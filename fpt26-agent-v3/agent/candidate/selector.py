"""Candidate and anchor selection — accepts only validated candidates."""

from __future__ import annotations

import hashlib
from typing import Any

from agent.candidate.validator import ValidationPlan
from agent.models import CandidateEvaluation, AnchorEvidence


def select_candidate(
    evaluations: list[CandidateEvaluation],
    *,
    plan: ValidationPlan = ValidationPlan.CSIM_SYNTH,
    prefer_lower_latency: bool = True,
) -> tuple[str | None, CandidateEvaluation | None]:
    """Select the best accepted candidate from a list of evaluations.

    Returns (source_sha256, evaluation) or (None, None) if none pass.
    Only candidates whose ``accepted`` is True and who meet *plan* are
    eligible.
    """
    accepted = [e for e in evaluations if e.accepted]
    if not accepted:
        return None, None

    if prefer_lower_latency:
        # Prefer lower synth latency; treat None as very large
        def _key(e: CandidateEvaluation) -> int:
            lat = e.synth_latency
            return lat if lat is not None else 10**12
        best = min(accepted, key=_key)
    else:
        best = accepted[-1]  # last accepted

    return best.source_sha256, best


def select_anchor(
    starter_eval: CandidateEvaluation | None,
    reference_eval: CandidateEvaluation | None,
    *,
    requires_cosim: bool = False,
) -> AnchorEvidence:
    """Choose the best valid anchor (starter preferred, then reference).

    Returns an :class:`AnchorEvidence` recording *why* the choice was made.
    """
    # Try starter first
    if starter_eval is not None and starter_eval.accepted:
        if not requires_cosim or (
            starter_eval.cosim is not None and starter_eval.cosim.ok
        ):
            return AnchorEvidence(
                source="starter", valid=True,
                source_sha256=starter_eval.source_sha256,
                csim_ok=(starter_eval.csim == "pass"),
                synth_ok=(starter_eval.synth == "pass"),
                interface_ok=starter_eval.interface.ok,
                frequency=starter_eval.frequency,
                resource=starter_eval.resource,
                cosim=starter_eval.cosim,
                latency=starter_eval.synth_latency,
                ii=starter_eval.synth_ii,
                clock_ns=starter_eval.synth_clock_ns,
                resources=starter_eval.synth_resources,
                available=dict(starter_eval.resource.available) if starter_eval.resource else {},
            )

    # Fall back to reference
    if reference_eval is not None and reference_eval.accepted:
        return AnchorEvidence(
            source="reference", valid=True,
            source_sha256=reference_eval.source_sha256,
            csim_ok=(reference_eval.csim == "pass"),
            synth_ok=(reference_eval.synth == "pass"),
            interface_ok=reference_eval.interface.ok,
            frequency=reference_eval.frequency,
            resource=reference_eval.resource,
            cosim=reference_eval.cosim,
            latency=reference_eval.synth_latency,
            ii=reference_eval.synth_ii,
            clock_ns=reference_eval.synth_clock_ns,
            resources=reference_eval.synth_resources,
            available=dict(reference_eval.resource.available) if reference_eval.resource else {},
        )

    # No valid anchor
    failure = ""
    if starter_eval is not None:
        failure = f"starter: {starter_eval.failure_reason}"
    if reference_eval is not None and not failure:
        failure = f"reference: {reference_eval.failure_reason}"
    return AnchorEvidence(source="none", valid=False, failure_reason=failure or "no valid anchor")
