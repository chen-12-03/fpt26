# =============================================================================
# FPT26 Track-A Agent v3 — Submission 流水线编排（核心！）
# =============================================================================
# 【功能概述】
#   本文件是 **整个系统最核心的编排代码**。
#   它定义了 Submission 角色的完整流水线：从初始代码开始，依次运行
#   CSim → Repair → Synthesis → CoSim → Optimization → Public Acceptance，
#   最终产生通过所有门控的优化内核代码。
#
# 【这是你应该看的第 5 个文件】
#   理解了 RunState 之后，看这个文件就能掌握整个系统的运行逻辑。
#
# 【流水线 6 阶段总览】
#
#   阶段 1: Baseline CSim (基线 C 仿真)
#   ├── 用任务初始代码运行 C 仿真
#   └── 记录 csim_ok 状态
#
#   阶段 2: Repair (LLM 修复)
#   ├── 仅在 mode ∈ {auto, repair, full} 且 csim_ok=False 时运行
#   ├── RepairAgent 循环: CSim → 失败 → 分类问题 → LLM 修改 → 重试
#   └── 最多 max_repair_attempts 次
#
#   阶段 3: Synthesis (C 综合)
#   ├── 调用 Vitis HLS 将 C++ 综合成 RTL
#   ├── 检查频率门控 (≥100MHz) 和资源门控 (不超出器件容量)
#   └── 如综合失败，同样触发 RepairAgent
#
#   阶段 4: CoSim (C/RTL 联合仿真)
#   ├── 仅对结构型任务 (requires_cosim=True) 运行
#   ├── CoSim 使用深度为 2 的有界 FIFO（CSim 用无界 FIFO）
#   └── 如 CoSim 失败，触发 StructuralRepairAgent
#
#   阶段 5: Optimization (LLM 优化)
#   ├── 仅在 mode ∈ {auto, optimize, full} 且所有门控通过时运行
#   ├── OptimizeAgent 循环: Synth → 分析 → LLM 优化 → 验证 → 比较 Q_HW
#   └── 最多 max_optimization_rounds 轮
#
#   阶段 6: Public Acceptance (公共验收)
#   ├── 最终检查所有门控状态
#   ├── 标记为 "fully verified" 或记录失败原因
#   └── 持久化最终内核文件
# =============================================================================

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.agents.base import AgentConfig, RunState
from agent.models import SubmissionEvidence
from agent.candidate.validator import CandidateValidator, ValidationPlan


# ===========================================================================
# run_submission — 主入口函数
# ===========================================================================

def run_submission(
    *,
    task: Any,
    config: AgentConfig,
    server: Any,
    llm: Any,
    run_root: Path,
    total_budget: int,
) -> RunState:
    """
    运行完整的 Submission 流水线，返回终止状态的 RunState。

    流程:
    1. 构造初始 RunState（包含任务、服务器、LLM、配置、初始内核代码）
    2. 注入 CandidateValidator（候选验证器，用于后续门控检查）
    3. 运行流水线（6 个阶段）
    4. 持久化最终内核文件
    5. 返回 RunState

    参数:
        task:         HLS 任务对象
        config:       Agent 配置
        server:       工具服务器（提供 csim/synth/cosim）
        llm:          LLM 客户端（可能为 None）
        run_root:     运行输出根目录
        total_budget: 总 credits 预算

    返回:
        终止状态的 RunState（status ∈ {completed, failed, budget_exceeded, infrastructure_error}）
    """
    # ---- 1. 构造初始状态 ----
    state = RunState(
        task=task,
        server=server,
        llm=llm,
        config=config,
        kernel=task.kernel_code,               # 使用任务提供的初始内核代码
        safe_fallback_kernel=task.kernel_code,  # 安全回退也设置为初始代码
    )
    state.metadata["run_role"] = "submission"
    state.metadata["effective_budget"] = total_budget
    state.metadata["official_budget"] = task.budget

    # ---- 2. 注入候选验证器 ----
    # CandidateValidator 是门控检查的唯一权威来源
    # 后续的 Agent 和流水线阶段都通过它来验证候选代码
    state.metadata["_candidate_validator"] = CandidateValidator(
        task, task.kernel_code,
    )

    # ---- 3. 运行流水线 ----
    _run_pipeline(state, config, task, server, llm)

    # ---- 4. 最终化 ----
    # 如果流水线没有调用 finalize（比如中途失败），这里补一次
    if not state.metadata.get("finalized"):
        _finalize(state)

    return state


# ===========================================================================
# _run_pipeline — 6 阶段流水线的实现
# ===========================================================================

def _run_pipeline(state: RunState, config: Any, task: Any, server: Any, llm: Any) -> None:
    """
    直接运行流水线的 6 个阶段，不通过 workflow.py 的外观层。

    每个阶段直接修改 state（in-place mutation）。
    阶段函数来自 candidate/validator.py（门控兼容函数）。

    设计要点:
    - 每个阶段读取前一阶段设置的 state 字段
    - 任何门控失败都会导致后续阶段被跳过（通过早期 return 或条件检查）
    - 所有 LLM Agent 调用都在 try/except 中，防止 ImportError 破坏流水线
    """
    from agent.candidate.validator import (
        validate_candidate,    # 接口门控检查
        record_synth_gates,    # 综合门控记录
        record_cosim_gate,     # CoSim 门控记录
        mark_fully_verified,   # 标记为"完全验证"
    )
    from agent.runner import CSimTool, SynthTool, CoSimTool

    mode = config.mode
    state.log(f"task={task.id} type={task.type} mode={mode} "
              f"budget={getattr(getattr(server, 'budget', None), 'total', '?')}")

    # ═══════════════════════════════════════════════════════════════════
    # 阶段 1: Baseline CSim（基线 C 仿真）
    # ═══════════════════════════════════════════════════════════════════
    # 首先验证接口契约（函数签名、include 是否被保留）
    if not validate_candidate(state, state.kernel, stage="baseline"):
        return  # 接口门控失败，无法继续

    # 运行 C 仿真，这是所有后续操作的前提
    r = server.csim(state.kernel)
    state.results.append(r)     # 记录工具调用结果
    state.csim_ok = r.ok        # 更新门控状态
    state.log(f"csim: {r.brief()}")

    # ═══════════════════════════════════════════════════════════════════
    # 阶段 2: Repair（LLM 修复 CSIM 失败）
    # ═══════════════════════════════════════════════════════════════════
    # 仅在以下条件同时满足时运行：
    # - mode 是 auto/repair/full（需要 LLM 的模式）
    # - CSim 失败
    if mode in ("auto", "repair", "full") and not state.csim_ok:
        try:
            from agent.agents.repair import RepairAgent
            agent = RepairAgent(llm=llm, max_attempts=config.max_repair_attempts)
            agent.run(state)  # RepairAgent 内部运行修复循环
        except ImportError as exc:
            state.log(f"repair: RepairAgent import failed: {exc}")
            # 记录基础设施错误，但不终止流水线
            state.metadata.setdefault("infrastructure_errors", []).append({
                "step": "repair", "error": f"ImportError: {exc}",
            })

    # ═══════════════════════════════════════════════════════════════════
    # 阶段 3: Synthesis（C 综合 + 频率/资源门控）
    # ═══════════════════════════════════════════════════════════════════
    # CSim 通过后才能综合
    if state.csim_ok:
        r = server.synth(state.kernel)
        state.results.append(r)
        state.synth_ok = r.ok
        # record_synth_gates 会同时检查频率门控（≥100MHz）和资源门控（不超容量）
        record_synth_gates(state, r, stage="pipeline_synth")
        state.log(f"synth: {r.brief()}")

    # 综合失败也触发修复（如果 CSim 通过但综合失败，说明代码有可综合性问题）
    if mode in ("auto", "repair", "full") and state.csim_ok and not state.synth_ok:
        try:
            from agent.agents.repair import RepairAgent
            agent = RepairAgent(llm=llm, max_attempts=config.max_repair_attempts)
            agent.run(state)
        except ImportError as exc:
            state.log(f"synth_repair: RepairAgent import failed: {exc}")
            state.metadata.setdefault("infrastructure_errors", []).append({
                "step": "synth_repair", "error": f"ImportError: {exc}",
            })

    # ═══════════════════════════════════════════════════════════════════
    # 阶段 4: CoSim（C/RTL 联合仿真 — 仅结构型任务）
    # ═══════════════════════════════════════════════════════════════════
    # CoSim 只在结构型任务（有 streaming/dataflow）时需要
    # CSim 使用无界 FIFO，隐藏了死锁问题；CoSim 使用深度为 2 的有界 FIFO
    if task.requires_cosim and state.synth_ok:
        r = server.cosim(state.kernel)
        state.results.append(r)
        record_cosim_gate(state, r, stage="pipeline_cosim", source_code=state.kernel)
        state.log(f"cosim: {r.brief()}")

    # CoSim 失败触发结构修复 Agent（专门处理 streaming/dataflow 死锁）
    if task.requires_cosim and mode in ("auto", "structural", "full") and not state.cosim_ok:
        try:
            from agent.agents.structural import StructuralRepairAgent
            agent = StructuralRepairAgent(llm=llm, max_attempts=config.max_structural_attempts)
            agent.run(state)
        except ImportError as exc:
            state.log(f"structural_repair: StructuralRepairAgent import failed: {exc}")
            state.metadata.setdefault("infrastructure_errors", []).append({
                "step": "structural_repair", "error": f"ImportError: {exc}",
            })

    # ═══════════════════════════════════════════════════════════════════
    # 阶段 5: Optimization（LLM 驱动的性能优化）
    # ═══════════════════════════════════════════════════════════════════
    # 仅在所有门控都通过时才优化（代码必须首先正确，然后才能优化）
    gates_ok = (state.csim_ok and state.synth_ok and state.interface_ok
                and state.frequency_ok and state.resource_ok
                and (not task.requires_cosim or state.cosim_ok))

    if mode in ("auto", "optimize", "full") and gates_ok:
        try:
            from agent.agents.optimize import OptimizeAgent
            agent = OptimizeAgent(
                llm=llm,
                max_rounds=config.max_optimization_rounds,
                scoring_profile=getattr(config, "scoring_profile", "balanced"),
            )
            agent.run(state)  # OptimizeAgent 内部运行优化循环
        except ImportError as exc:
            state.log(f"optimize: OptimizeAgent import failed: {exc}")
            state.metadata.setdefault("infrastructure_errors", []).append({
                "step": "optimize", "error": f"ImportError: {exc}",
            })

    # ═══════════════════════════════════════════════════════════════════
    # 阶段 6: Public Acceptance（公共验收）
    # ═══════════════════════════════════════════════════════════════════
    # 收集所有失败的门控
    failures = []
    if not state.interface_ok:
        failures.append("interface_failed")
    if not state.csim_ok:
        failures.append("csim_failed")
    if not state.synth_ok:
        failures.append("synth_failed")
    if not state.frequency_ok:
        failures.append("frequency_failed")
    if not state.resource_ok:
        failures.append("resource_failed")
    if task.requires_cosim and not state.cosim_ok:
        failures.append("cosim_failed")

    if failures:
        # 有任何失败 → 标记为 failed
        state.status = "failed"
        state.stop_reason = failures[0]  # 第一个失败原因
        state.metadata["public_acceptance"] = {"ok": False, "failures": failures}
    else:
        # 全部通过 → 标记为 completed
        mark_fully_verified(state)
        state.status = "completed"
        state.stop_reason = ""
        state.metadata["public_acceptance"] = {"ok": True, "failures": []}


# ===========================================================================
# _finalize — 持久化最终内核文件
# ===========================================================================

def _finalize(state: RunState) -> None:
    """
    将最终内核写入文件系统。

    优先级:
    1. last_verified_kernel（最后通过所有门控的版本）— 最好的情况
    2. safe_fallback_kernel（安全回退版本）— 失败时回退
    3. state.kernel（当前内核）— 最后的兜底

    输出路径: {output_root}/{task_id}/final_{kernel_name}
    """
    # 确定最终内核代码
    if getattr(state, "last_verified_kernel", None) is not None:
        state.kernel = state.last_verified_kernel
    elif state.status in ("failed", "budget_exceeded", "infrastructure_error"):
        if getattr(state, "safe_fallback_kernel", None) is not None:
            state.kernel = state.safe_fallback_kernel

    # 写入文件
    out = Path(state.config.output_root) / state.task.id
    out.mkdir(parents=True, exist_ok=True)
    kernel_path = out / f"final_{state.task.kernel_name}"
    kernel_path.write_text(state.kernel, encoding="utf-8")
    state.log(f"final kernel → {kernel_path}")
    state.metadata["finalized"] = True
    state.metadata["final_kernel_path"] = str(kernel_path)
