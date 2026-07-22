"""Pipeline stage functions extracted from workflow.py.

These are compatibility delegates.  New code should use CandidateValidator
and the scoring/evaluator modules directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def step_finalize(state: Any) -> Any:
    """Persist the final kernel and derive the truthful terminal status."""
    if not isinstance(getattr(state, "metadata", None), dict):
        state.metadata = {}
    if getattr(state, "last_verified_kernel", None) is not None:
        state.kernel = state.last_verified_kernel
    elif (state.status in ("failed", "budget_exceeded", "infrastructure_error")
          and getattr(state, "safe_fallback_kernel", None) is not None):
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


def step_public_acceptance(state: Any) -> Any:
    """Fold public correctness and target gates into one truthful terminal gate."""
    failures: list[str] = []
    if not state.interface_ok:
        failures.append("interface_failed")
    if not state.csim_ok:
        failures.append("csim_failed")
    if not state.synth_ok:
        failures.append("synth_failed")
    if not state.frequency_ok:
        failures.append(str((state.metadata.get("frequency_gate") or {}).get("reason", "frequency_failed")))
    if not state.resource_ok:
        failures.append(str((state.metadata.get("resource_gate") or {}).get("reason", "resource_failed")))
    if state.task.requires_cosim and not state.cosim_ok:
        failures.append("cosim_failed")
    if failures:
        state.status = "failed"
        state.stop_reason = failures[0]
        state.metadata["public_acceptance"] = {"ok": False, "failures": failures}
        return state
    from agent.candidate.validator import _mark_fully_verified
    _mark_fully_verified(state)
    state.status = "completed"
    state.stop_reason = ""
    state.metadata["public_acceptance"] = {"ok": True, "failures": []}
    return state
