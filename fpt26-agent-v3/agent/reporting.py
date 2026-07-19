"""Run reporting with derived evaluation metrics.

Writes a detailed run summary to ``runs/<task_id>/run_report.json``
and prints a console-friendly scorecard.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from agent.agents.base import RunState


# ---------------------------------------------------------------------------
# Derived metrics
# ---------------------------------------------------------------------------


def _tool_breakdown(results: list) -> dict[str, int]:
    """Count tool calls by kind (csim / synth / cosim)."""
    breakdown: dict[str, int] = {}
    for r in results:
        kind = getattr(r, "kind", "unknown")
        breakdown[kind] = breakdown.get(kind, 0) + 1
    return breakdown


def _attempts_to_pass(results: list, kind: str = "csim") -> int:
    """Count real calls through the first success, or all calls if none pass."""
    attempts = 0
    for r in results:
        k = getattr(r, "kind", "")
        if k != kind:
            continue
        attempts += 1
        if getattr(r, "ok", False):
            return attempts
    return attempts


def _wall_time(results: list) -> float:
    """Total wall-clock seconds across all tool calls."""
    return sum(getattr(r, "elapsed_s", 0.0) for r in results)


def _resource_growth(candidate: dict, baseline: dict) -> dict[str, float] | None:
    """Compute resource growth ratios (candidate / baseline)."""
    if not candidate or not baseline:
        return None
    growth: dict[str, float] = {}
    for key in ("LUT", "FF", "DSP", "BRAM_18K"):
        base = baseline.get(key, 0)
        cand = candidate.get(key, 0)
        if base and base > 0:
            growth[key] = round(cand / base, 2)
        elif cand > 0:
            growth[key] = float("inf")
        else:
            growth[key] = 1.0
    return growth


def _compute_derived(state: RunState) -> dict[str, Any]:
    """Compute all derived evaluation metrics from the run state."""
    results = state.results
    breakdown = _tool_breakdown(results)
    total_spent = getattr(state.server.budget, "spent", 0)
    total_budget = getattr(state.server.budget, "total", 1)

    metrics: dict[str, Any] = {
        "tool_breakdown": breakdown,
        "wall_time_seconds": round(_wall_time(results), 1),
        "csim_attempts": _attempts_to_pass(results, "csim"),
        "cosim_attempts": _attempts_to_pass(results, "cosim"),
        "budget_utilization": round(total_spent / max(total_budget, 1), 3),
        "budget_efficiency": None,
        "resource_growth": None,
        "resource_efficiency": None,
    }

    # Budget efficiency: score points per credit spent
    if state.scorecard is not None and total_spent > 0:
        sc = state.scorecard
        score_val = sc.score if hasattr(sc, 'score') else 0
        if score_val > 0:
            metrics["budget_efficiency"] = round(score_val / max(metrics["budget_utilization"], 0.001), 3)

    # Resource efficiency: acceleration per unit area growth
    if state.scorecard is not None:
        sc = state.scorecard
        is_v3 = hasattr(sc, 'schema_version') and getattr(sc, 'schema_version', 0) >= 5
        if is_v3 and sc.valid:
            # V3 scorecard: use latency_ratio and area_growth
            metrics["resource_growth"] = sc.growth_by_resource
            metrics["baseline_resources"] = sc.baseline_resources
            metrics["candidate_resources"] = sc.candidate_resources
            if sc.latency_ratio > 0 and sc.area_growth > 0:
                metrics["resource_efficiency"] = round(
                    sc.latency_ratio / max(sc.area_growth, 1.0), 3
                )
        elif not is_v3:
            # Legacy scorecard fields
            cand_rep = getattr(sc, 'candidate_report', None)
            base_rep = getattr(sc, 'baseline_report', None)
            if cand_rep is not None and base_rep is not None:
                cand_r = cand_rep.resources if hasattr(cand_rep, "resources") else {}
                base_r = base_rep.resources if hasattr(base_rep, "resources") else {}
                growth = _resource_growth(cand_r, base_r)
                metrics["resource_growth"] = growth
                metrics["baseline_resources"] = base_r
                metrics["candidate_resources"] = cand_r

                accel = getattr(sc, 'acceleration', None)
                if growth and accel and accel > 0:
                    max_growth = max(
                        growth.get("LUT", 1.0),
                        growth.get("FF", 1.0),
                        growth.get("DSP", 1.0),
                    )
                    if max_growth > 0:
                        metrics["resource_efficiency"] = round(
                            accel / max(max_growth, 1.0), 3
                        )

    return metrics


def _llm_summary(state: RunState) -> dict[str, Any] | None:
    """Return non-sensitive LLM configuration and exact token accounting."""
    client = state.llm
    if client is None:
        return None

    summary: dict[str, Any] = {
        "client": type(client).__name__,
        "model": getattr(client, "model", None),
        "temperature": getattr(client, "temperature", None),
        "max_tokens": getattr(client, "max_tokens", None),
    }
    token_usage = getattr(client, "token_usage", None)
    snapshot = getattr(token_usage, "snapshot", None)
    summary["token_usage"] = snapshot() if callable(snapshot) else None
    return summary


def _reported_cosim_status(state: RunState) -> bool | None:
    """Return N/A for tasks whose validity does not require RTL co-sim."""
    if not state.task.requires_cosim:
        return None
    return state.cosim_ok


def _toolchain_evidence(state: RunState) -> dict[str, Any]:
    """Extract the actual Vitis banner/target evidence emitted by real tools."""

    logs = [
        getattr(result, "log", "") or ""
        for result in state.results
    ]
    logs.extend(
        getattr(result, "log", "") or ""
        for _, result in state.metadata.get("grading_results", [])
    )
    joined = "\n".join(logs)
    versions = sorted(set(re.findall(r"vitis-run v(\d+\.\d+)", joined)))
    hls_builds = sorted(
        set(
            (version, build)
            for version, build in re.findall(
                r"HLS Build v(\d+\.\d+)\s+(\d+)", joined
            )
        )
    )
    observed_parts = sorted(
        set(re.findall(r"\bset_part\s+([A-Za-z0-9_.-]+)", joined))
    )
    preflight = state.metadata.get("task_preflight", {})
    configured = preflight.get("configured_vitis_root")
    probed_version = preflight.get("observed_vitis_version")
    probed_build = preflight.get("observed_vitis_build")
    required_version = "2025.2"
    required_part = getattr(state.task, "part", None)
    return {
        "configured_vitis_root": configured,
        "required_vitis_version": required_version,
        "preflight_vitis_version": probed_version,
        "preflight_vitis_build": probed_build,
        "observed_vitis_versions": versions,
        "observed_hls_builds": [
            {"version": version, "build": build}
            for version, build in hls_builds
        ],
        "required_part": required_part,
        "observed_parts": observed_parts,
        "real_tool_banner_observed": bool(versions),
        "version_gate_ok": (
            probed_version == required_version
            and (not versions or versions == [required_version])
        ),
        "part_gate_ok": (
            bool(observed_parts)
            and required_part is not None
            and set(observed_parts) == {required_part}
        ),
    }


def _tool_result_record(result: Any) -> dict[str, Any]:
    """Serialize one existing tool result without changing its semantics."""
    brief = getattr(result, "brief", None)
    return {
        "kind": getattr(result, "kind", "unknown"),
        "ok": bool(getattr(result, "ok", False)),
        "phase": getattr(result, "phase", "unknown"),
        "return_code": getattr(result, "return_code", None),
        "elapsed_s": round(float(getattr(result, "elapsed_s", 0.0)), 3),
        "brief": brief() if callable(brief) else None,
        "log": getattr(result, "log", "") or "",
    }


def _execution_trace(state: RunState) -> dict[str, Any]:
    """Return auditable metered and unmetered tool evidence for the report."""
    server = state.server
    run_root = Path(getattr(server, "run_root", ""))
    transcript = []
    for entry in getattr(server, "transcript", []):
        transcript.append(
            {
                "n": entry.n,
                "kind": entry.kind,
                "phase": entry.phase,
                "spent": entry.spent,
                "detail": entry.detail,
                "artifact_dir": str(run_root / f"{entry.kind}_{entry.n}"),
            }
        )

    grade_root = Path(state.config.output_root) / state.task.id / "grade"
    grade_dirs = {
        "hidden_csim": "grade_csim",
        "hidden_cosim": "grade_cosim",
        "candidate_synth": "grade_synth_cand",
        "starter_synth": "grade_synth_base",
        "reference_synth": "grade_synth_ref",
    }
    grading = []
    for stage, result in getattr(state, "metadata", {}).get("grading_results", []):
        record = _tool_result_record(result)
        record["stage"] = stage
        record["artifact_dir"] = str(grade_root / grade_dirs.get(stage, stage))
        grading.append(record)

    return {
        "transcript": transcript,
        "metered_results": [_tool_result_record(r) for r in state.results],
        "grading_results": grading,
    }


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------


def write_run_report(state: RunState) -> Path:
    """Write a JSON run report with derived evaluation metrics to output dir."""
    out_dir = Path(state.config.output_root) / state.task.id
    out_dir.mkdir(parents=True, exist_ok=True)

    derived = _compute_derived(state)

    report: dict[str, Any] = {
        "schema_version": 1,
        "task_id": state.task.id,
        "task_type": state.task.type,
        "task_difficulty": state.task.difficulty,
        "run_role": getattr(
            state.config, "run_role", state.metadata.get("run_role")
        ),
        "mode": state.config.mode,
        "scoring_profile": getattr(
            state.config, "scoring_profile", "balanced"
        ),
        "competition": state.config.competition,
        "status": state.status,
        "status_vocabulary": [
            "running",
            "completed",
            "failed",
            "budget_exceeded",
            "infrastructure_error",
        ],
        "csim_ok": state.csim_ok,
        "synth_ok": state.synth_ok,
        "cosim_ok": _reported_cosim_status(state),
        "gates": {
            "interface": state.metadata.get("interface_gate"),
            "frequency_100mhz": state.metadata.get("frequency_gate"),
            "resource_capacity": state.metadata.get("resource_gate"),
            "required_cosim": state.metadata.get("cosim_gate"),
            "public_acceptance": state.metadata.get("public_acceptance"),
            "evaluator_acceptance": state.metadata.get("evaluator_acceptance"),
        },
        "interface_contract": state.metadata.get("interface_contract"),
        "candidate_validation_history": state.metadata.get(
            "interface_validations", []
        ),
        "synthesis_gate_history": state.metadata.get(
            "synth_gate_history", []
        ),
        "cosim_gate_history": state.metadata.get("cosim_gate_history", []),
        "final_hardware": {
            **(state.metadata.get("best_synth_metrics") or {}),
            "cosim": state.metadata.get("cosim_gate"),
        },
        "task_preflight": state.metadata.get("task_preflight"),
        "target": {
            "part": getattr(state.task, "part", None),
            "clock_ns": getattr(state.task, "clock_ns", None),
            "minimum_frequency_mhz": 100.0,
        },
        "toolchain": _toolchain_evidence(state),
        "grading": {
            "source": state.metadata.get("grading_source"),
            "hidden_available": state.metadata.get("hidden_available"),
            "is_fallback": state.metadata.get("grading_source")
            in {"public_fallback", "proxy_grading"},
        },
        "model_compliance": state.metadata.get("model_compliance"),
        "best_latency": state.best_latency,
        "stop_reason": state.stop_reason,
        "tool_call_count": len(state.results),
        "budget": {
            "total": getattr(state.server.budget, "total", None),
            "spent": getattr(state.server.budget, "spent", None),
        },
        # Derived metrics
        "evaluation": derived,
        "execution_trace": _execution_trace(state),
        "llm": _llm_summary(state),
    }
    final_path = state.metadata.get("final_kernel_path")
    final_kernel = getattr(state, "kernel", "")
    final_bytes = final_kernel.encode("utf-8")
    if final_path and Path(final_path).is_file():
        final_bytes = Path(final_path).read_bytes()
    report["final_artifact"] = {
        "path": final_path,
        "sha256": hashlib.sha256(final_bytes).hexdigest(),
        "fully_verified": bool(
            getattr(state, "last_verified_kernel", None) is not None
            and final_kernel == getattr(state, "last_verified_kernel", None)
        ),
        "fallback_starter_used": bool(
            getattr(state, "last_verified_kernel", None) is None
            and getattr(state, "safe_fallback_kernel", None) is not None
            and final_kernel == getattr(state, "safe_fallback_kernel", None)
        ),
    }
    if getattr(state, "metadata", {}).get("optimization_search"):
        report["optimization_search"] = state.metadata["optimization_search"]

    if state.scorecard is not None:
        sc = state.scorecard
        # Support both V3 (scoring_v3) and legacy (llm4hls) scorecard formats
        is_v3 = hasattr(sc, 'schema_version') and getattr(sc, 'schema_version', 0) >= 5
        if is_v3:
            report["scoring"] = {
                "schema_version": sc.schema_version,
                "scoring_profile": getattr(sc, "scoring_profile", "balanced"),
                "performance_weight": getattr(sc, "performance_weight", 0.55),
                "area_weight": getattr(sc, "area_weight", 0.45),
                "area_reward_capped": getattr(sc, "area_reward_capped", False),
                "score": sc.score,
                "score_max": sc.score_max,
                "score_pct": round(sc.score / max(sc.score_max, 1) * 100, 1),
                "valid": sc.valid,
                "gate_reason": sc.gate_reason,
                "csim_pass": sc.csim_pass,
                "synth_pass": sc.synth_pass,
                "cosim_pass": sc.cosim_pass,
                "resource_capacity_pass": getattr(
                    sc, "resource_capacity_pass", None
                ),
                "anchor_source": sc.anchor_source,
                "latency_ratio": sc.latency_ratio,
                "acceleration_source": getattr(
                    sc, "acceleration_source", "synth"
                ),
                "cosim_latency_used": getattr(sc, "cosim_latency_used", None),
                "performance_ratio": getattr(sc, "performance_ratio", sc.latency_ratio),
                "area_growth": sc.area_growth,
                "area_ratio": getattr(
                    sc, "area_ratio", 1.0 / max(sc.area_growth, 1e-9)
                ),
                "effective_area_ratio": getattr(
                    sc,
                    "effective_area_ratio",
                    getattr(sc, "area_ratio", 1.0 / max(sc.area_growth, 1e-9)),
                ),
                "bottleneck_resource": sc.bottleneck_resource,
                "q_perf": sc.q_perf,
                "q_area": sc.q_area,
                "hardware_ratio": getattr(sc, "hardware_ratio", None),
                "q_hw": sc.q_hw,
                "efficiency": sc.efficiency,
                "growth_by_resource": sc.growth_by_resource,
                "baseline_resources": sc.baseline_resources,
                "candidate_resources": sc.candidate_resources,
                "available_resources": getattr(sc, "available_resources", {}),
                "cost_spent": sc.cost_spent,
                "cost_limit": sc.cost_limit,
                "wall_time_s": sc.wall_time_s,
                "time_limit_s": sc.time_limit_s,
            }
            # Reference-anchored scorecard (vs golden answer)
            if getattr(state, 'ref_scorecard', None) is not None:
                rsc = state.ref_scorecard
                report["scoring_vs_reference"] = {
                    "anchor": "reference",
                    "scoring_profile": getattr(
                        rsc, "scoring_profile", "balanced"
                    ),
                    "performance_weight": getattr(
                        rsc, "performance_weight", 0.55
                    ),
                    "area_weight": getattr(rsc, "area_weight", 0.45),
                    "area_reward_capped": getattr(
                        rsc, "area_reward_capped", False
                    ),
                    "score": rsc.score,
                    "score_pct": round(rsc.score / max(rsc.score_max, 1) * 100, 1),
                    "valid": rsc.valid,
                    "q_hw": rsc.q_hw,
                    "q_perf": rsc.q_perf,
                    "q_area": rsc.q_area,
                    "latency_ratio": rsc.latency_ratio,
                    "area_growth": rsc.area_growth,
                    "area_ratio": getattr(
                        rsc, "area_ratio", 1.0 / max(rsc.area_growth, 1e-9)
                    ),
                    "effective_area_ratio": getattr(
                        rsc,
                        "effective_area_ratio",
                        getattr(
                            rsc,
                            "area_ratio",
                            1.0 / max(rsc.area_growth, 1e-9),
                        ),
                    ),
                    "hardware_ratio": getattr(rsc, "hardware_ratio", None),
                    "efficiency": rsc.efficiency,
                    "bottleneck_resource": rsc.bottleneck_resource,
                    "reference_latency": rsc.anchor_latency,
                    "reference_ii": rsc.anchor_ii,
                    "reference_clock_ns": rsc.anchor_clock_ns,
                    "reference_resources": rsc.baseline_resources,
                    "candidate_resources": rsc.candidate_resources,
                    "growth_by_resource": rsc.growth_by_resource,
                }
        else:
            report["scoring"] = {
                "score": sc.score,
                "score_max": getattr(sc, 'difficulty', 1),
                "score_pct": round(sc.score / max(getattr(sc, 'difficulty', 1), 1) * 100, 1),
                "functional_pass": getattr(sc, 'functional_pass', None),
                "synth_pass": getattr(sc, 'synth_pass', None),
                "cosim_pass": getattr(sc, 'cosim_pass', None),
                "baseline_latency": getattr(sc, 'baseline_latency', None),
                "candidate_latency": getattr(sc, 'candidate_latency', None),
                "acceleration": getattr(sc, 'acceleration', None),
                "is_opt": getattr(sc, 'is_opt', None),
            }

    report_path = out_dir / "run_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report_path


def write_failure_report(
    *,
    output_root: str,
    task_id: str,
    run_role: str,
    status: str,
    stop_reason: str,
    error_type: str,
    error_message: str,
) -> Path:
    """Persist a truthful bootstrap/infrastructure failure without a RunState."""

    out_dir = Path(output_root) / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "run_report.json"
    report = {
        "schema_version": 1,
        "task_id": task_id,
        "run_role": run_role,
        "status": status,
        "stop_reason": stop_reason,
        "error": {
            "type": error_type,
            "message": error_message,
        },
        "scoring": None,
        "execution_trace": {
            "transcript": [],
            "metered_results": [],
            "grading_results": [],
        },
    }
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report_path


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------


def _res_str(r: dict) -> str:
    """Full resource string — all five resources."""
    parts = []
    for k in ("LUT", "FF", "DSP", "BRAM_18K", "URAM"):
        v = r.get(k, 0)
        parts.append(f"{k}={v}")
    return " ".join(parts)


def _loop_str(loop_metrics: list) -> str:
    """Format loop metrics as string."""
    if not loop_metrics:
        return ""
    loops = []
    for lm in loop_metrics:
        trip = lm.get("trip_count", "?")
        lat = lm.get("latency", "?")
        ii = lm.get("pipeline_ii", "?")
        name = lm.get("name", "?")
        loops.append(f"{name}(trip={trip},lat={lat},II={ii})")
    return ", ".join(loops)


def _synth_info(result: Any) -> dict[str, Any] | None:
    """Normalize one successful synthesis result for console comparison."""
    report = getattr(result, "report", None)
    if not getattr(result, "ok", False) or report is None:
        return None
    loops = [dict(item) for item in (report.loop_metrics or [])]
    return {
        "latency": report.latency_worst or report.latency_avg,
        "top_interval": report.interval_max,
        "loop_ii": (
            loops[0].get("pipeline_ii") if loops else None
        ),
        "clock_ns": report.clock_period_ns,
        "resources": dict(report.resources),
        "loop_metrics": loops,
    }


def _grading_synth_info(state: RunState, stage: str) -> dict[str, Any] | None:
    """Find a named evaluator-side synthesis without confusing it with agent tools."""
    for recorded_stage, result in state.metadata.get("grading_results", []):
        if recorded_stage == stage:
            return _synth_info(result)
    return None


def _final_synth_info(state: RunState) -> dict[str, Any] | None:
    """Return metrics for the kernel that was actually selected and finalized."""
    metrics = state.metadata.get("best_synth_metrics")
    if isinstance(metrics, dict) and metrics:
        loops = [dict(item) for item in (metrics.get("loop_metrics") or [])]
        return {
            "latency": (
                metrics.get("latency_worst")
                if metrics.get("latency_worst") is not None
                else metrics.get("latency_avg")
            ),
            "top_interval": metrics.get("interval_max"),
            "loop_ii": (
                loops[0].get("pipeline_ii") if loops else None
            ),
            "clock_ns": metrics.get("clock_period_ns"),
            "resources": dict(metrics.get("resources") or {}),
            "loop_metrics": loops,
        }
    # Evaluator scoring always synthesizes exactly the submitted kernel.
    return _grading_synth_info(state, "candidate_synth")


def print_evaluation(state: RunState) -> None:
    """Print a structured optimization report to stdout."""
    derived = _compute_derived(state)
    breakdown = derived["tool_breakdown"]
    budget = state.server.budget
    total_budget = getattr(budget, "total", "?")
    spent = getattr(budget, "spent", "?")
    sc = state.scorecard
    rsc = getattr(state, 'ref_scorecard', None)
    is_v3 = sc is not None and hasattr(sc, 'schema_version') and getattr(sc, 'schema_version', 0) >= 5

    # ── Extract synth transcript indices ────────────────────────────────
    synth_tx_indices: list[int] = []
    for entry in state.server.transcript:
        if entry.kind == "synth":
            synth_tx_indices.append(entry.n)

    # ── Structured candidate data (from OptimizeAgent) ──────────────────
    structured = getattr(state, 'metadata', {}).get("synth_candidates", [])

    # ── Build candidate list from structured data (preferred) or results ─
    baseline_info: dict | None = None
    candidates_info: list[dict] = []
    for c in structured:
        if c.get("is_baseline") or c.get("round") == 0:
            baseline_info = c
        else:
            candidates_info.append(c)

    # The evaluator's explicit starter synthesis is the strongest baseline
    # evidence. Agent-side results are a fallback for submission-only reports.
    graded_baseline = _grading_synth_info(state, "starter_synth")
    if graded_baseline is not None:
        graded_baseline.update(
            {"round": 0, "is_baseline": True, "decision": "BASELINE"}
        )
        baseline_info = graded_baseline

    # Extract baseline from results if no structured/evaluator data
    if baseline_info is None:
        for r in state.results:
            info = _synth_info(r)
            if getattr(r, "kind", None) == "synth" and info is not None:
                info.update(
                    {"round": 0, "is_baseline": True, "decision": "BASELINE"}
                )
                baseline_info = info
                break

    # ── Helper: total area ──────────────────────────────────────────────
    def _total_area(res: dict) -> int:
        return res.get("LUT", 0) + res.get("FF", 0) + res.get("DSP", 0)

    # ── Header ──────────────────────────────────────────────────────────
    task_id = state.task.id
    print(f"\n{'='*80}")
    print(f"  OPTIMIZATION REPORT — {task_id}")
    print(f"{'='*80}")

    gates = [
        ("csim", state.csim_ok),
        ("synth", state.synth_ok),
        ("cosim", _reported_cosim_status(state)),
    ]
    gate_str = ", ".join(
        f"{n}={('N/A' if v is None else ('PASS' if v else 'FAIL'))}"
        for n, v in gates
    )
    status = (
        "PASS"
        if state.status == "completed"
        else "FAIL"
    )
    stage = getattr(sc, 'stage', '?') if is_v3 else "?"
    grading_time = sc.wall_time_s if is_v3 else 0
    print(f"  Status: {status} | Stage: {stage} | Gates: {gate_str}")
    print(f"  Budget: {spent}/{total_budget} credits ({derived['budget_utilization']*100:.0f}%) | "
          f"Wall: {derived['wall_time_seconds']:.0f}s | Grading: {grading_time:.0f}/3600s | "
          f"Tools: csim×{breakdown.get('csim',0)}, synth×{breakdown.get('synth',0)}, cosim×{breakdown.get('cosim',0)}")

    # ── Score ───────────────────────────────────────────────────────────
    print(f"\n  {'SCORE':─^76}")
    if is_v3:
        starter_score = f"{sc.score:.2f}/{sc.score_max:.0f} ({round(sc.score / max(sc.score_max, 1) * 100, 1)}%)"
        print(f"  Starter anchor  : {starter_score} | Q_perf={sc.q_perf:.4f} | Q_area={sc.q_area:.4f} | Q_HW={sc.q_hw:.4f}")
        if rsc is not None:
            ref_score_str = f"{rsc.score:.2f}/{rsc.score_max:.0f} ({round(rsc.score / max(rsc.score_max, 1) * 100, 1)}%)"
            print(f"  Reference anchor: {ref_score_str} | Q_HW={rsc.q_hw:.4f} | Valid={rsc.valid}")
        print(f"  Efficiency={sc.efficiency:.4f} | HW ratio={getattr(sc, 'hardware_ratio', 1.0):.4f}x")
    elif sc is not None:
        print(f"  Score: {sc.score:.3f} / {getattr(sc, 'difficulty', '?')}")
    else:
        print(
            "  Evaluator score: N/A (submission role uses public acceptance "
            "gates only)"
        )

    # ── STARTER / FINAL BEST / REFERENCE table ──────────────────────────
    base_res = baseline_info.get("resources", {}) if baseline_info else {}
    base_lat = baseline_info.get("latency") if baseline_info else None
    base_ti = baseline_info.get("top_interval") if baseline_info else None
    base_lii = baseline_info.get("loop_ii") if baseline_info else None
    base_clk = baseline_info.get("clock_ns") if baseline_info else None

    # Best = measured synthesis for the kernel ultimately selected/finalized.
    # Never substitute the score anchor: it describes the starter/reference.
    final_info = _final_synth_info(state)
    best_res = (
        final_info.get("resources", {}) if final_info is not None else base_res
    )
    best_lat = (
        final_info.get("latency") if final_info is not None else base_lat
    )
    best_ti = (
        final_info.get("top_interval") if final_info is not None else base_ti
    )
    best_lii = (
        final_info.get("loop_ii") if final_info is not None else base_lii
    )
    best_clk = (
        final_info.get("clock_ns") if final_info is not None else base_clk
    )

    ref_lat = rsc.anchor_latency if rsc else None
    ref_ti = rsc.anchor_ii if rsc else None
    ref_clk = rsc.anchor_clock_ns if rsc else None
    ref_res = rsc.baseline_resources if rsc else {}

    # Is final best same as baseline?
    final_is_baseline = (best_lat == base_lat and best_res == base_res)

    print(f"\n  {'STARTER / FINAL BEST / REFERENCE':─^76}")
    print(f"  {'':<22} {'Starter':<20} {'Final Best':<20} {'Reference':<20}")
    print(f"  {'─'*22} {'─'*20} {'─'*20} {'─'*20}")
    print(f"  {'Lat / Top Int (cyc)':<22} {str(base_lat)+' / '+str(base_ti):<20} {str(best_lat)+' / '+str(best_ti):<20} {str(ref_lat)+' / '+str(ref_ti):<20}")
    print(f"  {'Loop II':<22} {str(base_lii) if base_lii is not None else 'N/A':<20} {str(best_lii) if best_lii is not None else 'N/A':<20} {'N/A':<20}")
    print(f"  {'Clock':<22} {str(base_clk)+' ns' if base_clk else 'N/A':<20} {str(best_clk)+' ns' if best_clk else 'N/A':<20} {str(ref_clk)+' ns' if ref_clk else 'N/A':<20}")
    cosim_gate = state.metadata.get("cosim_gate") or {}
    best_cosim = cosim_gate.get("latency_max")
    print(f"  {'CoSim max latency':<22} {'N/A':<20} {str(best_cosim)+' cyc' if best_cosim is not None else 'N/A':<20} {'N/A':<20}")
    print(f"  {'Power':<22} {'N/A':<20} {'N/A':<20} {'N/A':<20}")
    print(f"  {'Area':<22} {_res_str(base_res):<20} {_res_str(best_res):<20} {_res_str(ref_res):<20}")

    # Ratios: placed below table to avoid column-alignment ambiguity
    def _lat_ratio(cand_lat, anchor_lat):
        if anchor_lat and cand_lat and anchor_lat > 0:
            return f"{cand_lat / anchor_lat:.2f}x"
        return "N/A"

    def _area_ratio(cand_r, anchor_r):
        if anchor_r and cand_r:
            return f"{_total_area(cand_r) / max(_total_area(anchor_r), 1):.2f}x"
        return "N/A"

    best_vs_starter_lat = _lat_ratio(best_lat, base_lat)
    best_vs_starter_area = _area_ratio(best_res, base_res)
    best_vs_ref_lat = _lat_ratio((best_lat or base_lat), ref_lat)
    best_vs_ref_area = _area_ratio((best_res if best_res else base_res), ref_res)

    print(f"  Final Best vs Starter  : latency={best_vs_starter_lat} | area={best_vs_starter_area}")
    if ref_lat:
        print(f"  Final Best vs Reference: latency={best_vs_ref_lat} | area={best_vs_ref_area}")

    # Bottleneck
    if is_v3 and sc.valid:
        bottleneck = sc.bottleneck_resource
        growth_str = ", ".join(
            f"{k}={v:.2f}x" for k, v in sc.growth_by_resource.items()
        ) if sc.growth_by_resource else "N/A"
        print(f"\n  Area bottleneck: {bottleneck} | Growth: {growth_str}")

    # ── SYNTHESIS CANDIDATES ────────────────────────────────────────────
    all_entries = []
    # Baseline
    if baseline_info:
        bl_idx = synth_tx_indices[0] if synth_tx_indices else 2
        label = f"Final Best (#{bl_idx})" if final_is_baseline else f"Baseline (#{bl_idx})"
        all_entries.append((label, baseline_info, baseline_info.get("decision", "BASELINE")))
    # Candidates
    for i, c in enumerate(candidates_info):
        idx = synth_tx_indices[i + 1] if i + 1 < len(synth_tx_indices) else (i + 3)
        qhwb = c.get("q_hw_before")
        qhwa = c.get("q_hw_after")
        decision = c.get("decision", "REJECTED")
        delta_str = f"Q_HW {qhwb:.4f}→{qhwa:.4f}" if (qhwb is not None and qhwa is not None) else ""
        label_prefix = {
            "ACCEPTED": "Accepted",
            "SELECTED": "Selected",
            "VALID_NOT_SELECTED": "Valid",
        }.get(decision, "Rejected")
        strategy = c.get("strategy")
        label = f"{label_prefix} (#{idx})"
        if strategy:
            label = f"{label_prefix}:{strategy[:10]} (#{idx})"
        all_entries.append((label, c, decision))

    if all_entries:
        print(f"\n  {'SYNTHESIS CANDIDATES':─^76}")
        print(f"  {'Candidate':<22} {'Lat / Top Int':<17} {'Loop II':<10} {'Clock':<10} {'Area':<40} {'Decision':<12}")
        print(f"  {'─'*22} {'─'*17} {'─'*10} {'─'*10} {'─'*40} {'─'*12}")
        for label, c, decision in all_entries:
            lat = c.get("latency", "?")
            ti = c.get("top_interval", "?")
            lii = c.get("loop_ii", "?")
            clk = f"{c['clock_ns']} ns" if c.get("clock_ns") else "?"
            res = _res_str(c.get("resources", {}))
            lat_ti = f"{lat} / {ti} cyc"
            lii_str = str(lii) if lii is not None else "?"
            dec_str = {
                "BASELINE": "SELECTED" if final_is_baseline else "BASELINE",
                "ACCEPTED": "ACCEPTED",
                "SELECTED": "SELECTED",
                "VALID_NOT_SELECTED": "VALID",
            }.get(decision, "REJECTED")
            print(f"  {label:<22} {lat_ti:<17} {lii_str:<10} {clk:<10} {res:<40} {dec_str:<12}")

    # ── Loop details ────────────────────────────────────────────────────
    if baseline_info:
        bl_loops = _loop_str(baseline_info.get("loop_metrics", []))
        if bl_loops:
            lbl = f"{'Final Best' if final_is_baseline else 'Baseline'} loops"
            print(f"\n  {lbl}: {bl_loops}")

    for i, c in enumerate(candidates_info):
        if c.get("decision") == "REJECTED":
            cl = _loop_str(c.get("loop_metrics", []))
            if cl:
                print(f"  Rejected candidate R{c.get('round','?')} loops: {cl}")
                break  # only show last rejected

    # ── Trade-off ───────────────────────────────────────────────────────
    if baseline_info and candidates_info:
        last_cand = candidates_info[-1]
        base_l = baseline_info.get("latency")
        cand_l = last_cand.get("latency")
        if base_l and cand_l and base_l > 0:
            lat_diff = cand_l - base_l
            lat_pct = abs(lat_diff) / base_l * 100
            direction = "↓" if lat_diff < 0 else "↑"
            parts = [f"Latency {direction}{abs(lat_diff)} ({lat_pct:.1f}%)"]

            base_r = baseline_info.get("resources", {})
            cand_r = last_cand.get("resources", {})
            for res_key in ("LUT", "FF", "DSP"):
                bv = base_r.get(res_key, 0)
                cv = cand_r.get(res_key, 0)
                if bv != cv and bv > 0:
                    diff = cv - bv
                    pct = abs(diff) / bv * 100
                    arrow = "↓" if diff < 0 else "↑"
                    parts.append(f"{res_key} {arrow}{abs(diff)} ({pct:.1f}%)")
            if parts:
                qhwb = last_cand.get("q_hw_before")
                qhwa = last_cand.get("q_hw_after")
                dec = last_cand.get("decision", "REJECTED")
                if qhwb is not None and qhwa is not None:
                    parts.append(f"Q_HW {qhwb:.4f} → {qhwa:.4f} | {dec}")
                print(f"\n  Trade-off: {' | '.join(parts)}")

    # ── MODEL / TOKEN / COST ────────────────────────────────────────────
    llm = _llm_summary(state)
    print(f"\n  {'MODEL / TOKEN / COST':─^76}")
    if llm is not None:
        usage = llm.get("token_usage")
        model_str = llm.get("model") or llm.get("client") or "?"
        if isinstance(usage, dict):
            requests = usage.get("request_count", 0)
            reported = usage.get("reported_usage_count", 0)
            prompt_t = usage.get("prompt_tokens", 0)
            compl_t = usage.get("completion_tokens", 0)
            total_t = usage.get("total_tokens", 0)
            print(f"  Model={model_str} | API={reported}/{requests} | Prompt={prompt_t} | Completion={compl_t} | Total={total_t} tokens")
        else:
            print(f"  Model={model_str} | API tokens: unavailable")
    csim_times = ", ".join(f"{r.elapsed_s:.1f}s" for r in state.results if r.kind == "csim")
    synth_times = ", ".join(f"{r.elapsed_s:.1f}s" for r in state.results if r.kind == "synth")
    print(f"  Credits={spent}/{total_budget} | CSIM time={csim_times} | Synthesis time={synth_times}")

    # ── OPTIMIZATION TARGETS ────────────────────────────────────────────
    print(f"\n  {'OPTIMIZATION TARGETS':─^76}")
    base_lat_str = f"{base_lat} cyc" if base_lat else "?"
    print(f"  Latency : {base_lat_str} → reduce loop II and loop latency")
    if base_res:
        res_parts = ", ".join(f"{k}={v}" for k, v in base_res.items() if v)
        bt = sc.bottleneck_resource if (is_v3 and sc.valid) else "N/A"
        print(f"  Area    : {res_parts} → {bt} is the current bottleneck")
    print(f"  Power   : N/A → add total, dynamic and static power measurements")
    llm_tokens_val = 0
    if llm is not None and isinstance(llm.get("token_usage"), dict):
        llm_tokens_val = llm["token_usage"].get("total_tokens", 0)
    print(f"  Token   : {llm_tokens_val} → reduce prompt size and unnecessary repeated tool calls")
    wall_s = derived['wall_time_seconds']
    print(f"  Time    : {wall_s:.0f}s wall / {grading_time:.0f}s grading → reduce unsuccessful synthesis iterations")
    print(f"{'='*80}\n")


def print_transcript(state: RunState) -> None:
    """Print the metered tool transcript to stdout."""
    server = state.server
    total = getattr(server.budget, "total", "?")
    print(f"\n=== Tool Transcript ({len(server.transcript)} calls) ===")
    for entry in server.transcript:
        print(f"  #{entry.n:<2} {entry.detail}   [spent {entry.spent}/{total}]")
    summary = getattr(server.budget, "summary", None)
    if callable(summary):
        print(f"  {summary()}")
