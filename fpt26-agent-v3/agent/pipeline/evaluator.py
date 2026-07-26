"""Evaluator pipeline orchestration — real implementation.

Migrated from agent.evaluator.  Enforces fail-closed: missing/damaged
evidence, invalid anchors, or failed submission status prevent scoring.
"""

from __future__ import annotations

from pathlib import Path

from agent.integrations.harness import Budget
from agent.integrations.task_repository import EvaluatorTaskRepository

from agent.agents.base import AgentConfig, RunState
from agent.errors import EvidenceError, MissingEvidenceError, DigestMismatchError
from agent.models import (
    AnchorEvidence,
    ArtifactManifest,
    EvaluationAccounting,
    RunStatus,
    SubmissionEvidence,
)
from agent.runner import ToolServer
from agent.task_io import load_public_task
from agent.testbench import normalize_task_testbench_data
from agent.validation import CandidateValidator
from agent.pipeline.stages import step_finalize
from agent.candidate.validator import validate_candidate


def _hidden_source(task_dir: Path) -> tuple[bool, str]:
    return EvaluatorTaskRepository().hidden_source(task_dir)


def _candidate_validity_only_ok(state: RunState, anchor_evidence: AnchorEvidence) -> bool:
    """Accept correctness-only evaluator results when QoR anchors are unusable.

    Some imported benchmark tasks have invalid starter/reference anchors or
    missing top-level latency metrics even though the submitted candidate passes
    hidden/public CSim, synthesis, interface, frequency, and resource gates.
    That evidence is enough to accept correctness/synth validity, but not
    enough to publish an anchored QoR score.
    """

    if anchor_evidence.passes_all_required_gates:
        return False
    if not all(
        bool(value)
        for value in (
            getattr(state, "csim_ok", False),
            getattr(state, "synth_ok", False),
            getattr(state, "interface_ok", False),
            getattr(state, "frequency_ok", False),
            getattr(state, "resource_ok", False),
        )
    ):
        return False
    if getattr(state.task, "requires_cosim", False) and not bool(
        getattr(state, "cosim_ok", False)
    ):
        return False
    scorecard = getattr(state, "scorecard", None)
    gate_reason = getattr(scorecard, "gate_reason", "") if scorecard else ""
    stop_reason = getattr(state, "stop_reason", "") or ""
    return (
        stop_reason.startswith("anchor_invalid")
        or gate_reason in {"no_valid_anchor", "required_metric_missing"}
        or anchor_evidence.source in {"none", "candidate_self"}
    )


def run_evaluator(
    *,
    task_dir: Path,
    kernel_path: Path,
    output_root: str,
    scoring_profile: str,
    verbose: bool,
    submission_evidence: SubmissionEvidence,
) -> RunState:
    """Run evaluator-owned grading — **requires** valid SubmissionEvidence.

    Args:
        task_dir: Path to the official task directory.
        kernel_path: Path to the final kernel artifact to grade.
        output_root: Output root for grading artifacts.
        scoring_profile: Scoring profile name.
        verbose: Enable step-level logging.
        submission_evidence: **Required** submission evidence.  The evaluator
            validates kernel digest, checks submission status, and carries
            forward credit accounting.

    Returns:
        Terminal RunState with scorecard populated (or failure status).

    Raises:
        EvidenceError: evidence is missing, damaged, or has mismatched digest.
    """
    task_dir = task_dir.resolve()
    kernel_path = kernel_path.resolve()
    if not kernel_path.is_file():
        raise ValueError(f"final kernel not found: {kernel_path}")

    # ── 0. Validate submission evidence (fail-closed, required) ──────────
    submission_evidence.validate_against_kernel(str(kernel_path))
    submission_evidence.require_completed()
    sub_spent = submission_evidence.credits_spent
    sub_wall = submission_evidence.tool_wall_seconds

    repo = EvaluatorTaskRepository()
    task = repo.load(task_dir)
    _, preflight = load_public_task(task_dir)
    hidden_available, source = _hidden_source(task_dir)
    task.hidden_available = hidden_available
    task.grading_source = source
    normalize_task_testbench_data(task, include_hidden=True)

    budget = Budget(total=task.budget)
    server = ToolServer(
        task,
        budget,
        Path(output_root) / task.id / "evaluator_tools",
    )
    config = AgentConfig(
        mode="baseline",
        run_role="evaluator",
        output_root=output_root,
        score=True,
        scoring_profile=scoring_profile,
        verbose=verbose,
    )
    kernel = kernel_path.read_text(encoding="utf-8")
    state = RunState(
        task=task,
        server=server,
        llm=None,
        config=config,
        kernel=kernel,
        safe_fallback_kernel=kernel,
    )
    state.metadata["task_preflight"] = preflight.to_dict()
    state.metadata["run_role"] = "evaluator"
    state.metadata["hidden_available"] = hidden_available
    state.metadata["grading_source"] = source
    state.metadata["evaluator_input_kernel"] = str(kernel_path)
    state.metadata["_candidate_validator"] = CandidateValidator.from_task(task)

    # Record submission evidence for audit trail
    state.metadata["submission_evidence"] = submission_evidence.to_dict()
    state.metadata["submission_evidence_valid"] = True
    state.metadata["submission_credits_spent"] = sub_spent
    state.metadata["submission_wall_seconds"] = sub_wall

    # ── Fail-closed: interface gate ────────────────────────────────────
    if not validate_candidate(state, state.kernel, stage="evaluator_input"):
        state.status = RunStatus.FAILED.value
        state.stop_reason = "interface_failed"
        state.metadata["evaluator_acceptance"] = {
            "ok": False, "failures": ["interface_failed"],
            "grading_source": source, "hidden_available": hidden_available,
        }
        return step_finalize(state)

    # ── Build accounting ───────────────────────────────────────────────
    # Evaluator credits start at 0 on a fresh Budget; we track them
    # separately from submission credits.
    import time as _time
    _eval_start = _time.monotonic()

    from scoring.evaluator import evaluate_and_score as step_score

    state = step_score(state, accounting=None)  # will be updated below

    _eval_wall = round(_time.monotonic() - _eval_start, 3)
    _eval_spent = getattr(budget, "spent", 0) if hasattr(budget, 'spent') else 0

    accounting = EvaluationAccounting(
        submission_credits=sub_spent,
        evaluator_credits=_eval_spent,
        submission_wall_seconds=sub_wall,
        evaluator_wall_seconds=_eval_wall,
    )
    state.metadata["evaluation_accounting"] = accounting.to_dict()

    # Re-score with proper accounting if the first pass used the compat path
    if state.scorecard is not None:
        # Update scorecard cost/time fields from accounting
        state.scorecard.cost_spent = accounting.total_credits
        state.scorecard.wall_time_s = accounting.total_wall_seconds

    # ── Read anchor evidence from scoring step ─────────────────────────
    anchor_data = state.metadata.get("anchor_evidence")
    if isinstance(anchor_data, dict):
        anchor_evidence = AnchorEvidence.from_dict(anchor_data)
    else:
        anchor_evidence = AnchorEvidence(source="none", valid=False)

    # ── Validity-only fallback: correct candidate, unusable QoR anchor ───
    if _candidate_validity_only_ok(state, anchor_evidence):
        state.status = RunStatus.COMPLETED.value
        state.stop_reason = ""
        state.scorecard = None
        state.last_verified_kernel = state.kernel
        state.metadata["evaluator_acceptance"] = {
            "ok": True,
            "failures": [],
            "grading_source": source,
            "hidden_available": hidden_available,
            "anchor_source": anchor_evidence.source,
            "anchor_valid": False,
            "validity_only": True,
            "score_available": False,
            "reason": (
                "candidate passed evaluator correctness/synthesis gates, "
                "but no valid QoR anchor was available"
            ),
        }
        return step_finalize(state)

    # ── Fail-closed: no valid anchor → no score ─────────────────────────
    if not anchor_evidence.passes_all_required_gates:
        state.status = RunStatus.FAILED.value
        state.stop_reason = (
            anchor_evidence.failure_reason
            or f"anchor_invalid: {anchor_evidence.source}"
        )
        state.scorecard = None
        state.metadata["evaluator_acceptance"] = {
            "ok": False,
            "failures": [state.stop_reason],
            "grading_source": source,
            "hidden_available": hidden_available,
            "anchor_source": anchor_evidence.source,
            "anchor_valid": False,
        }
        return step_finalize(state)

    if state.status == RunStatus.FAILED.value:
        state.metadata["evaluator_acceptance"] = {
            "ok": False,
            "failures": [state.stop_reason],
            "grading_source": source,
            "hidden_available": hidden_available,
            "anchor_source": anchor_evidence.source,
            "anchor_valid": anchor_evidence.valid,
        }
        return step_finalize(state)

    if state.scorecard is not None:
        state.csim_ok = bool(state.scorecard.csim_pass)
        state.cosim_ok = (
            bool(state.scorecard.cosim_pass)
            if task.requires_cosim
            else True
        )

    # ── Fail-closed: scorecard invalid → refuse to publish ──────────────
    failures: list[str] = []
    if state.scorecard is None or not state.scorecard.valid:
        failures.append(
            getattr(state.scorecard, "gate_reason", "evaluation_failed")
        )
    if not state.interface_ok:
        failures.append("interface_failed")
    if not state.frequency_ok:
        failures.append(
            (state.metadata.get("frequency_gate") or {}).get(
                "reason", "frequency_failed"
            )
        )
    if not state.resource_ok:
        failures.append(
            (state.metadata.get("resource_gate") or {}).get(
                "reason", "resource_failed"
            )
        )

    if failures:
        state.status = RunStatus.FAILED.value
        state.stop_reason = str(failures[0])
    else:
        state.status = RunStatus.COMPLETED.value
        state.last_verified_kernel = state.kernel
    state.metadata["evaluator_acceptance"] = {
        "ok": not failures,
        "failures": failures,
        "grading_source": source,
        "hidden_available": hidden_available,
        "anchor_source": anchor_evidence.source,
        "anchor_valid": anchor_evidence.valid,
    }
    return step_finalize(state)


def run_evaluator_legacy(
    *, task_dir, kernel_path, output_root, scoring_profile, verbose,
) -> RunState:
    """Legacy evaluator entry — does NOT require SubmissionEvidence.

    Use only for compatibility with old callers.  Results are marked
    as non-formal in the report.
    """
    ev = SubmissionEvidence(
        status="completed",
        kernel_sha256="",  # Will be validated leniently
    )
    # Bypass evidence validation
    task_dir = task_dir.resolve()
    kernel_path = kernel_path.resolve()
    if not kernel_path.is_file():
        raise ValueError(f"final kernel not found: {kernel_path}")

    repo = EvaluatorTaskRepository()
    task = repo.load(task_dir)
    _, preflight = load_public_task(task_dir)
    hidden_available, source = _hidden_source(task_dir)
    task.hidden_available = hidden_available
    task.grading_source = source
    normalize_task_testbench_data(task, include_hidden=True)

    budget = Budget(total=task.budget)
    server = ToolServer(task, budget, Path(output_root) / task.id / "evaluator_tools")
    config = AgentConfig(mode="baseline", run_role="evaluator", output_root=output_root,
                         score=True, scoring_profile=scoring_profile, verbose=verbose)
    kernel = kernel_path.read_text(encoding="utf-8")
    state = RunState(task=task, server=server, llm=None, config=config,
                     kernel=kernel, safe_fallback_kernel=kernel)
    state.metadata["task_preflight"] = preflight.to_dict()
    state.metadata["run_role"] = "evaluator"
    state.metadata["hidden_available"] = hidden_available
    state.metadata["grading_source"] = source
    state.metadata["evaluator_input_kernel"] = str(kernel_path)
    state.metadata["_candidate_validator"] = CandidateValidator.from_task(task)
    state.metadata["submission_evidence_valid"] = False
    state.metadata["grading_legacy_mode"] = True

    if not validate_candidate(state, state.kernel, stage="evaluator_input"):
        state.status = RunStatus.FAILED.value
        state.stop_reason = "interface_failed"
        return step_finalize(state)

    from scoring.evaluator import evaluate_and_score as step_score

    state = step_score(state)  # no accounting in legacy mode

    anchor_data = state.metadata.get("anchor_evidence")
    if isinstance(anchor_data, dict):
        anchor_evidence = AnchorEvidence.from_dict(anchor_data)
    else:
        anchor_evidence = AnchorEvidence(source="none", valid=False)

    if not anchor_evidence.passes_all_required_gates:
        state.status = RunStatus.FAILED.value
        state.scorecard = None
        state.metadata["evaluator_acceptance"] = {
            "ok": False, "failures": [state.stop_reason or "anchor_invalid"],
            "grading_source": source, "hidden_available": hidden_available,
        }
        return step_finalize(state)

    if state.scorecard is not None:
        state.csim_ok = bool(state.scorecard.csim_pass)
        state.cosim_ok = bool(state.scorecard.cosim_pass) if task.requires_cosim else True

    failures = []
    if state.scorecard is None or not state.scorecard.valid:
        failures.append(getattr(state.scorecard, "gate_reason", "evaluation_failed"))
    if not state.interface_ok:
        failures.append("interface_failed")
    if not state.frequency_ok:
        failures.append("frequency_failed")
    if not state.resource_ok:
        failures.append("resource_failed")

    if failures:
        state.status = RunStatus.FAILED.value
        state.stop_reason = str(failures[0])
    else:
        state.status = RunStatus.COMPLETED.value
        state.last_verified_kernel = state.kernel
    state.metadata["evaluator_acceptance"] = {
        "ok": not failures, "failures": failures,
        "grading_source": source, "hidden_available": hidden_available,
        "anchor_source": anchor_evidence.source, "anchor_valid": anchor_evidence.valid,
        "legacy_mode": True,
    }
    return step_finalize(state)
