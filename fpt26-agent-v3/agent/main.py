#!/usr/bin/env python3
"""CLI entry point for the fpt26-agent-v3 pipeline.

Usage::

    python -m agent.main --task tasks/projection_bugfix --mode baseline
    python -m agent.main --task tasks/dotProduct_optimize --mode full
    python -m agent.main --task tasks/residual_stream_deadlock --mode full --competition
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from llm4hls.budget import Budget
from agent.agents.base import RunState
from agent.backends import create_llm
from agent.runner import ToolServer
from agent.safety import redact_sensitive_text
from agent.model_compliance import model_compliance_evidence
from agent.task_io import TaskPreflightError, load_public_task
from agent.testbench import normalize_task_testbench_data
from agent.workflow import build_pipeline, step_finalize
from scoring.profiles import DEFAULT_SCORING_PROFILE, SCORING_PROFILE_CHOICES


def _safe_error_message(exc: BaseException) -> str:
    """Remove endpoint/token-shaped strings before stderr or reports."""

    return redact_sensitive_text(exc)


def _bootstrap_failure(
    *,
    output_root: str,
    task_id: str,
    run_role: str,
    status: str,
    stop_reason: str,
    exc: BaseException,
) -> Path:
    from agent.reporting import write_failure_report

    return write_failure_report(
        output_root=output_root,
        task_id=task_id,
        run_role=run_role,
        status=status,
        stop_reason=stop_reason,
        error_type=type(exc).__name__,
        error_message=_safe_error_message(exc),
    )


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="FPT26 Track-A agent v3 — pipeline-based LLM4HLS agent with V3 scoring"
    )
    p.add_argument("--task", required=True, type=Path, help="Path to official task directory")
    p.add_argument(
        "--mode",
        choices=["auto", "baseline", "repair", "optimize", "structural", "full"],
        default="auto",
        help="Agent operating mode (default: tool-result-driven auto)",
    )
    p.add_argument(
        "--run-role",
        choices=["submission", "evaluator"],
        default="submission",
        help="Public-only submission agent or isolated hidden/reference evaluator",
    )
    p.add_argument(
        "--final-kernel",
        type=Path,
        default=None,
        help="Final kernel artifact to grade (required for --run-role evaluator)",
    )
    p.add_argument("--output-root", type=Path, default=None, help="Run artifact output root")
    p.add_argument("--budget", type=int, default=None, help="Override task credit budget")
    p.add_argument(
        "--backend", choices=["auto", "openrouter", "custom", "scripted"],
        default="auto", help="LLM backend selection (default: auto-detect)",
    )
    p.add_argument(
        "--competition",
        action="store_true",
        help=(
            "Evaluate independent optimization strategy lanes sequentially "
            "and select the highest measured Q_HW"
        ),
    )
    p.add_argument("--max-repair-attempts", type=int, default=None)
    p.add_argument("--max-optimization-rounds", type=int, default=None)
    p.add_argument("--max-structural-attempts", type=int, default=None)
    p.add_argument("--no-score", action="store_true", help="Skip hidden-testbench scoring")
    p.add_argument(
        "--scoring-profile",
        choices=SCORING_PROFILE_CHOICES,
        default=DEFAULT_SCORING_PROFILE,
        help=(
            "Hardware trade-off profile: balanced (0.55/0.45), "
            "extreme_speed (0.70/0.30), or extreme_speed_capped "
            "(0.70/0.30 without area-saving rewards)"
        ),
    )
    p.add_argument("--quiet", action="store_true", help="Suppress step-by-step log output")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # 1. Resolve task and output role ----------------------------------------
    task_dir = args.task.resolve()
    if not task_dir.is_dir():
        print(f"error: task directory not found: {task_dir}", file=sys.stderr)
        return 2
    output_root = str(args.output_root or os.environ.get("FPT26_RUN_OUTPUT_ROOT", "runs"))

    if args.run_role == "evaluator":
        if args.final_kernel is None:
            print(
                "error: --final-kernel is required for --run-role evaluator",
                file=sys.stderr,
            )
            return 2
        try:
            from agent.evaluator import evaluate_final_kernel
            from agent.reporting import print_evaluation, write_run_report

            final_state = evaluate_final_kernel(
                task_dir=task_dir,
                kernel_path=args.final_kernel,
                output_root=output_root,
                scoring_profile=args.scoring_profile,
                verbose=not args.quiet,
            )
            report_path = write_run_report(final_state)
            print(f"Evaluator report written to {report_path}")
            print_evaluation(final_state)
            return _exit_code(final_state.status)
        except Exception as exc:
            report_path = _bootstrap_failure(
                output_root=output_root,
                task_id=task_dir.name,
                run_role="evaluator",
                status="infrastructure_error",
                stop_reason="evaluator_exception",
                exc=exc,
            )
            print(
                f"error: evaluator failed: {type(exc).__name__}: "
                f"{_safe_error_message(exc)}; report={report_path}",
                file=sys.stderr,
            )
            return 6

    # Submission loading is public-only: no hidden/reference paths are opened.
    try:
        task, preflight = load_public_task(task_dir)
    except TaskPreflightError as exc:
        report_path = _bootstrap_failure(
            output_root=output_root,
            task_id=task_dir.name,
            run_role="submission",
            status="failed",
            stop_reason="task_preflight_failed",
            exc=exc,
        )
        print(
            f"error: task preflight failed: {_safe_error_message(exc)}; "
            f"report={report_path}",
            file=sys.stderr,
        )
        return 4
    normalized_fixtures = normalize_task_testbench_data(
        task, include_hidden=False
    )
    if normalized_fixtures:
        print(
            "Testbench text fixtures normalized to LF: "
            + ", ".join(normalized_fixtures),
            flush=True,
        )

    # 2. Budget & ToolServer -------------------------------------------------
    if args.budget is not None and (
        args.budget <= 0 or args.budget > task.budget
    ):
        error = TaskPreflightError(
            f"submission budget override {args.budget} must be positive "
            f"and no greater than official task budget {task.budget}"
        )
        report_path = _bootstrap_failure(
            output_root=output_root,
            task_id=task.id,
            run_role="submission",
            status="failed",
            stop_reason="budget_override_invalid",
            exc=error,
        )
        print(
            f"error: {_safe_error_message(error)}; report={report_path}",
            file=sys.stderr,
        )
        return 4
    total_budget = args.budget if args.budget is not None else task.budget
    budget = Budget(total=total_budget)
    run_root = Path(output_root) / task.id / "agent"
    server = ToolServer(task, budget, run_root)

    # 3. LLM client (only if mode requires it) --------------------------------
    llm = None
    modes_needing_llm = {"auto", "repair", "optimize", "structural", "full"}
    if args.mode in modes_needing_llm:
        try:
            llm = create_llm(args.backend)
        except RuntimeError as exc:
            report_path = _bootstrap_failure(
                output_root=output_root,
                task_id=task.id,
                run_role="submission",
                status="infrastructure_error",
                stop_reason="llm_initialization_failed",
                exc=exc,
            )
            print(
                f"error: {_safe_error_message(exc)}; report={report_path}",
                file=sys.stderr,
            )
            return 6

    # 4. Build config ---------------------------------------------------------
    from agent.agents.base import AgentConfig

    config = AgentConfig(
        mode=args.mode,
        run_role="submission",
        competition=args.competition,
        output_root=output_root,
        # Hidden/reference grading belongs exclusively to evaluator mode.
        score=False,
        scoring_profile=args.scoring_profile,
        verbose=not args.quiet,
        max_repair_attempts=args.max_repair_attempts or _env_int("FPT26_MAX_REPAIR_ATTEMPTS", 3),
        max_optimization_rounds=args.max_optimization_rounds or _env_int("FPT26_MAX_OPTIMIZATION_CANDIDATES", 5),
        max_structural_attempts=args.max_structural_attempts or _env_int("FPT26_MAX_STRUCTURAL_REPAIR_ATTEMPTS", 3),
    )

    # 5. Build and run pipeline ----------------------------------------------
    pipeline = build_pipeline(config=config, task=task, server=server, llm=llm)

    state = RunState(
        task=task,
        server=server,
        llm=llm,
        config=config,
        kernel=task.kernel_code,
        safe_fallback_kernel=task.kernel_code,
    )
    state.metadata["task_preflight"] = preflight.to_dict()
    state.metadata["run_role"] = "submission"
    state.metadata["official_budget"] = task.budget
    state.metadata["effective_budget"] = total_budget
    license_evidence = os.environ.get("FPT26_LLM_LICENSE") or os.environ.get(
        "FPT26_LLM_LICENSE_EVIDENCE"
    )
    source_evidence = os.environ.get("FPT26_LLM_SOURCE")
    explicit_open_source = os.environ.get(
        "FPT26_LLM_OPEN_SOURCE", ""
    ).strip().lower() in {"1", "true", "yes"}
    state.metadata["model_compliance"] = model_compliance_evidence(
        getattr(llm, "model", None) if llm is not None else None,
        explicit_open_source=explicit_open_source,
        license_evidence=license_evidence,
        source_evidence=source_evidence,
    )

    final_state = pipeline.run(state)
    if not final_state.metadata.get("finalized"):
        final_state = step_finalize(final_state)

    # 5. Persist run report --------------------------------------------------
    from agent.reporting import print_evaluation, write_run_report

    report_path = write_run_report(final_state)
    print(f"Run report written to {report_path}")
    print_evaluation(final_state)

    # 6. Print results -------------------------------------------------------
    print(f"\n=== Agent run complete: {final_state.status} ===")
    print(f"Transcript ({len(server.transcript)} tool calls):")
    for entry in server.transcript:
        print(f"  #{entry.n:<2} {entry.detail}   [spent {entry.spent}/{total_budget}]")
    print(f"  {budget.summary()}")
    print()

    return _exit_code(final_state.status)


def _exit_code(status: str) -> int:
    if status == "completed":
        return 0
    if status == "budget_exceeded":
        return 5
    if status == "infrastructure_error":
        return 6
    return 4


if __name__ == "__main__":
    sys.exit(main())
