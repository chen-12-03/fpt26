#!/usr/bin/env python3
"""CLI entry point for the fpt26-agent-v3 pipeline.

Usage::

    python -m agent.main --task tasks/projection_bugfix --mode baseline
    python -m agent.main --task tasks/dotProduct_optimize --mode full
    python -m agent.main --task tasks/residual_stream_deadlock --mode full --competition
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from agent.cli import parse_args
from agent.integrations.harness import Budget
from agent.backends import create_llm
from agent.runner import ToolServer
from agent.safety import redact_sensitive_text
from agent.model_compliance import model_compliance_evidence
from agent.task_io import TaskPreflightError, load_public_task
from agent.testbench import normalize_task_testbench_data
from scoring.profiles import DEFAULT_SCORING_PROFILE
from agent.console_ui import artifact, configure as configure_console, error, run_header


def _safe_error_message(exc: BaseException) -> str:
    return redact_sensitive_text(exc)


def _bootstrap_failure(*, output_root, task_id, run_role, status, stop_reason, exc) -> Path:
    from agent.reporting import write_failure_report
    return write_failure_report(
        output_dir=Path(output_root) / task_id,
        task_id=task_id, run_role=run_role,
        status=status, stop_reason=stop_reason,
        error_type=type(exc).__name__, error_message=_safe_error_message(exc),
    )


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v and v.strip() else default


def _run_evaluator(args, task_dir, output_root):
    """Run the evaluator pipeline."""
    if args.final_kernel is None:
        error("--final-kernel is required for --run-role evaluator")
        return 2
    if args.submission_evidence is None:
        error("--submission-evidence is required for formal evaluator mode")
        return 2
    try:
        from agent.evaluator import evaluate_final_kernel
        from agent.reporting import print_evaluation, write_run_report
        from agent.models import SubmissionEvidence

        ep = args.submission_evidence.resolve()
        if not ep.is_file():
            error(f"submission evidence not found: {ep}")
            return 2
        import json as _json
        submission_evidence = SubmissionEvidence.from_dict(_json.loads(ep.read_text(encoding="utf-8")))

        final_state = evaluate_final_kernel(
            task_dir=task_dir, kernel_path=args.final_kernel,
            output_root=output_root, scoring_profile=args.scoring_profile,
            verbose=not args.quiet, submission_evidence=submission_evidence,
        )
        report_path = write_run_report(final_state)
        print_evaluation(final_state)
        artifact("Evaluator report", report_path)
        return _exit_code(final_state.status)
    except Exception as exc:
        rp = _bootstrap_failure(output_root=output_root, task_id=task_dir.name, run_role="evaluator",
                                status="infrastructure_error", stop_reason="evaluator_exception", exc=exc)
        error(f"evaluator failed: {type(exc).__name__}: {_safe_error_message(exc)}; report={rp}")
        return 6


def _run_submission(args, task_dir, output_root):
    """Run the submission pipeline (extracted from main for clarity)."""
    from agent.integrations.task_repository import PublicTaskRepository
    from agent.agents.base import AgentConfig
    from agent.pipeline.submission import run_submission
    from agent.reporting import print_evaluation, write_run_report
    from agent.models import SubmissionEvidence
    import json as _json

    try:
        task, _ = PublicTaskRepository().load(task_dir)
        _, preflight = load_public_task(task_dir)
    except (TaskPreflightError, Exception) as exc:
        rp = _bootstrap_failure(output_root=output_root, task_id=task_dir.name, run_role="submission",
                                status="failed", stop_reason="task_preflight_failed", exc=exc)
        error(f"task preflight failed: {_safe_error_message(exc)}; report={rp}")
        return 4

    # Budget
    if args.budget is not None and (args.budget <= 0 or args.budget > task.budget):
        err = TaskPreflightError(f"budget override {args.budget} invalid (must be 1..{task.budget})")
        rp = _bootstrap_failure(output_root=output_root, task_id=task.id, run_role="submission",
                                status="failed", stop_reason="budget_override_invalid", exc=err)
        error(f"{_safe_error_message(err)}; report={rp}")
        return 4
    total_budget = args.budget if args.budget is not None else task.budget

    run_header(
        task_id=task.id,
        task_type=task.type,
        mode=args.mode,
        backend=args.backend,
        budget=total_budget,
        output_root=str(Path(output_root) / task.id),
    )

    server = ToolServer(task, Budget(total=total_budget), Path(output_root) / task.id / "agent")

    # LLM
    llm = None
    if args.mode in {"auto", "repair", "optimize", "structural", "full"}:
        try:
            llm = create_llm(args.backend)
        except RuntimeError as exc:
            rp = _bootstrap_failure(output_root=output_root, task_id=task.id, run_role="submission",
                                    status="infrastructure_error", stop_reason="llm_init_failed", exc=exc)
            error(f"{_safe_error_message(exc)}; report={rp}")
            return 6

    # Config + Pipeline
    config = AgentConfig(
        mode=args.mode, run_role="submission", competition=args.competition,
        output_root=output_root, score=False, scoring_profile=args.scoring_profile,
        verbose=not args.quiet,
        max_repair_attempts=args.max_repair_attempts or _env_int("FPT26_MAX_REPAIR_ATTEMPTS", 3),
        max_optimization_rounds=args.max_optimization_rounds or _env_int("FPT26_MAX_OPTIMIZATION_CANDIDATES", 5),
        max_structural_attempts=args.max_structural_attempts or _env_int("FPT26_MAX_STRUCTURAL_REPAIR_ATTEMPTS", 3),
    )
    final_state = run_submission(task=task, config=config, server=server, llm=llm,
                                 run_root=Path(output_root) / task.id / "agent",
                                 total_budget=total_budget,
                                 preflight_metadata=preflight.to_dict())
    final_state.metadata["task_preflight"] = preflight.to_dict()
    final_state.metadata["official_budget"] = task.budget
    final_state.metadata["model_compliance"] = model_compliance_evidence(
        getattr(llm, "model", None) if llm else None,
        explicit_open_source=os.environ.get("FPT26_LLM_OPEN_SOURCE", "").strip().lower() in {"1", "true", "yes"},
        license_evidence=os.environ.get("FPT26_LLM_LICENSE") or os.environ.get("FPT26_LLM_LICENSE_EVIDENCE"),
        source_evidence=os.environ.get("FPT26_LLM_SOURCE"),
    )

    # Report + evidence
    report_path = write_run_report(final_state)
    ev = SubmissionEvidence.from_run_state(final_state, run_id=f"{task.id}_{final_state.status}")
    ep = Path(output_root) / task.id / "submission_evidence.json"
    ep.parent.mkdir(parents=True, exist_ok=True)
    ep.write_text(_json.dumps(ev.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print_evaluation(final_state)
    artifact("Final kernel", Path(output_root) / task.id / f"final_{task.kernel_name}")
    artifact("Run report", report_path)
    artifact("Evidence", ep)
    print()
    return _exit_code(final_state.status)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_console(args.color)

    # 1. Resolve task and output role ----------------------------------------
    task_dir = args.task.resolve()
    if not task_dir.is_dir():
        error(f"task directory not found: {task_dir}")
        return 2
    output_root = str(args.output_root or os.environ.get("FPT26_RUN_OUTPUT_ROOT", "runs"))

    if args.run_role == "evaluator":
        return _run_evaluator(args, task_dir, output_root)
    return _run_submission(args, task_dir, output_root)


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
