"""FPT26 Track-A agent workflow — the single file to read for understanding the full pipeline.

Workflow overview::

    baseline_check ──┬── csim pass ──→ cosim? ──→ optimize ──→ score
                      │
                      └── csim fail ──→ repair loop ──→ ...
                                            │
                            LLM modifies code → csim simulation →
                            read result log → decide whether to call LLM again

Each step below is a pure function ``RunState -> RunState``.  Open
``build_pipeline()`` to see the step ordering and conditional logic at a glance.
"""

from __future__ import annotations

import hashlib
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from llm4hls.budget import BudgetExceeded
from llm4hls.harness import ToolServer
from llm4hls.task import Task
from llm4hls.tools import ToolResult

from agent.agents.base import AgentConfig, RunState
from agent.runner import CoSimTool, CSimTool, SynthTool
from agent.safety import redact_sensitive_text
from agent.validation import CandidateValidator, frequency_gate, resource_gate

# ---------------------------------------------------------------------------
# Pipeline framework
# ---------------------------------------------------------------------------


@dataclass
class Step:
    """A named step in the pipeline.

    Args:
        name: Short identifier shown in logs.
        fn: ``RunState -> RunState`` callable.
        condition: If set, the step is skipped when this returns False.
        desc: Human-readable one-liner for log output.
    """

    name: str
    fn: Callable[[RunState], RunState]
    condition: Callable[[RunState], bool] | None = None
    desc: str = ""


class Pipeline:
    """Ordered collection of Steps executed sequentially."""

    def __init__(self, steps: list[Step] | None = None, *, name: str = "workflow") -> None:
        self.steps: list[Step] = steps or []
        self.name = name

    def run(self, state: RunState) -> RunState:
        state.log(f"Pipeline '{self.name}' starting ({len(self.steps)} steps)")
        for step in self.steps:
            if step.condition is not None and not step.condition(state):
                state.log(f"  skip '{step.name}' (condition not met)")
                continue
            state.log(f"  step '{step.name}': {step.desc}")
            try:
                state = step.fn(state)
            except BudgetExceeded:
                state.status = "budget_exceeded"
                state.stop_reason = "budget_exceeded"
                state.log("  budget exceeded — stopping pipeline")
                break
            except Exception as exc:
                safe_message = redact_sensitive_text(exc)
                state.status = "infrastructure_error"
                state.stop_reason = f"{type(exc).__name__}: {safe_message}"
                state.metadata["infrastructure_error"] = {
                    "type": type(exc).__name__,
                    "message": safe_message,
                    "step": step.name,
                }
                state.log(
                    f"  infrastructure error in '{step.name}': {safe_message}"
                )
                break
            if state.status in (
                "failed",
                "budget_exceeded",
                "infrastructure_error",
            ):
                state.log(f"  pipeline stopping: status={state.status}")
                break
        state.log(f"Pipeline done, status={state.status}")
        return state


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

_CODE_RE = re.compile(r"```(?:cpp|c\+\+|c)?\s*\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str | None:
    """Extract kernel source from an LLM response (```cpp fenced block)."""
    blocks = _CODE_RE.findall(text)
    if blocks:
        return blocks[0].strip() + "\n"
    stripped = text.strip()
    return stripped + "\n" if stripped else None


def _latency(result: ToolResult) -> int | None:
    """Extract worst-case latency from a synthesis ToolResult."""
    if result.report is None:
        return None
    return (
        result.report.latency_worst
        if result.report.latency_worst is not None
        else result.report.latency_avg
    )


def _candidate_validator(state: RunState) -> CandidateValidator:
    if not isinstance(getattr(state, "metadata", None), dict):
        state.metadata = {}
    validator = state.metadata.get("_candidate_validator")
    if not isinstance(validator, CandidateValidator):
        starter_code = getattr(state.task, "kernel_code", None)
        if not isinstance(starter_code, str) or not starter_code.strip():
            # Compatibility for focused unit-test states. Real submission
            # tasks always carry the public starter in ``task.kernel_code``.
            starter_code = state.kernel
        validator = CandidateValidator.from_source(state.task.top, starter_code)
        state.metadata["_candidate_validator"] = validator
        state.metadata["interface_contract"] = validator.contract.to_dict()
    return validator


def validate_candidate(
    state: RunState,
    code: str,
    *,
    stage: str,
    current_best: bool = True,
) -> bool:
    """Run and record the deterministic public interface/source gate."""

    result = _candidate_validator(state).validate(code)
    record = {"stage": stage, **result.to_dict()}
    state.metadata.setdefault("interface_validations", []).append(record)
    if current_best:
        state.interface_ok = result.ok
        state.metadata["interface_gate"] = record
    if not result.ok:
        state.log(f"{stage}: interface gate FAIL ({result.reason})")
    return result.ok


def record_synth_gates(
    state: RunState,
    result: ToolResult,
    *,
    stage: str,
    current_best: bool = True,
) -> bool:
    """Record mandatory frequency and capacity evidence from one synthesis."""

    if not isinstance(getattr(state, "metadata", None), dict):
        state.metadata = {}
    freq = frequency_gate(result.report if result.ok else None, state.task.clock_ns)
    capacity = resource_gate(result.report if result.ok else None)
    state.metadata.setdefault("synth_gate_history", []).append(
        {
            "stage": stage,
            "frequency": freq.to_dict(),
            "resource": capacity.to_dict(),
        }
    )
    if current_best:
        state.frequency_ok = freq.ok
        state.resource_ok = capacity.ok
        state.metadata["frequency_gate"] = freq.to_dict()
        state.metadata["resource_gate"] = capacity.to_dict()
        if result.ok and result.report is not None:
            state.best_synth_result = result
            state.metadata["best_synth_metrics"] = {
                "stage": stage,
                "latency_worst": getattr(
                    result.report, "latency_worst", None
                ),
                "latency_avg": getattr(result.report, "latency_avg", None),
                "interval_max": getattr(
                    result.report, "interval_max", None
                ),
                "clock_period_ns": getattr(
                    result.report, "clock_period_ns", None
                ),
                "frequency_mhz": freq.frequency_mhz,
                "resources": dict(
                    getattr(result.report, "resources", None) or {}
                ),
                "available": dict(capacity.available),
                "pipeline_type": getattr(
                    result.report, "pipeline_type", None
                ),
                "loop_metrics": [
                    dict(item)
                    for item in (
                        getattr(result.report, "loop_metrics", None) or []
                    )
                ],
            }
    return bool(result.ok and freq.ok and capacity.ok)


def record_cosim_gate(
    state: RunState,
    result: ToolResult,
    *,
    stage: str,
    current_best: bool = True,
    source_code: str | None = None,
) -> bool:
    if not isinstance(getattr(state, "metadata", None), dict):
        state.metadata = {}
    payload = getattr(result, "cosim", None)
    passed = bool(
        result.ok
        and payload is not None
        and getattr(payload, "passed", False)
    )
    record = {
        "stage": stage,
        "ok": passed,
        "phase": getattr(result, "phase", "unknown"),
        "source_sha256": hashlib.sha256(
            (state.kernel if source_code is None else source_code).encode(
                "utf-8"
            )
        ).hexdigest(),
        "latency_min": getattr(payload, "latency_min", None),
        "latency_avg": getattr(payload, "latency_avg", None),
        "latency_max": getattr(payload, "latency_max", None),
    }
    state.metadata.setdefault("cosim_gate_history", []).append(record)
    if current_best:
        state.cosim_ok = passed
        state.metadata["cosim_gate"] = record
    return passed


def mark_fully_verified(state: RunState) -> None:
    if (
        getattr(state, "interface_ok", False)
        and getattr(state, "csim_ok", False)
        and getattr(state, "synth_ok", False)
        and getattr(state, "frequency_ok", False)
        and getattr(state, "resource_ok", False)
        and (not state.task.requires_cosim or state.cosim_ok)
    ):
        state.last_verified_kernel = state.kernel
        if isinstance(getattr(state, "metadata", None), dict):
            state.metadata["last_verified_kernel_stage"] = "public_acceptance"


# ---------------------------------------------------------------------------
# Step functions — tool calls (simple, no LLM)
# ---------------------------------------------------------------------------


def step_csim(state: RunState) -> RunState:
    """Run C simulation on the current kernel."""
    if not validate_candidate(state, state.kernel, stage="baseline"):
        return state
    r = state.server.csim(state.kernel)
    state.results.append(r)
    state.csim_ok = r.ok
    state.log(f"csim: {r.brief()}")
    return state


def step_synth(state: RunState) -> RunState:
    """Run C synthesis on the current kernel (requires csim to have passed)."""
    if not state.csim_ok:
        state.log("synth: skipped (csim not ok)")
        return state

    # RepairAgent validates its accepted kernel with synthesis before returning.
    # When that successful result is the immediately preceding transcript item,
    # it is for the same current kernel and can be reused by the adjacent pipeline
    # step.  Requiring both synth_ok and adjacency avoids stale-result reuse.
    previous = state.results[-1] if state.results else None
    if (
        state.synth_ok
        and getattr(previous, "kind", None) == "synth"
        and getattr(previous, "ok", False)
        and getattr(previous, "report", None) is not None
    ):
        r = previous
        state.log("synth: reusing upstream successful synth report")
    else:
        r = state.server.synth(state.kernel)
        state.results.append(r)
    state.synth_ok = r.ok
    record_synth_gates(state, r, stage="pipeline_synth")
    lat = _latency(r)
    if lat is not None:
        state.best_latency = lat
    state.log(f"synth: {r.brief()}  latency={lat}")
    if not state.task.requires_cosim:
        mark_fully_verified(state)
    return state


def step_cosim(state: RunState) -> RunState:
    """Run C/RTL co-simulation (only for structural tasks)."""
    if not state.task.requires_cosim:
        state.cosim_ok = True  # not required → trivially ok
        return state
    r = state.server.cosim(state.kernel)
    state.results.append(r)
    if r.report is not None:
        # CoSimTool runs csynth_design before RTL simulation.  Preserve that
        # real report as the synthesis gate/evidence for structural-only mode.
        state.synth_ok = True
        lat = _latency(r)
        if lat is not None:
            state.best_latency = lat
    record_cosim_gate(
        state, r, stage="pipeline_cosim", source_code=state.kernel
    )
    state.log(f"cosim: {r.brief()}")
    mark_fully_verified(state)
    return state


def step_score(state: RunState) -> RunState:
    """Run profiled scoring: hidden-csim → synth(cand) → synth(base) → optional cosim.

    Uses the selected profile and verified device capacity:
        balanced: hardware_ratio = performance_ratio^0.55 * area_ratio^0.45
        extreme:  hardware_ratio = performance_ratio^0.70 * area_ratio^0.30
        score = 100 * validity * ratio_quality(hardware_ratio) * efficiency
        missing/over-capacity evidence = invalid
    """
    if not state.config.score:
        return state

    from scoring.scoring_v3 import (
        Anchor, QoREvidence, TaskScoringConfig, ValidityGates,
        verified_available_resources,
    )
    from scoring.profiles import grade_with_profile

    task = state.task
    kernel = state.kernel
    if not isinstance(getattr(state, "metadata", None), dict):
        state.metadata = {}
    grade_root = Path(state.config.output_root) / task.id / "grade"
    _start = time.monotonic()

    grading_results: list[tuple[str, ToolResult]] = []

    def _record(stage: str, result: ToolResult) -> None:
        grading_results.append((stage, result))
        state.metadata["grading_results"] = list(grading_results)
        state.metadata["grading_source"] = getattr(
            task, "grading_source", "hidden"
        )
        state.metadata["hidden_available"] = bool(
            getattr(task, "hidden_available", True)
        )

    def _gate_failure(reason: str) -> RunState:
        state.status = "failed"
        state.stop_reason = reason
        state.scorecard = None
        state.ref_scorecard = None
        state.log(f"evaluator gate failed before scoring: {reason}")
        return state

    # ── 1. Evaluator functional test (hidden or labelled fallback) ─────────
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

    # ── 2. Candidate synthesis and mandatory target gates ─────────────────
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
    if not record_synth_gates(
        state, cand_synth, stage="evaluator_candidate_synth"
    ):
        reason = (
            (state.metadata.get("frequency_gate") or {}).get("reason")
            if not state.frequency_ok
            else (state.metadata.get("resource_gate") or {}).get("reason")
        )
        return _gate_failure(str(reason or "candidate_target_gate_failed"))

    # ── 3. Required evaluator CoSim after synth/frequency/resource gates ───
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
        cosim_ok = record_cosim_gate(
            state,
            cosim,
            stage="evaluator_hidden_cosim",
            source_code=kernel,
        )
        cosim_report = getattr(cosim, "cosim", None)
        if not cosim_ok:
            return _gate_failure("required_cosim_failed")
        cosim_latency = cosim_report.latency_max
        if cosim_latency is None:
            return _gate_failure("required_cosim_report_missing")
    else:
        state.cosim_ok = True

    # ── 4. Baseline (starter) synthesis for the scoring anchor ─────────────
    base_files = dict(task.headers)
    base_files[task.kernel_name] = task.kernel_code
    base_synth = SynthTool().run(
        grade_root / "grade_synth_base", base_files,
        synth_sources=[task.kernel_name],
        top=task.top, part=task.part, clock_ns=task.clock_ns,
    )
    _record("starter_synth", base_synth)

    # ── 5. Build current scoring data structures ──────────────────────────
    cfg = TaskScoringConfig(
        task_id=task.id,
        task_type=task.type,
        difficulty=task.difficulty,
        requires_cosim=task.requires_cosim,
        budget_limit=task.budget,
        task_clock_ns=task.clock_ns,
    )

    # Anchor: starter code synthesis results
    starter_lat = (
        base_synth.report.latency_worst or base_synth.report.latency_avg
        if base_synth.ok and base_synth.report else None
    )
    starter_ii = (
        base_synth.report.interval_max
        if base_synth.ok and base_synth.report else None
    )
    starter_clock = (
        base_synth.report.clock_period_ns
        if base_synth.ok and base_synth.report else task.clock_ns
    )
    starter_resources = (
        base_synth.report.resources
        if base_synth.ok and base_synth.report else {}
    )
    starter_available = verified_available_resources(
        getattr(base_synth.report, "available", None)
        if base_synth.ok and base_synth.report else None
    )
    starter_valid = base_synth.ok

    # Check if reference solution exists for anchor fallback
    ref_synth = None
    ref_lat = None; ref_ii = None; ref_clock = None
    ref_resources = {}; ref_available = {}
    if task.reference_code:
        ref_files = dict(task.headers)
        ref_files[task.kernel_name] = task.reference_code
        ref_synth = SynthTool().run(
            grade_root / "grade_synth_ref", ref_files,
            synth_sources=[task.kernel_name],
            top=task.top, part=task.part, clock_ns=task.clock_ns,
        )
        _record("reference_synth", ref_synth)
        if ref_synth.ok and ref_synth.report:
            ref_lat = ref_synth.report.latency_worst or ref_synth.report.latency_avg
            ref_ii = ref_synth.report.interval_max
            ref_clock = ref_synth.report.clock_period_ns
            ref_resources = ref_synth.report.resources
            ref_available = verified_available_resources(
                getattr(ref_synth.report, "available", None)
            )

    # If starter synthesis succeeded but latency is undef (data-dependent loops),
    # fall back to reference anchor when available.  starter_valid is re-evaluated
    # so that ``no_valid_anchor`` is only returned when both anchors are unusable.
    starter_has_latency = starter_valid and starter_lat is not None
    if not starter_has_latency and ref_lat is not None:
        anchor = Anchor(
            source="reference", valid=True,
            latency=ref_lat, ii=ref_ii, clock_ns=ref_clock,
            resources=ref_resources, available=ref_available,
        )
    else:
        anchor = Anchor(
            source="starter" if starter_has_latency else ("reference" if ref_lat else "none"),
            valid=starter_has_latency or ref_lat is not None,
            latency=starter_lat if starter_has_latency else ref_lat,
            ii=starter_ii if starter_has_latency else ref_ii,
            clock_ns=starter_clock if starter_has_latency else ref_clock,
            resources=starter_resources if starter_has_latency else ref_resources,
            available=starter_available if starter_has_latency else ref_available,
        )

    # Evidence: candidate synthesis results
    cand_lat = (
        cand_synth.report.latency_worst or cand_synth.report.latency_avg
        if cand_synth.ok and cand_synth.report else None
    )
    cand_ii = (
        cand_synth.report.interval_max
        if cand_synth.ok and cand_synth.report else None
    )
    cand_clock = (
        cand_synth.report.clock_period_ns
        if cand_synth.ok and cand_synth.report else task.clock_ns
    )
    cand_resources = (
        cand_synth.report.resources
        if cand_synth.ok and cand_synth.report else {}
    )

    evidence = QoREvidence(
        candidate_latency=cand_lat,
        candidate_ii=cand_ii,
        candidate_clock_ns=cand_clock,
        cosim_latency=cosim_latency,
        candidate_resources=cand_resources,
    )

    # Gates
    gates = ValidityGates(
        hidden_csim_pass=csim.ok,
        hidden_cosim_pass=cosim_ok,
        synth_pass=cand_synth.ok,
        resource_capacity_pass=state.resource_ok,
    )

    # Budget & grading wall time. API tokens are observability-only in V8.
    budget = state.server.budget
    cost_spent = budget.spent if hasattr(budget, 'spent') else 0
    wall_time_s = time.monotonic() - _start

    # ── 6. Call the authoritative grade function ──────────────────────────
    scorecard = grade_with_profile(
        task_cfg=cfg,
        anchor=anchor,
        evidence=evidence,
        scoring_profile=getattr(state.config, "scoring_profile", "balanced"),
        cost_spent=cost_spent,
        wall_time_s=wall_time_s,
        gates=gates,
    )
    state.scorecard = scorecard
    state.log(
        f"V{scorecard.schema_version} score: {scorecard.score:.2f}/100  "
        f"(valid={scorecard.valid}, q_hw={scorecard.q_hw:.4f}, "
        f"eff={scorecard.efficiency:.4f})"
    )

    # ── 7. Reference-anchored scorecard (vs golden answer) ─────────────────
    if ref_lat is not None:
        ref_anchor = Anchor(
            source="reference", valid=True,
            latency=ref_lat, ii=ref_ii, clock_ns=ref_clock,
            resources=ref_resources,
            available=ref_available,
        )
        ref_scorecard = grade_with_profile(
            task_cfg=cfg,
            anchor=ref_anchor,
            evidence=evidence,
            scoring_profile=getattr(state.config, "scoring_profile", "balanced"),
            cost_spent=cost_spent,
            wall_time_s=wall_time_s,
            gates=gates,
        )
        state.ref_scorecard = ref_scorecard
        state.log(
            f"V{ref_scorecard.schema_version} score vs reference: "
            f"{ref_scorecard.score:.2f}/100  "
            f"(valid={ref_scorecard.valid}, q_hw={ref_scorecard.q_hw:.4f})"
        )

    return state


def step_public_acceptance(state: RunState) -> RunState:
    """Fold public correctness and target gates into one truthful terminal gate."""

    failures: list[str] = []
    if not state.interface_ok:
        failures.append("interface_failed")
    if not state.csim_ok:
        failures.append("csim_failed")
    if not state.synth_ok:
        failures.append("synth_failed")
    if not state.frequency_ok:
        failures.append(
            str(
                (state.metadata.get("frequency_gate") or {}).get(
                    "reason", "frequency_failed"
                )
            )
        )
    if not state.resource_ok:
        failures.append(
            str(
                (state.metadata.get("resource_gate") or {}).get(
                    "reason", "resource_failed"
                )
            )
        )
    if state.task.requires_cosim and not state.cosim_ok:
        failures.append("cosim_failed")

    if failures:
        state.status = "failed"
        state.stop_reason = failures[0]
        state.metadata["public_acceptance"] = {
            "ok": False,
            "failures": failures,
        }
        return state

    mark_fully_verified(state)
    state.status = "completed"
    state.stop_reason = ""
    state.metadata["public_acceptance"] = {"ok": True, "failures": []}
    return state


def step_finalize(state: RunState) -> RunState:
    """Persist the final kernel and derive the truthful terminal status."""
    if not isinstance(getattr(state, "metadata", None), dict):
        state.metadata = {}
    if getattr(state, "last_verified_kernel", None) is not None:
        state.kernel = state.last_verified_kernel
    elif (
        state.status in ("failed", "budget_exceeded", "infrastructure_error")
        and getattr(state, "safe_fallback_kernel", None) is not None
    ):
        # Never publish an unverified LLM proposal. If no fully accepted
        # candidate exists, preserve the immutable public starter and keep the
        # truthful failure status.
        state.kernel = state.safe_fallback_kernel
    out = Path(state.config.output_root) / state.task.id
    out.mkdir(parents=True, exist_ok=True)
    kernel_path = out / f"final_{state.task.kernel_name}"
    kernel_path.write_text(state.kernel, encoding="utf-8")
    state.log(f"final kernel → {kernel_path}")
    state.metadata["finalized"] = True
    state.metadata["final_kernel_path"] = str(kernel_path)

    if state.status in ("budget_exceeded", "infrastructure_error", "failed"):
        return state
    if state.scorecard is not None:
        if getattr(state.scorecard, "valid", False):
            state.status = "completed"
        else:
            state.status = "failed"
            state.stop_reason = (
                getattr(state.scorecard, "gate_reason", "") or "scoring_invalid"
            )
    elif not hasattr(state, "interface_ok"):
        # Compatibility for callers constructing the pre-P0 lightweight state.
        if not state.csim_ok:
            state.status = "failed"
            state.stop_reason = "csim_failed"
        elif not state.synth_ok:
            state.status = "failed"
            state.stop_reason = "synth_failed"
        elif state.task.requires_cosim and not state.cosim_ok:
            state.status = "failed"
            state.stop_reason = "cosim_failed"
        else:
            state.status = "completed"
    return state


# ---------------------------------------------------------------------------
# Step functions — agent-based (delegate to agents/*.py)
# ---------------------------------------------------------------------------


def step_repair(state: RunState) -> RunState:
    """Run the repair agent loop if csim failed."""
    if state.csim_ok and state.synth_ok:
        state.log("repair: skipped (csim and synth already ok)")
        return state
    if state.llm is None:
        state.log("repair: no LLM client — cannot repair")
        state.status = "failed"
        state.stop_reason = "repair_no_llm"
        return state

    try:
        from agent.agents.repair import RepairAgent
    except ImportError:
        state.log("repair: RepairAgent not implemented yet")
        return state

    agent = RepairAgent(llm=state.llm, max_attempts=state.config.max_repair_attempts)
    result = agent.run(state)
    state.kernel = result.kernel
    # result is the same RunState object; results already appended in-place
    state.csim_ok = result.csim_ok
    state.log(f"repair: csim_ok={result.csim_ok}")
    return state


def step_structural_repair(state: RunState) -> RunState:
    """Run structural repair if cosim failed on a structural task."""
    if state.cosim_ok:
        state.log("structural_repair: skipped (cosim already ok)")
        return state
    if not state.task.requires_cosim:
        return state
    if state.llm is None:
        state.log("structural_repair: no LLM client")
        state.status = "failed"
        state.stop_reason = "structural_repair_no_llm"
        return state

    try:
        from agent.agents.structural import StructuralRepairAgent
    except ImportError:
        state.log("structural_repair: StructuralRepairAgent not implemented yet")
        return state

    agent = StructuralRepairAgent(llm=state.llm, max_attempts=state.config.max_structural_attempts)
    result = agent.run(state)
    state.kernel = result.kernel
    # result is the same RunState object; cosim_ok set in-place on success
    state.cosim_ok = result.cosim_ok
    state.log(f"structural_repair: {result.status}")
    return state


def step_optimize(state: RunState) -> RunState:
    """Run the optimization agent loop."""
    if state.llm is None:
        state.log("optimize: no LLM client")
        state.status = "failed"
        state.stop_reason = "optimize_no_llm"
        return state

    try:
        from agent.agents.optimize import OptimizeAgent
    except ImportError:
        state.log("optimize: OptimizeAgent not implemented yet")
        return state

    if state.config.competition:
        from agent.agents.competition import DiverseOptimizationStage

        agent = DiverseOptimizationStage(
            state.llm,
            max_candidates=state.config.max_optimization_rounds,
            scoring_profile=getattr(
                state.config, "scoring_profile", "balanced"
            ),
        )
        result = agent.run(state)
    else:
        agent = OptimizeAgent(
            llm=state.llm,
            max_rounds=state.config.max_optimization_rounds,
            scoring_profile=getattr(
                state.config, "scoring_profile", "balanced"
            ),
        )
        result = agent.run(state)
    state.kernel = result.kernel
    # result is the same RunState object; results already appended in-place
    if result.best_latency is not None:
        state.best_latency = result.best_latency
    state.log(f"optimize: {result.status}  latency={state.best_latency}")
    return state


# ---------------------------------------------------------------------------
# Pipeline builder — the single place to understand the full workflow
# ---------------------------------------------------------------------------


def build_pipeline(
    *,
    config: AgentConfig,
    task: Task,
    server: ToolServer,
    llm: Any = None,
) -> Pipeline:
    """Build the agent pipeline based on mode and task type.

    This is **the** function to read when you want to understand or modify
    the agent's execution order.  Each ``Step`` entry below corresponds to
    one stage in the run.

    Modes:
    - ``auto``       — tool-result-driven repair → synth repair → cosim repair → optimize
    - ``baseline``   — csim → synth → score (no LLM)
    - ``repair``     — csim → repair → synth → score
    - ``optimize``   — csim → synth → optimize → score
    - ``structural`` — csim → synth → cosim → structural_repair → score
    - ``full``       — all of the above, conditioned on task type
    """
    mode = config.mode

    # Every pipeline starts with an init step
    def _init(state: RunState) -> RunState:
        state.log(
            f"task={task.id}  type={task.type}  mode={mode}  "
            f"scoring_profile={getattr(config, 'scoring_profile', 'balanced')}  "
            f"budget={server.budget.total}"
        )
        return state

    pipeline = Pipeline(name=f"fpt26-v3/{mode}")
    pipeline.steps.append(Step("init", _init, desc="initialise run state"))

    # ---- Stage 1: Baseline correctness check ----
    pipeline.steps.append(Step("csim", step_csim, desc="C simulation (baseline)"))

    # ---- Stage 2: Repair (if enabled and needed) ----
    if mode in ("auto", "repair", "full"):
        pipeline.steps.append(
            Step("repair", step_repair,
                 condition=lambda s: not s.csim_ok,
                 desc="LLM repair loop: modify code → csim → read log → retry")
        )

    # ---- Stage 3: Synthesis ----
    pipeline.steps.append(Step("synth", step_synth, desc="C synthesis (baseline PPA)"))

    # Auto/repair must also handle designs that pass CSim but fail synthesis.
    if mode in ("auto", "repair", "full"):
        pipeline.steps.append(
            Step(
                "synth_repair",
                step_repair,
                condition=lambda s: s.csim_ok and not s.synth_ok,
                desc="LLM synthesis-repair loop driven by the failed synth log",
            )
        )

    # ---- Stage 4: Co-simulation (structural tasks) ----
    if task.requires_cosim:
        pipeline.steps.append(
            Step(
                "cosim",
                step_cosim,
                desc="C/RTL co-simulation (includes synthesis evidence)",
            )
        )

    # ---- Stage 5: Structural repair ----
    if task.requires_cosim and mode in ("auto", "structural", "full"):
        pipeline.steps.append(
            Step("structural_repair", step_structural_repair,
                 condition=lambda s: not s.cosim_ok,
                 desc="Structural repair: fix streaming/dataflow deadlocks")
        )

    # ---- Stage 6: Optimization ----
    if mode in ("auto", "optimize", "full"):
        optimize_desc = (
            "Independent strategy competition: measure candidates, pick best Q_HW"
            if config.competition
            else "LLM optimization loop: propose → csim → synth → compare latency"
        )
        pipeline.steps.append(
            Step("optimize", step_optimize,
                 condition=lambda s: (
                     s.csim_ok
                     and s.synth_ok
                     and s.interface_ok
                     and s.frequency_ok
                     and s.resource_ok
                     and (not s.task.requires_cosim or s.cosim_ok)
                 ),
                 desc=optimize_desc)
        )

    # ---- Stage 7: Public submission acceptance ----
    pipeline.steps.append(
        Step(
            "public_acceptance",
            step_public_acceptance,
            desc="Interface/correctness/synth/frequency/resource/final-cosim gates",
        )
    )

    # ---- Stage 8: Finalize ----
    pipeline.steps.append(Step("finalize", step_finalize, desc="Persist final kernel"))

    return pipeline
