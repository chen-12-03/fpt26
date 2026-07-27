"""Scoring orchestration — hidden CSim, synth comparisons, CoSim, grading.

Extracted from ``agent.workflow.step_score``.  This is the single authority
for the evaluator scoring pipeline.

Key fixes vs. prior version:
- Starter and reference each receive **independent** gate evaluation via
  ``_evaluate_anchor_source()``.  No candidate gate results leak into the
  anchor qualification.
- ``EvaluationAccounting`` is passed directly to ``grade_with_profile()``
  so scoring uses total (submission + evaluator) credits and wall time.
- ``AnchorEvidence`` is constructed exactly once, inside this module, and
  the same evidence flows through to the Scorecard.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from agent.runner import CSimTool, SynthTool, CoSimTool
from agent.candidate.validator import record_synth_gates, record_cosim_gate
from agent.models import (
    AnchorEvidence,
    CandidateEvaluation,
    CoSimGateEvidence,
    EvaluationAccounting,
    FrequencyGateEvidence,
    InterfaceGateEvidence,
    ResourceGateEvidence,
)
from agent.validation import frequency_gate as _freq_gate_fn
from agent.validation import resource_gate as _res_gate_fn
from scoring.scoring_v3 import (
    Anchor,
    QoREvidence,
    TaskScoringConfig,
    ValidityGates,
    verified_available_resources,
)
from scoring.profiles import grade_with_profile


# ═══════════════════════════════════════════════════════════════════════════════
# Independent anchor-source evaluation
# ═══════════════════════════════════════════════════════════════════════════════


def _evaluate_anchor_source(
    *,
    source_code: str,
    source_label: str,  # "starter" | "reference"
    task: Any,
    grade_root: Path,
    requires_cosim: bool,
) -> CandidateEvaluation:
    """Run every required gate for *source_code* independently.

    This function owns its own CSim, Synth, frequency, resource, and
    (when required) CoSim runs.  It never reads candidate gate state.
    """
    source_sha = hashlib.sha256(source_code.encode("utf-8")).hexdigest()
    ev = CandidateEvaluation(source_sha256=source_sha, stage=source_label)

    # ── Interface gate ──────────────────────────────────────────────────
    from agent.candidate.validator import InterfaceValidator
    try:
        iface_validator = InterfaceValidator.from_source(task.top, source_code)
    except ValueError:
        ev.interface = InterfaceGateEvidence(ok=False, reason="contract_build_failed")
        ev.fail("contract_build_failed")
        return ev
    result = iface_validator.validate(source_code)
    ev.interface = InterfaceGateEvidence(
        ok=result.ok, reason=result.reason,
        fingerprint=result.fingerprint,
        canonical_signature=result.canonical_signature,
        language_linkage=result.language_linkage,
        required_includes_present=result.required_includes_present,
    )
    if not result.ok:
        ev.fail(result.reason or "interface")
        return ev

    # ── CSim gate ───────────────────────────────────────────────────────
    source_files = task.assemble(source_code, task.hidden_tb_code, task.hidden_tb_name)
    data_files = getattr(task, "hidden_data_files", None) or None
    csim_result = CSimTool().run(
        grade_root / f"grade_csim_{source_label}", source_files,
        top=task.top, part=task.part, clock_ns=task.clock_ns,
        data_files=data_files,
    )
    csim_ok = bool(getattr(csim_result, "ok", False))
    ev.csim = "pass" if csim_ok else "fail"
    if not csim_ok:
        ev.fail("csim")
        return ev

    # ── Synth gate ──────────────────────────────────────────────────────
    synth_files = dict(getattr(task, "headers", {}))
    synth_files[task.kernel_name] = source_code
    synth_result = SynthTool().run(
        grade_root / f"grade_synth_{source_label}", synth_files,
        synth_sources=[task.kernel_name],
        top=task.top, part=task.part, clock_ns=task.clock_ns,
    )
    synth_ok = bool(getattr(synth_result, "ok", False))
    report = getattr(synth_result, "report", None) if synth_ok else None
    ev.synth = "pass" if (synth_ok and report is not None) else "fail"
    if report is None:
        ev.fail("synth")
        return ev

    # ── Frequency gate ──────────────────────────────────────────────────
    freq = _freq_gate_fn(report, task.clock_ns)
    ev.frequency = FrequencyGateEvidence(
        ok=freq.ok, reason=freq.reason,
        target_clock_ns=freq.target_clock_ns,
        candidate_clock_ns=freq.candidate_clock_ns,
        frequency_mhz=freq.frequency_mhz,
    )
    if not freq.ok:
        ev.fail(freq.reason or "frequency")
        return ev

    # ── Resource gate ───────────────────────────────────────────────────
    res = _res_gate_fn(report)
    ev.resource = ResourceGateEvidence(
        ok=res.ok, reason=res.reason,
        resources=dict(res.resources), available=dict(res.available),
    )
    # resource_capacity_missing is a metric-completeness issue, not a
    # source invalidity — the scoring kernel handles it via the
    # metric_completeness_pass gate.  resource_capacity_exceeded IS a
    # source invalidity.
    if not res.ok and res.reason != "resource_capacity_missing":
        ev.fail(res.reason or "resource")
        return ev

    # ── PPA from synthesis ──────────────────────────────────────────────
    ev.synth_latency = (
        report.latency_worst
        if getattr(report, "latency_worst", None) is not None
        else getattr(report, "latency_avg", None)
    )
    ev.synth_ii = getattr(report, "interval_max", None)
    ev.synth_clock_ns = getattr(report, "clock_period_ns", None)
    ev.synth_resources = dict(getattr(report, "resources", {}) or {})

    # ── CoSim gate (only when required) ─────────────────────────────────
    if requires_cosim:
        cosim_result = CoSimTool().run(
            grade_root / f"grade_cosim_{source_label}", source_files,
            synth_sources=[task.kernel_name],
            tb_sources=[task.hidden_tb_name],
            top=task.top, part=task.part, clock_ns=task.clock_ns,
        )
        payload = getattr(cosim_result, "cosim", None)
        cosim_ok = bool(
            getattr(cosim_result, "ok", False)
            and payload is not None
            and getattr(payload, "passed", False)
        )
        ev.cosim = CoSimGateEvidence(
            ok=cosim_ok,
            source_sha256=source_sha,
            latency_max=getattr(payload, "latency_max", None) if payload else None,
        )
        if not cosim_ok:
            ev.fail("cosim")
            return ev

    ev.accepted = True
    return ev


# ═══════════════════════════════════════════════════════════════════════════════
# Main scoring step
# ═══════════════════════════════════════════════════════════════════════════════


def evaluate_and_score(state: Any, *, accounting: EvaluationAccounting | None = None) -> Any:
    """Run profiled scoring: hidden-csim → synth(cand) → synth(starter) → synth(ref) → optional cosim → grade.

    Mutates *state* in place (scorecard, ref_scorecard, gates) and returns it.

    Args:
        state: RunState with task, kernel, config.
        accounting: Required for formal evaluation.  If absent, falls back
            to ``state.server.budget.spent`` for backward compat only.
    """
    if not state.config.score:
        return state

    task = state.task
    kernel = state.kernel
    if not isinstance(getattr(state, "metadata", None), dict):
        state.metadata = {}
    grade_root = Path(state.config.output_root) / task.id / "grade"
    _start = time.monotonic()

    grading_results: list[tuple[str, Any]] = []

    def _record(stage: str, result: Any) -> None:
        grading_results.append((stage, result))
        state.metadata["grading_results"] = list(grading_results)
        state.metadata["grading_source"] = getattr(task, "grading_source", "hidden")
        state.metadata["hidden_available"] = bool(getattr(task, "hidden_available", True))

    def _gate_failure(reason: str) -> Any:
        state.status = "failed"
        state.stop_reason = reason
        state.scorecard = None
        state.ref_scorecard = None
        state.log(f"evaluator gate failed before scoring: {reason}")
        return state

    # ── 1. Hidden CSim (candidate validity gate) ──────────────────────────
    hidden_files = task.assemble(kernel, task.hidden_tb_code, task.hidden_tb_name)
    data_files = getattr(task, "hidden_data_files", None) or None
    csim = CSimTool().run(
        grade_root / "grade_csim", hidden_files,
        top=task.top, part=task.part, clock_ns=task.clock_ns,
        data_files=data_files,
    )
    _record("hidden_csim", csim)
    state.csim_ok = csim.ok
    if not csim.ok:
        return _gate_failure("hidden_csim_failed")

    # ── 2. Candidate synthesis ────────────────────────────────────────────
    cand_files = dict(task.headers)
    cand_files[task.kernel_name] = kernel
    cand_synth = SynthTool().run(
        grade_root / "grade_synth_cand", cand_files,
        synth_sources=[task.kernel_name],
        top=task.top, part=task.part, clock_ns=task.clock_ns,
    )
    _record("candidate_synth", cand_synth)
    state.synth_ok = cand_synth.ok
    if not cand_synth.ok or cand_synth.report is None:
        return _gate_failure("candidate_synth_failed")
    if not record_synth_gates(state, cand_synth, stage="evaluator_candidate_synth"):
        reason = (
            (state.metadata.get("frequency_gate") or {}).get("reason")
            if not state.frequency_ok
            else (state.metadata.get("resource_gate") or {}).get("reason")
        )
        return _gate_failure(str(reason or "candidate_target_gate_failed"))

    # ── 3. CoSim (candidate, if required) ─────────────────────────────────
    cosim = None
    cosim_ok: bool | None = None
    cosim_latency: int | None = None
    if task.requires_cosim:
        cosim = CoSimTool().run(
            grade_root / "grade_cosim", hidden_files,
            synth_sources=[task.kernel_name],
            tb_sources=[task.hidden_tb_name],
            top=task.top, part=task.part, clock_ns=task.clock_ns,
        )
        _record("hidden_cosim", cosim)
        cosim_ok = record_cosim_gate(state, cosim, stage="evaluator_hidden_cosim", source_code=kernel)
        cosim_report = getattr(cosim, "cosim", None)
        if not cosim_ok:
            return _gate_failure("required_cosim_failed")
        cosim_latency = cosim_report.latency_max
        if cosim_latency is None:
            return _gate_failure("required_cosim_report_missing")
    else:
        state.cosim_ok = True

    # ── 4. Independent anchor evaluation ──────────────────────────────────
    # Each anchor source runs its OWN CSim, Synth, frequency, resource, and
    # CoSim.  No candidate gate state leaks in.

    starter_eval = _evaluate_anchor_source(
        source_code=task.kernel_code,
        source_label="starter",
        task=task,
        grade_root=grade_root,
        requires_cosim=task.requires_cosim,
    )
    _record("starter_anchor_eval", starter_eval)

    ref_eval = None
    if task.reference_code:
        ref_eval = _evaluate_anchor_source(
            source_code=task.reference_code,
            source_label="reference",
            task=task,
            grade_root=grade_root,
            requires_cosim=task.requires_cosim,
        )
        _record("reference_anchor_eval", ref_eval)

    # ── 5. Build scoring data structures ──────────────────────────────────
    cfg = TaskScoringConfig(
        task_id=task.id, task_type=task.type, difficulty=task.difficulty,
        requires_cosim=task.requires_cosim, budget_limit=task.budget,
        task_clock_ns=task.clock_ns,
    )

    # Candidate evidence
    cand_lat = (
        cand_synth.report.latency_worst or cand_synth.report.latency_avg
        if cand_synth.ok and cand_synth.report else None
    )
    cand_ii = cand_synth.report.interval_max if cand_synth.ok and cand_synth.report else None
    cand_clock = (
        cand_synth.report.clock_period_ns
        if cand_synth.ok and cand_synth.report else task.clock_ns
    )
    cand_resources = cand_synth.report.resources if cand_synth.ok and cand_synth.report else {}

    candidate_freq = _freq_gate_fn(cand_synth.report, task.clock_ns)
    candidate_res = _res_gate_fn(cand_synth.report)
    candidate_eval = CandidateEvaluation(
        source_sha256=hashlib.sha256(kernel.encode("utf-8")).hexdigest(),
        interface=InterfaceGateEvidence(
            ok=bool(getattr(state, "interface_ok", False)),
            reason=(
                (state.metadata.get("interface_contract") or {}).get("reason")
                if isinstance(state.metadata.get("interface_contract"), dict)
                else None
            ),
        ),
        csim="pass" if csim.ok else "fail",
        synth="pass" if cand_synth.ok else "fail",
        frequency=FrequencyGateEvidence(
            ok=candidate_freq.ok,
            reason=candidate_freq.reason,
            target_clock_ns=candidate_freq.target_clock_ns,
            candidate_clock_ns=candidate_freq.candidate_clock_ns,
            frequency_mhz=candidate_freq.frequency_mhz,
        ),
        resource=ResourceGateEvidence(
            ok=candidate_res.ok,
            reason=candidate_res.reason,
            resources=dict(candidate_res.resources),
            available=dict(candidate_res.available),
        ),
        cosim=(
            CoSimGateEvidence(ok=True, latency_max=cosim_latency)
            if task.requires_cosim and cosim_ok
            else None
        ),
        stage="candidate_self_anchor",
        accepted=(
            bool(getattr(state, "interface_ok", False))
            and bool(csim.ok)
            and bool(cand_synth.ok)
            and bool(candidate_freq.ok)
            and bool(candidate_res.ok)
            and (not task.requires_cosim or bool(cosim_ok))
            and cand_lat is not None
            and cand_ii is not None
        ),
        synth_latency=cand_lat,
        synth_ii=cand_ii,
        synth_clock_ns=cand_clock,
        synth_resources=dict(cand_resources),
    )

    # ── 6. Anchor selection (once) ────────────────────────────────────────
    from agent.candidate.selector import select_anchor

    anchor_evidence = select_anchor(
        starter_eval,
        ref_eval,
        requires_cosim=task.requires_cosim,
        candidate_eval=candidate_eval,
        allow_candidate_self_anchor=True,
    )

    # Convert AnchorEvidence → scoring Anchor.
    anchor = Anchor(
        source=anchor_evidence.source,
        valid=anchor_evidence.valid,
        latency=anchor_evidence.latency,
        ii=anchor_evidence.ii,
        clock_ns=anchor_evidence.clock_ns,
        resources=dict(anchor_evidence.resources),
        available=dict(anchor_evidence.available),
    )

    evidence = QoREvidence(
        candidate_latency=cand_lat, candidate_ii=cand_ii,
        candidate_clock_ns=cand_clock, cosim_latency=cosim_latency,
        candidate_resources=cand_resources,
    )
    gates = ValidityGates(
        hidden_csim_pass=csim.ok, hidden_cosim_pass=cosim_ok,
        synth_pass=cand_synth.ok, resource_capacity_pass=state.resource_ok,
    )

    # ── 7. Determine cost/time for efficiency ─────────────────────────────
    if accounting is not None:
        cost_spent = accounting.total_credits
        wall_time_s = accounting.total_wall_seconds
    else:
        # Backward compat: evaluator-only cost (deprecated path)
        budget_obj = state.server.budget
        cost_spent = budget_obj.spent if hasattr(budget_obj, 'spent') else 0
        wall_time_s = time.monotonic() - _start

    # ── 8. Grade ──────────────────────────────────────────────────────────
    # Always call grade_with_profile — it handles invalid anchors internally
    # and returns a Scorecard with valid=False and proper gate_reason.
    scorecard = grade_with_profile(
        task_cfg=cfg, anchor=anchor, evidence=evidence,
        scoring_profile=getattr(state.config, "scoring_profile", "balanced"),
        cost_spent=cost_spent, wall_time_s=wall_time_s, gates=gates,
        accounting=accounting,
    )
    state.scorecard = scorecard
    state.log(
        f"V{scorecard.schema_version} score: {scorecard.score:.2f}/100  "
        f"(valid={scorecard.valid}, q_hw={scorecard.q_hw:.4f}, "
        f"eff={scorecard.efficiency:.4f}, anchor={scorecard.anchor_source})"
    )

    # ── 9. Record anchor evidence (one authoritative copy) ────────────────
    state.metadata["anchor_evidence"] = anchor_evidence.to_dict()

    # Verify Scorecard ↔ AnchorEvidence consistency
    if scorecard.anchor_source != anchor_evidence.source:
        state.log(
            f"WARNING: Scorecard.anchor_source={scorecard.anchor_source} "
            f"!= AnchorEvidence.source={anchor_evidence.source}"
        )

    # If the anchor itself is invalid, the score must be zero (fail-closed).
    # The scoring kernel (``_grade``) may have already set a specific
    # gate_reason like "required_metric_missing" — preserve that.
    if not anchor_evidence.passes_all_required_gates:
        scorecard.valid = False
        # Only override gate_reason if the scoring kernel didn't detect
        # the issue (e.g. "passed" means the kernel saw valid gates).
        if scorecard.gate_reason in ("passed", "", None):
            scorecard.gate_reason = (
                anchor_evidence.failure_reason
                or f"anchor_invalid: {anchor_evidence.source}"
            )
        scorecard.score = 0.0

    # Fail-closed: invalid anchor → set terminal failure on state
    if not anchor_evidence.passes_all_required_gates and not scorecard.valid:
        state.status = "failed"
        if not state.stop_reason:
            state.stop_reason = (
                anchor_evidence.failure_reason
                or f"anchor_invalid: {anchor_evidence.source}"
            )

    # ── 10. Reference-anchored scorecard ──────────────────────────────────
    if ref_eval is not None and ref_eval.accepted:
        ref_anchor = Anchor(
            source="reference", valid=True,
            latency=ref_eval.synth_latency, ii=ref_eval.synth_ii,
            clock_ns=ref_eval.synth_clock_ns,
            resources=dict(ref_eval.synth_resources),
            available=dict(ref_eval.resource.available) if ref_eval.resource else {},
        )
        ref_scorecard = grade_with_profile(
            task_cfg=cfg, anchor=ref_anchor, evidence=evidence,
            scoring_profile=getattr(state.config, "scoring_profile", "balanced"),
            cost_spent=cost_spent, wall_time_s=wall_time_s, gates=gates,
            accounting=accounting,
        )
        state.ref_scorecard = ref_scorecard
        state.log(
            f"V{ref_scorecard.schema_version} score vs reference: "
            f"{ref_scorecard.score:.2f}/100 (valid={ref_scorecard.valid}, "
            f"q_hw={ref_scorecard.q_hw:.4f})"
        )

    return state
