"""Derived metrics, toolchain evidence, and execution trace builders.

Extracted from _legacy.py.  Builder and other modules import from here,
NOT from _legacy.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from agent.agents.base import RunState


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
        "client": getattr(
            client, "backend_client_name", type(client).__name__
        ),
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
# Display helpers (used by _legacy.print_evaluation)
# ---------------------------------------------------------------------------


def _synth_info(result: Any) -> dict[str, Any] | None:
    """Normalize one successful synthesis result for console comparison."""
    report = getattr(result, "report", None)
    if not getattr(result, "ok", False) or report is None:
        return None
    loops = [dict(item) for item in (report.loop_metrics or [])]
    return {
        "latency": report.latency_worst or report.latency_avg,
        "top_interval": report.interval_max,
        "loop_ii": loops[0].get("pipeline_ii") if loops else None,
        "clock_ns": report.clock_period_ns,
        "resources": dict(report.resources),
        "loop_metrics": loops,
    }


def _grading_synth_info(state: Any, stage: str) -> dict[str, Any] | None:
    """Find a named evaluator-side synthesis without confusing it with agent tools."""
    for recorded_stage, result in state.metadata.get("grading_results", []):
        if recorded_stage == stage:
            return _synth_info(result)
    return None


def _final_synth_info(state: Any) -> dict[str, Any] | None:
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
            "loop_ii": loops[0].get("pipeline_ii") if loops else None,
            "clock_ns": metrics.get("clock_period_ns"),
            "resources": dict(metrics.get("resources") or {}),
            "loop_metrics": loops,
        }
    return _grading_synth_info(state, "candidate_synth")
