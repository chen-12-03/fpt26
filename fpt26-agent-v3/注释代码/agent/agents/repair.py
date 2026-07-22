# =============================================================================
# FPT26 Track-A Agent v3 — RepairAgent（修复 Agent）
# =============================================================================
# 【功能概述】
#   RepairAgent 是最核心的 LLM Agent 之一。当 C 仿真（CSim）或 C 综合（Synth）
#   失败时，它通过 LLM 自动诊断和修复代码。
#
# 【这是你应该看的第 8 个文件】
#   理解了这个 Agent，其他两个 Agent（StructuralRepairAgent、OptimizeAgent）
#   的模式就非常相似了。
#
# 【修复循环（核心算法）】
#
#   for attempt in 1..max_attempts:
#       ┌─────────────────────────────────────────┐
#       │ 1. csim(current_kernel) → ToolResult    │  ← 运行 C 仿真
#       │    ├── if pass → csim_ok=true, return    │  ← 成功退出
#       │    └── if fail → continue                │
#       ├─────────────────────────────────────────┤
#       │ 2. normalize log                         │  ← 规范化日志（去ANSI、去路径）
#       │ 3. classify issue                        │  ← 分类问题类型
#       │    ├── compile_failure  → 编译错误       │
#       │    ├── csim_failure     → 功能错误       │
#       │    ├── synth_failure    → 综合失败       │
#       │    ├── timeout          → 超时           │
#       │    └── unknown          → 未知           │
#       ├─────────────────────────────────────────┤
#       │ 4. build prompt(packed context + error)  │  ← 构建 LLM Prompt
#       │ 5. llm.complete(system, prompt)          │  ← 调用 LLM 修改代码
#       │ 6. extract_code(response) → new kernel   │  ← 从 LLM 回复中提取代码
#       ├─────────────────────────────────────────┤
#       │ 7. validate_candidate(new_code)          │  ← 接口门控验证
#       │ 8. csim(new_code) → if pass → synth()    │  ← 验证新代码
#       │ 9. record_synth_gates()                  │  ← 频率/资源门控
#       └─────────────────────────────────────────┘
#
# 【设计原则】
#   1. 每次尝试完全由工具结果驱动 —— 不积累隐式状态
#   2. 接口契约验证在所有工具调用之前 —— 不浪费 credits 在非法代码上
#   3. 失败后给出不同的诊断，避免 LLM 重复同样的错误
# =============================================================================

from __future__ import annotations

from typing import Any

from agent.integrations.harness import ToolResult

from agent.agents.base import RunState
from agent.analysis.issue_classifier import IssueClassifier   # 问题分类器
from agent.analysis.log_normalizer import LogNormalizer       # 日志规范化器
from agent.prompts import REPAIR_SYSTEM, build_repair_prompt  # Prompt 模板
from agent.candidate.validator import extract_code            # 代码提取（从 LLM 回复中提取 ```cpp 块）


class RepairAgent:
    """
    迭代修复 C 仿真或 C 综合失败的内核代码。

    循环:
        1. 复用流水线已有的失败结果，或运行 csim(current_kernel) → ToolResult
        2. 如果通过 → 成功退出（修复成功）
        3. 如果失败 → 规范化日志，分类问题
        4. 用错误上下文构建 Prompt
        5. llm.complete(system, prompt) → 获取 LLM 响应
        6. extract_code(response) → 提取新内核代码
        7. 验证新代码：接口门控 → CSim → Synth → 频率/资源门控
        8. 跳回步骤 1（最多 max_attempts 次）

    这是刻意保持显式的设计 —— 没有隐藏的抽象层。
    """

    def __init__(
        self,
        llm: Any,
        max_attempts: int = 3,
    ) -> None:
        """
        参数:
            llm:          LLM 客户端（需要支持 complete(system, prompt) 方法）
            max_attempts: 最大修复尝试次数（默认 3）
        """
        self.llm = llm
        self.max_attempts = max_attempts
        self.log_normalizer = LogNormalizer()    # 日志规范化：去ANSI、去路径前缀
        self.issue_classifier = IssueClassifier() # 问题分类：编译错误/功能错误/超时等

    def run(self, state: RunState) -> RunState:
        """
        运行修复循环。返回更新后的 RunState。

        参数:
            state: 当前运行状态（包含内核代码、工具服务器、失败结果等）

        返回:
            更新后的 RunState（status 可能为 running/completed/failed）
        """
        task = state.task
        server = state.server
        stable_code = state.kernel  # 追踪最稳定的代码版本

        # ---- 尝试复用流水线已有的失败结果 ----
        # 流水线在调用 RepairAgent 之前已经运行了 CSim/Synth，
        # 最后一次结果可能就是失败的结果，不需要重新运行。
        failure = state.results[-1] if state.results else None
        if getattr(failure, "ok", True):
            failure = None  # 如果最后一个结果是成功的，则需要重新运行

        # ---- 主修复循环 ----
        for attempt in range(1, self.max_attempts + 1):
            # ═══════════════════════════════════════════════════════════════
            # 步骤 1-2: 运行 CSim（如果没有可复用的失败结果）
            # ═══════════════════════════════════════════════════════════════
            if failure is None:
                # 没有可复用的失败结果 → 运行 CSim
                failure = server.csim(stable_code)
                state.results.append(failure)
                if failure.ok:
                    # CSim 通过了，还需要检查 Synth
                    failure = server.synth(stable_code)
                    state.results.append(failure)
                if failure.ok:
                    # 全部通过！修复成功
                    state.csim_ok = True
                    state.synth_ok = True
                    state.kernel = stable_code
                    return state
            elif attempt == 1:
                # 复用了流水线的失败结果
                state.log(
                    f"repair: reusing pipeline {getattr(failure, 'kind', 'tool')} failure"
                )

            # ═══════════════════════════════════════════════════════════════
            # 步骤 3: 读取结果 → 规范化日志 → 分类问题
            # ═══════════════════════════════════════════════════════════════
            log_text = getattr(failure, "log", "") or ""
            phase = getattr(failure, "phase", "unknown") or "unknown"
            kind = getattr(failure, "kind", "csim") or "csim"

            # 规范化日志：去除 ANSI 转义序列、标准化文件路径
            normalized = self.log_normalizer.normalize(kind, phase, log_text)

            # 分类问题：确定失败类型和推荐操作
            # 可能的分类: compile_failure, csim_failure, synth_failure, timeout, unknown
            issue = self.issue_classifier.classify(failure, normalized)

            # ═══════════════════════════════════════════════════════════════
            # 步骤 4: 构建 LLM Prompt（打包上下文 + 错误信息）
            # ═══════════════════════════════════════════════════════════════
            prompt = build_repair_prompt(
                task=task,
                current_kernel=stable_code,
                normalized_log=normalized,
                issue=issue,
                attempt_feedback=(
                    {"attempt": attempt, "phase": phase}
                    if attempt > 1 else None  # 第二次尝试开始提供反馈
                ),
            )

            # ═══════════════════════════════════════════════════════════════
            # 步骤 5: 调用 LLM 修改代码
            # ═══════════════════════════════════════════════════════════════
            response = self.llm.complete(REPAIR_SYSTEM, prompt)
            new_code = extract_code(response)  # 从 LLM 回复中提取 ```cpp 代码块

            # 如果 LLM 没有返回任何修改，跳过这次尝试
            if new_code is None or new_code.strip() == stable_code.strip():
                state.log(f"repair attempt {attempt}: LLM returned no change")
                continue

            # ═══════════════════════════════════════════════════════════════
            # 步骤 6: 验证新代码（在花费 credits 之前先做免费检查）
            # ═══════════════════════════════════════════════════════════════
            from agent.candidate.validator import (
                mark_fully_verified,
                record_synth_gates,
                validate_candidate,
            )

            # 接口门控：检查函数签名、include、分隔符是否与原始代码一致
            if not validate_candidate(
                state, new_code,
                stage=f"repair_candidate_{attempt}",
                current_best=False,
            ):
                # 接口验证失败 → 构造一个人造的失败结果，下一轮提示 LLM
                validation = state.metadata.get("interface_validations", [{}])[-1]
                failure = ToolResult(
                    kind="csim", ok=False, phase="compile_error", return_code=-1,
                    log=(
                        "Candidate rejected by deterministic interface gate: "
                        + str(validation.get("reason", "unknown"))
                    ),
                    elapsed_s=0.0,
                )
                continue

            # ═══════════════════════════════════════════════════════════════
            # 步骤 7: 运行 CSim 验证新代码
            # ═══════════════════════════════════════════════════════════════
            cr = server.csim(new_code)
            state.results.append(cr)
            state.log(f"repair attempt {attempt}: {cr.brief()}")
            if not cr.ok:
                failure = cr  # CSim 失败 → 下一轮继续
                continue

            # ═══════════════════════════════════════════════════════════════
            # 步骤 8: 运行 Synth 验证可综合性
            # ═══════════════════════════════════════════════════════════════
            sr = server.synth(new_code)
            state.results.append(sr)
            state.log(f"repair attempt {attempt}: {sr.brief()}")
            if not sr.ok:
                failure = sr  # Synth 失败 → 下一轮继续
                continue

            # ═══════════════════════════════════════════════════════════════
            # 步骤 9: 频率/资源门控检查
            # ═══════════════════════════════════════════════════════════════
            if not record_synth_gates(state, sr, stage=f"repair_candidate_{attempt}", current_best=False):
                # 综合通过但频率 < 100MHz 或超出器件容量 → 丢弃
                failure = ToolResult(
                    kind="synth", ok=False, phase="target_gate_fail", return_code=-1,
                    log=(
                        "Candidate synthesis completed but failed the mandatory "
                        "100 MHz and/or device-capacity gate."
                    ),
                    elapsed_s=0.0, report=sr.report,
                )
                state.log(f"repair attempt {attempt}: target gate failed — discard")
                continue

            # ═══════════════════════════════════════════════════════════════
            # 全部通过！更新状态并返回
            # ═══════════════════════════════════════════════════════════════
            state.kernel = new_code
            state.csim_ok = True
            state.synth_ok = True
            state.status = "running"
            state.stop_reason = ""
            record_synth_gates(state, sr, stage=f"repair_candidate_{attempt}_accepted")

            # 提取延迟信息
            latency = (
                sr.report.latency_worst
                if sr.report and sr.report.latency_worst is not None
                else (sr.report.latency_avg if sr.report else None)
            )
            if latency is not None:
                state.best_latency = latency

            # 如果不是结构型任务，标记为完全验证
            if not task.requires_cosim:
                mark_fully_verified(state)

            state.log(f"repair: succeeded on attempt {attempt}")
            return state

        # ---- 所有尝试都用完了 ----
        state.kernel = stable_code  # 恢复为最稳定的代码
        state.status = "failed"
        state.stop_reason = "repair_failed"
        state.log(f"repair: failed after {self.max_attempts} attempts")
        return state
