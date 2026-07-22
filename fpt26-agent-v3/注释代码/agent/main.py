#!/usr/bin/env python3
# =============================================================================
# FPT26 Track-A Agent v3 — 程序入口 (CLI Entry Point)
# =============================================================================
# 【功能概述】
#   本文件是整个 Agent 系统的命令行入口。它负责：
#   1. 解析命令行参数
#   2. 根据 --run-role 参数分发到两条不同的执行路径：
#      - submission（提交模式）：运行完整的 Agent 流水线，产生优化后的内核代码
#      - evaluator（评分模式）：对已生成的内核代码进行正式评分
#   3. 处理各种错误场景，生成失败报告
#
# 【调用方式】
#   python -m agent.main --task tasks/projection_bugfix --mode baseline
#   python -m agent.main --task tasks/dotProduct_optimize --mode full
#   python -m agent.main --task tasks/residual_stream_deadlock --mode full --competition
#
# 【阅读顺序】
#   这是你应该看的第 2 个文件（在 cli.py 之后）
# =============================================================================

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 导入各个子系统模块
# ---------------------------------------------------------------------------
from agent.cli import parse_args                        # 命令行参数解析
from agent.integrations.harness import Budget            # 预算管理（credits 消耗追踪）
from agent.backends import create_llm                    # LLM 后端工厂（OpenRouter/OpenAI/离线）
from agent.runner import ToolServer                      # 工具服务器（CSim/Synth/CoSim 的执行器）
from agent.safety import redact_sensitive_text           # 敏感信息脱敏（防止 API key 泄露到日志）
from agent.model_compliance import model_compliance_evidence  # 模型合规性证据收集
from agent.task_io import TaskPreflightError, load_public_task  # 任务加载与预检
from agent.testbench import normalize_task_testbench_data  # 测试台数据规范化
from scoring.profiles import DEFAULT_SCORING_PROFILE     # 默认评分策略（balanced）


# ===========================================================================
# 辅助函数
# ===========================================================================

def _safe_error_message(exc: BaseException) -> str:
    """安全地获取异常消息：自动脱敏敏感信息（如路径、密钥等）"""
    return redact_sensitive_text(exc)


def _bootstrap_failure(*, output_root, task_id, run_role, status, stop_reason, exc) -> Path:
    """
    启动阶段失败处理：生成一份失败报告 JSON 文件。

    这发生在流水线尚未完全初始化时（比如任务加载失败、LLM 初始化失败等），
    此时无法走正常的报告流程，所以需要这个"兜底"函数。

    参数:
        output_root: 输出根目录
        task_id: 任务 ID
        run_role: 运行角色 (submission/evaluator)
        status: 最终状态
        stop_reason: 停止原因
        exc: 异常对象

    返回:
        生成的失败报告文件路径
    """
    from agent.reporting import write_failure_report
    return write_failure_report(
        output_dir=Path(output_root) / task_id,
        task_id=task_id, run_role=run_role,
        status=status, stop_reason=stop_reason,
        error_type=type(exc).__name__, error_message=_safe_error_message(exc),
    )


def _env_int(name: str, default: int) -> int:
    """从环境变量读取整数值，如果未设置或为空则返回默认值"""
    v = os.environ.get(name)
    return int(v) if v and v.strip() else default


# ===========================================================================
# Evaluator（评分者）角色
# ===========================================================================

def _run_evaluator(args, task_dir, output_root):
    """
    运行 Evaluator 流水线。

    Evaluator 角色是竞赛中的"裁判"：它读取 Submission 角色生成的内核代码，
    用隐藏的测试平台（hidden testbench）重新验证所有门控（Gate），
    然后计算正式评分。

    与 Submission 角色的关键区别：
    - 必须提供 --final-kernel 参数（待评分的内核文件路径）
    - 必须提供 --submission-evidence 参数（Submission 阶段产生的证据文件）
    - 使用隐藏的测试平台（而非公共测试平台）
    - 产出正式的评分报告（包含 Q_HW 分数）
    """
    # ---- 参数校验 ----
    if args.final_kernel is None:
        print("error: --final-kernel is required for --run-role evaluator", file=sys.stderr)
        return 2
    if args.submission_evidence is None:
        print("error: --submission-evidence is required for formal evaluator mode", file=sys.stderr)
        return 2

    try:
        from agent.evaluator import evaluate_final_kernel
        from agent.reporting import print_evaluation, write_run_report
        from agent.models import SubmissionEvidence

        # 加载 Submission 阶段产生的证据文件
        ep = args.submission_evidence.resolve()
        if not ep.is_file():
            print(f"error: submission evidence not found: {ep}", file=sys.stderr)
            return 2
        import json as _json
        submission_evidence = SubmissionEvidence.from_dict(
            _json.loads(ep.read_text(encoding="utf-8"))
        )

        # 执行正式评分（包含 hidden CSim、独立 anchor 评估等）
        final_state = evaluate_final_kernel(
            task_dir=task_dir, kernel_path=args.final_kernel,
            output_root=output_root, scoring_profile=args.scoring_profile,
            verbose=not args.quiet, submission_evidence=submission_evidence,
        )
        print(f"Evaluator report written to {write_run_report(final_state)}")
        print_evaluation(final_state)
        return _exit_code(final_state.status)

    except Exception as exc:
        rp = _bootstrap_failure(
            output_root=output_root, task_id=task_dir.name, run_role="evaluator",
            status="infrastructure_error", stop_reason="evaluator_exception", exc=exc,
        )
        print(f"error: evaluator failed: {type(exc).__name__}: {_safe_error_message(exc)}; "
              f"report={rp}", file=sys.stderr)
        return 6


# ===========================================================================
# Submission（提交者）角色 — 核心流水线入口
# ===========================================================================

def _run_submission(args, task_dir, output_root):
    """
    运行 Submission 流水线 — 这是整个系统最核心的执行路径。

    流水线包含 6 个阶段：

    阶段 1: Baseline CSim
        └── 用初始代码运行 C 仿真，建立基线

    阶段 2: Repair（修复）
        └── 如果 CSim 或综合失败，LLM Agent 尝试自动修复代码
        └── 修复循环：CSim → 失败 → 分类问题 → 构建 Prompt → LLM 修改 → 提取代码 → 重试

    阶段 3: Synthesis（综合）
        └── 调用 Vitis HLS 将 C++ 综合成 RTL 电路
        └── 检查频率门控（≥100MHz）和资源门控（不超过器件容量）

    阶段 4: CoSim（联合仿真）
        └── 仅对结构型任务（有 streaming/dataflow 的任务）
        └── C/RTL 联合仿真验证

    阶段 5: Optimization（优化）
        └── LLM 驱动的迭代优化，通过添加 HLS pragma 降低延迟/优化资源
        └── 优化策略由 scoring profile 决定（balanced/extreme_speed/extreme_speed_capped）

    阶段 6: Public Acceptance（公共验收）
        └── 最终检查所有门控，持久化最终内核文件
    """
    from agent.integrations.task_repository import PublicTaskRepository
    from agent.agents.base import AgentConfig
    from agent.pipeline.submission import run_submission
    from agent.reporting import print_evaluation, write_run_report
    from agent.models import SubmissionEvidence
    import json as _json

    # ---- 1. 加载任务（只访问公共工件，不接触隐藏/参考目录）----
    try:
        task, _ = PublicTaskRepository().load(task_dir)
        _, preflight = load_public_task(task_dir)
    except (TaskPreflightError, Exception) as exc:
        rp = _bootstrap_failure(
            output_root=output_root, task_id=task_dir.name, run_role="submission",
            status="failed", stop_reason="task_preflight_failed", exc=exc,
        )
        print(f"error: task preflight failed: {_safe_error_message(exc)}; report={rp}",
              file=sys.stderr)
        return 4

    # ---- 2. 预算校验 ----
    # Budget 是云端 credits 的限制，每个工具调用（CSim/Synth/CoSim）消耗固定数量
    if args.budget is not None and (args.budget <= 0 or args.budget > task.budget):
        err = TaskPreflightError(f"budget override {args.budget} invalid (must be 1..{task.budget})")
        rp = _bootstrap_failure(
            output_root=output_root, task_id=task.id, run_role="submission",
            status="failed", stop_reason="budget_override_invalid", exc=err,
        )
        print(f"error: {_safe_error_message(err)}; report={rp}", file=sys.stderr)
        return 4
    total_budget = args.budget if args.budget is not None else task.budget

    # ---- 3. 创建工具服务器 ----
    # ToolServer 是 CSim/Synth/CoSim 的统一入口，内部委托给 SecureToolExecutor
    # 每次工具调用会消耗 Budget，并记录到 transcript（调用日志）
    server = ToolServer(task, Budget(total=total_budget), Path(output_root) / task.id / "agent")

    # ---- 4. 创建 LLM 后端 ----
    # 根据 --backend 参数选择合适的 LLM：
    #   auto: 自动检测环境变量中的 API key
    #   openrouter: 使用 OpenRouter API
    #   custom: 自定义兼容 OpenAI 的 API
    #   scripted: 离线模式（回放预定义的响应，用于测试）
    llm = None
    if args.mode in {"auto", "repair", "optimize", "structural", "full"}:
        try:
            llm = create_llm(args.backend)
        except RuntimeError as exc:
            rp = _bootstrap_failure(
                output_root=output_root, task_id=task.id, run_role="submission",
                status="infrastructure_error", stop_reason="llm_init_failed", exc=exc,
            )
            print(f"error: {_safe_error_message(exc)}; report={rp}", file=sys.stderr)
            return 6

    # ---- 5. 配置 + 启动流水线 ----
    # AgentConfig 控制流水线中各个 Agent 的行为参数
    config = AgentConfig(
        mode=args.mode,                          # auto | baseline | repair | optimize | structural | full
        run_role="submission",
        competition=args.competition,            # 是否启用竞争模式（多条独立策略并行）
        output_root=output_root,
        score=False,                             # Submission 角色不做评分
        scoring_profile=args.scoring_profile,    # balanced | extreme_speed | extreme_speed_capped
        verbose=not args.quiet,
        max_repair_attempts=args.max_repair_attempts or _env_int("FPT26_MAX_REPAIR_ATTEMPTS", 3),
        max_optimization_rounds=args.max_optimization_rounds or _env_int("FPT26_MAX_OPTIMIZATION_CANDIDATES", 5),
        max_structural_attempts=args.max_structural_attempts or _env_int("FPT26_MAX_STRUCTURAL_REPAIR_ATTEMPTS", 3),
    )

    # 启动！这是整个系统的核心调用
    final_state = run_submission(
        task=task, config=config, server=server, llm=llm,
        run_root=Path(output_root) / task.id / "agent",
        total_budget=total_budget,
    )

    # ---- 6. 记录元数据和证据 ----
    final_state.metadata["task_preflight"] = preflight.to_dict()
    final_state.metadata["official_budget"] = task.budget
    final_state.metadata["model_compliance"] = model_compliance_evidence(
        getattr(llm, "model", None) if llm else None,
        explicit_open_source=os.environ.get("FPT26_LLM_OPEN_SOURCE", "").strip().lower() in {"1", "true", "yes"},
        license_evidence=os.environ.get("FPT26_LLM_LICENSE") or os.environ.get("FPT26_LLM_LICENSE_EVIDENCE"),
        source_evidence=os.environ.get("FPT26_LLM_SOURCE"),
    )

    # ---- 7. 生成报告和提交证据 ----
    print(f"Run report written to {write_run_report(final_state)}")
    print_evaluation(final_state)

    # SubmissionEvidence 是提交给 Evaluator 的证据文件
    # 包含内核摘要、credits 消耗、各门控结果等
    ev = SubmissionEvidence.from_run_state(final_state, run_id=f"{task.id}_{final_state.status}")
    ep = Path(output_root) / task.id / "submission_evidence.json"
    ep.parent.mkdir(parents=True, exist_ok=True)
    ep.write_text(_json.dumps(ev.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                  encoding="utf-8")
    print(f"Submission evidence written to {ep}")

    # ---- 8. 打印工具调用摘要 ----
    print(f"\n=== Agent run complete: {final_state.status} ===")
    for entry in server.transcript:
        print(f"  #{entry.n:<2} {entry.detail}   [spent {entry.spent}/{total_budget}]")
    print(f"  {server.budget.summary()}\n")
    return _exit_code(final_state.status)


# ===========================================================================
# 主函数
# ===========================================================================

def main(argv: list[str] | None = None) -> int:
    """
    程序入口。

    流程:
    1. 解析命令行参数
    2. 验证任务目录存在
    3. 根据 --run-role 分发到 _run_evaluator 或 _run_submission
    """
    args = parse_args(argv)

    # 解析任务目录
    task_dir = args.task.resolve()
    if not task_dir.is_dir():
        print(f"error: task directory not found: {task_dir}", file=sys.stderr)
        return 2
    output_root = str(args.output_root or os.environ.get("FPT26_RUN_OUTPUT_ROOT", "runs"))

    # 角色分发
    if args.run_role == "evaluator":
        return _run_evaluator(args, task_dir, output_root)
    return _run_submission(args, task_dir, output_root)


def _exit_code(status: str) -> int:
    """
    将运行状态映射为 Unix 退出码。

    退出码约定:
        0 = completed（成功完成）
        4 = failed（流水线失败）
        5 = budget_exceeded（预算耗尽）
        6 = infrastructure_error（基础设施错误，如 LLM 初始化失败）
    """
    if status == "completed":
        return 0
    if status == "budget_exceeded":
        return 5
    if status == "infrastructure_error":
        return 6
    return 4


if __name__ == "__main__":
    sys.exit(main())
