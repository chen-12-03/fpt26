"""II resource intent feedback — rejects pragma-only actions that ignore measured port limits.

Pure function extracted from OptimizeAgent.  Does NOT call tools or modify state.
"""

from __future__ import annotations

import re
from typing import Any

from agent.analysis.action_contract import build_ii_resource_action_contract
from agent.analysis.synth_diagnostics import extract_ii_resource_limits
from agent.agents.optimization.strategies import (
    _hls_pragmas, _source_array_rank, _without_hls_pragmas_fingerprint,
)


def ii_resource_intent_feedback(
    synth_result: Any,
    best: str,
    candidate: str,
    action_contract: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Reject pragma-only actions that cannot resolve a measured port limit."""
    limits = extract_ii_resource_limits(getattr(synth_result, "log", "") or "")
    if not limits or _without_hls_pragmas_fingerprint(best) != _without_hls_pragmas_fingerprint(candidate):
        return None

    best_pragmas = {p.lower() for p in _hls_pragmas(best)}
    added_pragmas = [p for p in _hls_pragmas(candidate) if p.lower() not in best_pragmas]
    if not added_pragmas:
        return None

    evidence_arrays = {limit.array.lower() for limit in limits if limit.array}
    banking_actions: list[dict[str, Any]] = []
    recognized_only = True
    for pragma in added_pragmas:
        banking = re.search(r"\b(ARRAY_PARTITION|ARRAY_RESHAPE)\b.*?\bvariable\s*=\s*([A-Za-z_]\w*)", pragma, re.IGNORECASE)
        if banking:
            style = re.search(r"\b(cyclic|block|complete)\b", pragma, re.IGNORECASE)
            factor = re.search(r"\bfactor\s*=\s*(\d+)", pragma, re.IGNORECASE)
            dimension = re.search(r"\bdim\s*=\s*(\d+)", pragma, re.IGNORECASE)
            banking_actions.append({
                "pragma": pragma, "pragma_class": banking.group(1).upper(),
                "variable": banking.group(2),
                "style": style.group(1).lower() if style else None,
                "factor": int(factor.group(1)) if factor else None,
                "dimension": int(dimension.group(1)) if dimension else None,
            })
            continue
        if re.search(r"\b(?:PIPELINE|UNROLL)\b", pragma, re.IGNORECASE):
            continue
        recognized_only = False
        break

    if not recognized_only:
        return None

    contract = action_contract or build_ii_resource_action_contract(getattr(synth_result, "log", "") or "")
    contract_violations: list[str] = []
    if contract:
        if len(added_pragmas) != 1:
            contract_violations.append("expected exactly one newly added HLS pragma")
        if len(banking_actions) != 1:
            contract_violations.append(
                "the single action must be ARRAY_PARTITION or ARRAY_RESHAPE"
            )
        else:
            action = banking_actions[0]
            variable = action["variable"]
            rank = _source_array_rank(best, variable)
            if action["pragma_class"] not in {
                "ARRAY_PARTITION",
                "ARRAY_RESHAPE",
            }:
                contract_violations.append(
                    "pragma class must be ARRAY_PARTITION or ARRAY_RESHAPE"
                )
            if variable.lower() not in evidence_arrays:
                contract_violations.append(f"variable '{variable}' is not a reported target")
            if action["style"] not in {"cyclic", "block", "complete"}:
                contract_violations.append(
                    "partition style must be explicit: cyclic, block, or complete"
                )
            if action["style"] == "complete":
                if action["factor"] is not None:
                    contract_violations.append(
                        "complete partition must omit factor"
                    )
            elif action["factor"] is None or action["factor"] < 2:
                contract_violations.append(
                    "partial partition requires a finite factor >=2"
                )
            dimension = action["dimension"]
            if dimension is None:
                contract_violations.append("partition dim must be explicit and source-supported")
            elif dimension < 1:
                contract_violations.append("partition dim must be positive")
            elif rank is not None and dimension > rank:
                contract_violations.append(f"partition dim={dimension} exceeds visible array rank={rank}")
        if not contract_violations:
            return None
    elif any(action["variable"].lower() in evidence_arrays for action in banking_actions):
        return None

    evidence = [{"message_id": "HLS 200-448", "ii_lower_bound": limit.lower_bound,
                  "operation": limit.operation, "array": limit.array,
                  "source": limit.source, "core": limit.core} for limit in limits[:3]]
    arrays = [limit.array for limit in limits if limit.array]
    return {
        "status": "REJECTED_BY_SYNTH_EVIDENCE_INTENT",
        "candidate_pragmas": added_pragmas,
        "unmatched_banking_variables": [a["variable"] for a in banking_actions
                                        if a["variable"].lower() not in evidence_arrays],
        "contract_violations": contract_violations,
        "ii_resource_limits": evidence,
        "reason": (
            "The candidate changes only concurrency directives and/or banks "
            "arrays other than the one named by Vitis HLS 200-448. Vitis "
            "already proved which memory ports set the II lower bound, so this "
            "action does not address the measured bottleneck. No candidate "
            "tool was run."
        ),
        "required_next_action": (
            f"Apply exactly one evidence-matched ARRAY_PARTITION or "
            f"ARRAY_RESHAPE to reported "
            f"array(s) {arrays}, with an explicit source-supported dimension "
            "and a cyclic/block/complete mapping justified by its accesses; or make "
            "a real code-locality change such as a line buffer/cache that "
            "reduces external reads. Otherwise return the current editable "
            "kernel unchanged to stop."
        ),
    }
