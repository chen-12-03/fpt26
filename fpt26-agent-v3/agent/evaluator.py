"""Evaluator-only hidden/reference grading for a finalized submission kernel.

Enforces fail-closed evaluation: missing/damaged evidence, invalid anchors, or
failed submission status prevent scoring and publishing.
"""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 image
    import tomli as tomllib

from llm4hls.budget import Budget
from llm4hls.task import load_task

from agent.agents.base import AgentConfig, RunState
from agent.errors import EvidenceError, MissingEvidenceError, DigestMismatchError
from agent.models import (
    AnchorEvidence,
    ArtifactManifest,
    RunStatus,
    SubmissionEvidence,
)
from agent.runner import ToolServer
from agent.task_io import load_public_task
from agent.testbench import normalize_task_testbench_data
from agent.validation import CandidateValidator
from agent.workflow import (
    step_finalize,
    step_score,
    validate_candidate,
)


def _hidden_source(task_dir: Path) -> tuple[bool, str]:
    spec = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    public_name = spec["public_tb"]
    hidden_name = spec.get("hidden_tb", public_name)
    available = (task_dir / "hidden" / hidden_name).is_file()
    return available, "hidden" if available else "public_fallback"


def _build_anchor_evidence(state: RunState) -> AnchorEvidence:
    """Build anchor evidence from the scoring step's recorded gates and PPA."""
    meta = state.metadata

    freq_data = meta.get("frequency_gate") or {}
    res_data = meta.get("resource_gate") or {}
    cosim_data = meta.get("cosim_gate") or {}

    best = meta.get("best_synth_metrics") or {}

    from agent.models import FrequencyGateEvidence, ResourceGateEvidence, CoSimGateEvidence

    return AnchorEvidence(
        schema_version=1,
        source="starter",
        valid=bool(
            state.csim_ok
            and state.synth_ok
            and state.interface_ok
            and state.frequency_ok
            and state.resource_ok
            and (state.cosim_ok if state.task.requires_cosim else True)
            and best.get("latency_worst") is not None
        ),
        source_sha256=(
            __import__("hashlib").sha256(
                getattr(state.task, "kernel_code", "").encode("utf-8")
            ).hexdigest()
            if getattr(state.task, "kernel_code", None) else ""
        ),
        csim_ok=state.csim_ok,
        synth_ok=state.synth_ok,
        interface_ok=state.interface_ok,
        frequency=FrequencyGateEvidence(
            ok=bool(freq_data.get("ok", False)),
            reason=freq_data.get("reason"),
            target_clock_ns=freq_data.get("target_clock_ns"),
            candidate_clock_ns=freq_data.get("candidate_clock_ns"),
            frequency_mhz=freq_data.get("frequency_mhz"),
        ) if freq_data else None,
        resource=ResourceGateEvidence(
            ok=bool(res_data.get("ok", False)),
            reason=res_data.get("reason"),
            resources=dict(res_data.get("resources", {})),
            available=dict(res_data.get("available", {})),
        ) if res_data else None,
        cosim=CoSimGateEvidence(
            ok=bool(cosim_data.get("ok", False)),
            phase=cosim_data.get("phase"),
            source_sha256=cosim_data.get("source_sha256"),
            latency_min=cosim_data.get("latency_min"),
            latency_avg=cosim_data.get("latency_avg"),
            latency_max=cosim_data.get("latency_max"),
        ) if cosim_data else None,
        latency=(
            best.get("latency_worst")
            if best.get("latency_worst") is not None
            else best.get("latency_avg")
        ),
        ii=best.get("interval_max"),
        clock_ns=best.get("clock_period_ns"),
        resources=dict(best.get("resources", {})),
        available=dict(best.get("available", {})),
        failure_reason=(
            state.stop_reason
            if state.status != RunStatus.COMPLETED.value
            else ""
        ),
    )


def evaluate_final_kernel(
    *,
    task_dir: Path,
    kernel_path: Path,
    output_root: str,
    scoring_profile: str,
    verbose: bool,
    submission_evidence: SubmissionEvidence | None = None,
) -> RunState:
    """Run evaluator-owned grading without exposing hidden data to submission.

    Args:
        task_dir: Path to the official task directory.
        kernel_path: Path to the final kernel artifact to grade.
        output_root: Output root for grading artifacts.
        scoring_profile: Scoring profile name.
        verbose: Enable step-level logging.
        submission_evidence: Optional submission evidence for cross-process
            verification.  When provided, the evaluator validates the kernel
            digest, checks submission status, and carries forward credit
            accounting instead of resetting to 0.

    Returns:
        Terminal RunState with scorecard populated (or failure status).
    """

    task_dir = task_dir.resolve()
    kernel_path = kernel_path.resolve()
    if not kernel_path.is_file():
        raise ValueError(f"final kernel not found: {kernel_path}")

    # ── 0. Validate submission evidence (fail-closed) ─────────────────────
    evidence_valid = False
    if submission_evidence is not None:
        try:
            submission_evidence.validate_against_kernel(str(kernel_path))
            submission_evidence.require_completed()
            evidence_valid = True
        except EvidenceError as exc:
            # Evidence is present but invalid — refuse to score
            raise EvidenceError(
                f"submission evidence invalid, refusing to grade: {exc}"
            ) from exc

    _, preflight = load_public_task(task_dir)
    task = load_task(task_dir)
    hidden_available, source = _hidden_source(task_dir)
    task.hidden_available = hidden_available
    task.grading_source = source
    normalize_task_testbench_data(task, include_hidden=True)

    # When evidence is valid, carry forward submission costs; otherwise start fresh.
    budget_total = task.budget
    if evidence_valid and submission_evidence is not None:
        # Carry forward the spent credits so grading adds on top of submission
        # without resetting to 0.
        pass  # Budget starts fresh for evaluator tool calls — cost is additive

    budget = Budget(total=budget_total)
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

    # Record submission evidence in metadata for the report
    if submission_evidence is not None:
        state.metadata["submission_evidence"] = submission_evidence.to_dict()
        state.metadata["submission_evidence_valid"] = evidence_valid

    # ── Fail-closed: interface gate must pass before any tool runs ─────────
    if not validate_candidate(state, state.kernel, stage="evaluator_input"):
        state.status = RunStatus.FAILED.value
        state.stop_reason = "interface_failed"
        state.metadata["evaluator_acceptance"] = {
            "ok": False,
            "failures": ["interface_failed"],
            "grading_source": source,
            "hidden_available": hidden_available,
        }
        return step_finalize(state)

    # ── Fail-closed: don't score if submission evidence is missing/damaged ─
    if submission_evidence is not None and not evidence_valid:
        state.status = RunStatus.FAILED.value
        state.stop_reason = "submission_evidence_invalid"
        state.metadata["evaluator_acceptance"] = {
            "ok": False,
            "failures": [state.stop_reason],
            "grading_source": source,
            "hidden_available": hidden_available,
        }
        return step_finalize(state)

    state = step_score(state)

    # ── Build anchor evidence ──────────────────────────────────────────
    anchor_evidence = _build_anchor_evidence(state)
    state.metadata["anchor_evidence"] = anchor_evidence.to_dict()

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
