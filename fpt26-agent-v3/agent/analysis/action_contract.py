"""Translate measured HLS diagnostics into bounded optimization actions."""
from __future__ import annotations

from typing import Any

from agent.analysis.synth_diagnostics import extract_ii_resource_limits


def build_ii_resource_action_contract(log_text: str) -> dict[str, Any] | None:
    """Build a prompt contract from Vitis HLS 200-448 evidence.

    The contract deliberately recommends only the smallest evidence-matched
    experiment.  It does not decide an array dimension because that requires
    inspecting the source access pattern; an unsupported trial must not be
    guessed into the kernel.
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
                "recommended_minimal_trial": {
                    "pragma_class": "ARRAY_PARTITION",
                    "variable": limit.array,
                    "style": "cyclic",
                    "factor": 2,
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
            "Use exactly one minimal action that changes bandwidth or read "
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
            "show another measured benefit; scoring_v3 V8 Q_HW must exceed "
            "the current best after clock and resources are included."
        ),
    }
