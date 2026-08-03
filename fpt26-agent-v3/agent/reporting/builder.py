"""Report builder — constructs the run report dict from RunState.

Extracted from ``_legacy.write_run_report``.  This module owns report
construction; file I/O is handled by ``writer.py``.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


def build_report(state: Any) -> dict[str, Any]:
    """Build the complete run report dict from a terminal RunState.

    Returns a dict suitable for JSON serialisation.  Does NOT write to disk.
    """
    from agent.reporting.metrics import (
        _compute_derived, _llm_summary, _reported_cosim_status,
        _toolchain_evidence, _execution_trace,
    )

    derived = _compute_derived(state)
    sc = state.scorecard
    rsc = getattr(state, 'ref_scorecard', None)
    is_v3 = sc is not None and hasattr(sc, 'schema_version') and getattr(sc, 'schema_version', 0) >= 5

    report: dict[str, Any] = {
        "schema_version": 1,
        "task_id": state.task.id,
        "task_type": state.task.type,
        "task_difficulty": state.task.difficulty,
        "run_role": getattr(state.config, "run_role", state.metadata.get("run_role")),
        "mode": state.config.mode,
        "scoring_profile": getattr(state.config, "scoring_profile", "balanced"),
        "competition": state.config.competition,
        "status": state.status,
        "status_vocabulary": ["running", "completed", "failed", "budget_exceeded", "infrastructure_error"],
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
        "candidate_validation_history": state.metadata.get("interface_validations", []),
        "synthesis_gate_history": state.metadata.get("synth_gate_history", []),
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
            "is_fallback": state.metadata.get("grading_source") in {"public_fallback", "proxy_grading"},
        },
        "model_compliance": state.metadata.get("model_compliance"),
        "best_latency": state.best_latency,
        "stop_reason": state.stop_reason,
        "tool_call_count": len(state.results),
        "budget": {
            "total": getattr(state.server.budget, "total", None),
            "spent": getattr(state.server.budget, "spent", None),
        },
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
    optimization_keys = (
        "qor_rag_mode",
        "knowledge_retrievals",
        "synth_candidates",
        "best_q_hw",
        "optimization_failures",
        "semantic_duplicate_skips",
        "semantic_current_best_skips",
        "anti_repeat_action_rejections",
        "report_evidence_action_rejections",
        "report_supported_convergence",
        "optimization_convergence_reason",
        "action_guard_rejection_reasons",
        "measured_rejected_actions",
        "cross_strategy_duplicate_skips",
        "strategy_contract_rejections",
        "ii_resource_intent_rejections",
        "structured_bottleneck_diagnostics_enabled",
        "bottleneck_diagnostics",
        "bottleneck_action_alignment",
    )
    if any(key in state.metadata for key in optimization_keys):
        report["optimization_metrics"] = {
            key: state.metadata.get(key)
            for key in optimization_keys
            if key in state.metadata
        }
    if getattr(state, "metadata", {}).get("optimization_search"):
        report["optimization_search"] = state.metadata["optimization_search"]

    if state.scorecard is not None:
        if is_v3:
            report["scoring"] = _build_v3_scoring(sc)
            if rsc is not None:
                report["scoring_vs_reference"] = _build_v3_reference(rsc)
        else:
            report["scoring"] = {
                "score": sc.score, "score_max": getattr(sc, 'difficulty', 1),
                "score_pct": round(sc.score / max(getattr(sc, 'difficulty', 1), 1) * 100, 1),
                "functional_pass": getattr(sc, 'functional_pass', None),
                "synth_pass": getattr(sc, 'synth_pass', None),
                "cosim_pass": getattr(sc, 'cosim_pass', None),
                "baseline_latency": getattr(sc, 'baseline_latency', None),
                "candidate_latency": getattr(sc, 'candidate_latency', None),
                "acceleration": getattr(sc, 'acceleration', None),
                "is_opt": getattr(sc, 'is_opt', None),
            }

    return report


def _build_v3_scoring(sc: Any) -> dict[str, Any]:
    """Build V3 scoring block."""
    return {
        "schema_version": sc.schema_version,
        "scoring_profile": getattr(sc, "scoring_profile", "balanced"),
        "performance_weight": getattr(sc, "performance_weight", 0.55),
        "area_weight": getattr(sc, "area_weight", 0.45),
        "area_reward_capped": getattr(sc, "area_reward_capped", False),
        "score": sc.score, "score_max": sc.score_max,
        "score_pct": round(sc.score / max(sc.score_max, 1) * 100, 1),
        "valid": sc.valid, "gate_reason": sc.gate_reason,
        "csim_pass": sc.csim_pass, "synth_pass": sc.synth_pass,
        "cosim_pass": sc.cosim_pass,
        "resource_capacity_pass": getattr(sc, "resource_capacity_pass", None),
        "anchor_source": sc.anchor_source,
        "latency_ratio": sc.latency_ratio,
        "acceleration_source": getattr(sc, "acceleration_source", "synth"),
        "cosim_latency_used": getattr(sc, "cosim_latency_used", None),
        "performance_ratio": getattr(sc, "performance_ratio", sc.latency_ratio),
        "area_growth": sc.area_growth,
        "area_ratio": getattr(sc, "area_ratio", 1.0 / max(sc.area_growth, 1e-9)),
        "effective_area_ratio": getattr(sc, "effective_area_ratio", getattr(sc, "area_ratio", 1.0 / max(sc.area_growth, 1e-9))),
        "bottleneck_resource": sc.bottleneck_resource,
        "q_perf": sc.q_perf, "q_area": sc.q_area,
        "anchor_resource_footprint": getattr(sc, "anchor_resource_footprint", None),
        "candidate_resource_footprint": getattr(sc, "candidate_resource_footprint", None),
        "base_hardware_ratio": getattr(sc, "base_hardware_ratio", None),
        "source_changed": getattr(sc, "source_changed", False),
        "validity_rescue": getattr(sc, "validity_rescue", False),
        "source_change_multiplier": getattr(sc, "source_change_multiplier", 1.0),
        "validity_rescue_multiplier": getattr(sc, "validity_rescue_multiplier", 1.0),
        "hardware_ratio": getattr(sc, "hardware_ratio", None), "q_hw": sc.q_hw,
        "efficiency": sc.efficiency,
        "growth_by_resource": sc.growth_by_resource,
        "baseline_resources": sc.baseline_resources,
        "candidate_resources": sc.candidate_resources,
        "available_resources": getattr(sc, "available_resources", {}),
        "cost_spent": sc.cost_spent, "cost_limit": sc.cost_limit,
        "wall_time_s": sc.wall_time_s, "time_limit_s": sc.time_limit_s,
    }


def _build_v3_reference(rsc: Any) -> dict[str, Any]:
    """Build reference-anchored scorecard block."""
    return {
        "anchor": "reference",
        "scoring_profile": getattr(rsc, "scoring_profile", "balanced"),
        "performance_weight": getattr(rsc, "performance_weight", 0.55),
        "area_weight": getattr(rsc, "area_weight", 0.45),
        "area_reward_capped": getattr(rsc, "area_reward_capped", False),
        "score": rsc.score,
        "score_pct": round(rsc.score / max(rsc.score_max, 1) * 100, 1),
        "valid": rsc.valid, "q_hw": rsc.q_hw,
        "q_perf": rsc.q_perf, "q_area": rsc.q_area,
        "latency_ratio": rsc.latency_ratio, "area_growth": rsc.area_growth,
        "area_ratio": getattr(rsc, "area_ratio", 1.0 / max(rsc.area_growth, 1e-9)),
        "effective_area_ratio": getattr(rsc, "effective_area_ratio",
                                        getattr(rsc, "area_ratio", 1.0 / max(rsc.area_growth, 1e-9))),
        "hardware_ratio": getattr(rsc, "hardware_ratio", None),
        "base_hardware_ratio": getattr(rsc, "base_hardware_ratio", None),
        "anchor_resource_footprint": getattr(rsc, "anchor_resource_footprint", None),
        "candidate_resource_footprint": getattr(rsc, "candidate_resource_footprint", None),
        "source_changed": getattr(rsc, "source_changed", False),
        "validity_rescue": getattr(rsc, "validity_rescue", False),
        "source_change_multiplier": getattr(rsc, "source_change_multiplier", 1.0),
        "validity_rescue_multiplier": getattr(rsc, "validity_rescue_multiplier", 1.0),
        "efficiency": rsc.efficiency,
        "bottleneck_resource": rsc.bottleneck_resource,
        "reference_latency": rsc.anchor_latency, "reference_ii": rsc.anchor_ii,
        "reference_clock_ns": rsc.anchor_clock_ns,
        "reference_resources": rsc.baseline_resources,
        "candidate_resources": rsc.candidate_resources,
        "growth_by_resource": rsc.growth_by_resource,
    }
