"""Translate measured HLS diagnostics into bounded optimization actions."""
from __future__ import annotations

from typing import Any

from agent.analysis.synth_diagnostics import extract_ii_resource_limits


_CAUSE_FAMILIES: dict[str, tuple[str, ...]] = {
    "memory_port": ("MEMORY_BANKING", "SOURCE_RESTRUCTURE"),
    "carried_dependency": ("SOURCE_RESTRUCTURE",),
    "shared_resource_conflict": ("SOURCE_RESTRUCTURE",),
    "timing_critical_path": (
        "PIPELINE",
        "RESOURCE_BINDING",
        "SOURCE_RESTRUCTURE",
    ),
    "serial_loop_latency": ("LOOP_UNROLL", "SOURCE_RESTRUCTURE"),
    "pipeline_structure": ("LOOP_UNROLL", "SOURCE_RESTRUCTURE"),
    "variable_trip_count": ("SOURCE_RESTRUCTURE",),
    "dataflow_noncanonical": ("DATAFLOW", "SOURCE_RESTRUCTURE"),
    "stream_depth_risk": ("STREAM", "DATAFLOW", "SOURCE_RESTRUCTURE"),
    "rewind_dependency": ("SOURCE_RESTRUCTURE",),
    "rewind_synchronization": ("SOURCE_RESTRUCTURE",),
    "m_axi_widening_limit": ("INTERFACE", "SOURCE_RESTRUCTURE"),
    "m_axi_conditional_access": ("SOURCE_RESTRUCTURE",),
    "m_axi_alignment_limit": ("INTERFACE", "SOURCE_RESTRUCTURE"),
    "m_axi_width_mismatch": ("INTERFACE", "SOURCE_RESTRUCTURE"),
    "m_axi_bundle_write_conflict": ("INTERFACE", "SOURCE_RESTRUCTURE"),
}


def build_bottleneck_action_contract(
    diagnosis: Any,
) -> dict[str, Any]:
    """Turn one evidence-backed category into a bounded planning contract.

    This contract proposes a search space, not a mandatory edit.  Source-level
    preconditions remain explicit and every proposed trial must be measured.
    """

    primary = diagnosis.primary
    diagnostic_state = str(
        getattr(diagnosis, "diagnostic_state", "") or "unknown"
    )
    families = _CAUSE_FAMILIES.get(primary.cause, ())
    actionable = bool(families) and primary.confidence != "unknown"
    if diagnostic_state in {
        "synthesis_failed",
        "insufficient_artifacts",
        "no_confirmed_bottleneck",
        "unresolved_bottleneck_cause",
    }:
        actionable = False

    return {
        "kind": "diagnosis_guided_optimization",
        "diagnostic_state": diagnostic_state,
        "cause": primary.cause,
        "confidence": primary.confidence,
        "target": dict(primary.target),
        "actionable": actionable,
        "candidate_families": list(families) if actionable else [],
        "candidate_schemes": (
            list(primary.allowed_actions) if actionable else []
        ),
        "required_preconditions": list(primary.missing_evidence),
        "forbidden_actions": list(primary.forbidden_actions),
        "selection_rule": (
            "Inspect the editable source, select at most one listed family whose "
            "preconditions are proved, and otherwise keep the kernel unchanged."
            if actionable
            else "Do not propose an optimization until the required evidence is available."
        ),
        "verification": list(primary.expected_validation_signals),
    }


def build_ii_resource_action_contract(log_text: str) -> dict[str, Any] | None:
    """Build a prompt contract from Vitis HLS 200-448 evidence.

    The contract records the measured II lower bound as a soft search hint.
    It does not decide an array dimension, banking style, or mandatory factor
    because those require inspecting the source access pattern; an unsupported
    trial must not be guessed into the kernel.
    """
    limits = [
        limit
        for limit in extract_ii_resource_limits(log_text)
        if limit.array
    ][:3]
    if not limits:
        return None

    targets = []
    for limit in limits:
        targets.append(
            {
                "array": limit.array,
                "operation": limit.operation,
                "observed_ii_lower_bound": limit.lower_bound,
                "source": limit.source,
                "candidate_parameter_space": {
                    "pragma_classes": [
                        "ARRAY_PARTITION",
                        "ARRAY_RESHAPE",
                    ],
                    "variable": limit.array,
                    "partition_type": "derive_from_source_bank_mapping",
                    "factor_policy": (
                        "Derive candidate factors from the number and affine "
                        "mapping of concurrent accesses. The observed II lower "
                        "bound describes the bottleneck and is not a factor."
                    ),
                    "dimension_policy": (
                        "Choose only the dimension indexed by concurrent loop "
                        "iterations. Omit this trial when the source does not "
                        "prove that dimension."
                    ),
                },
                "code_alternative": (
                    f"Create local reuse/buffering that reduces repeated reads "
                    f"from {limit.array}; preserve the top signature."
                ),
            }
        )

    arrays = [target["array"] for target in targets]
    return {
        "kind": "measured_memory_port_ii",
        "evidence_id": "HLS 200-448",
        "targets": targets,
        "required_candidate_delta": (
            "Use exactly one evidence-matched action that changes bandwidth or read "
            f"reuse for a reported target {arrays}; otherwise return the "
            "current editable kernel unchanged."
        ),
        "forbidden_as_non_responsive": [
            "standalone PIPELINE or UNROLL",
            "ARRAY_PARTITION or ARRAY_RESHAPE on an unreported array",
            "multiple speculative pragma classes",
        ],
        "verification": (
            "Candidate C-sim must pass; synthesis must lower the target II or "
            "show another measured benefit; scoring_v3 schema 11 Q_HW must exceed "
            "the current best after clock and resources are included."
        ),
    }


def augment_action_contract_with_source_architecture(
    contract: dict[str, Any] | None,
    architecture_evidence: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Fuse deterministic source opportunities into a diagnostic contract.

    Synthesis messages describe scheduling symptoms but do not always expose
    task-level concurrency already visible in the editable source.  This
    function preserves the original diagnostic evidence and adds only source-
    proven families; it never selects an action or a parameter for the model.
    """

    usable = [
        dict(item)
        for item in architecture_evidence
        if isinstance(item, dict)
        and item.get("kind")
        and item.get("candidate_families")
    ]
    if not usable:
        return contract
    merged = dict(contract or {})
    original_kind = str(merged.get("kind") or "none")
    families = {
        str(value)
        for value in merged.get("candidate_families", [])
        if str(value)
    }
    for item in usable:
        families.update(
            str(value)
            for value in item.get("candidate_families", [])
            if str(value)
        )
    merged.update(
        {
            "kind": "evidence_fused_optimization",
            "original_contract_kind": original_kind,
            "actionable": True,
            "candidate_families": sorted(families),
            "source_architecture_evidence": usable[:4],
            "selection_rule": (
                "Choose one candidate family supported by either the measured "
                "diagnostic or source architecture evidence. TASK_PIPELINE is "
                "one coherent family even when its implementation needs "
                "DATAFLOW plus stage-boundary/pipeline directives. Measure the "
                "candidate and retain it only when scoring_v3 Q_HW improves. "
                "Likewise, an evidence-declared REDUCTION_PARALLELISM family "
                "may combine its listed source rewrite, input banking, and "
                "loop scheduling members using only a listed factor."
            ),
        }
    )
    return merged
