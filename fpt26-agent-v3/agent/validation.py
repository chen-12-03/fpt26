"""Backward-compatibility re-exports from ``agent.candidate.validator``.

All business rules live in ``agent.candidate.validator`` — the single
authoritative module.  This module exists only so that existing imports
continue to work without changes.

**Important**: ``CandidateValidator`` here is the **interface-only** validator
(``InterfaceValidator`` in the canonical module).  Callers that need the
full-gate validator (CSim/Synth/CoSim) MUST import ``CandidateValidator``
from ``agent.candidate.validator`` directly.
"""

from __future__ import annotations

# Interface contract types
from agent.candidate.validator import (
    InterfaceContract,
    CandidateValidation,
    FrequencyGate,
    ResourceGate,
)

# ── CandidateValidator = InterfaceValidator (backward compat) ───────────
# Old code calls ``CandidateValidator.from_task(task).validate(code)`` and
# expects a ``CandidateValidation`` with ``.ok``.  The interface-only
# ``InterfaceValidator`` preserves that contract exactly.
from agent.candidate.validator import (
    InterfaceValidator as CandidateValidator,
    ValidationPlan,
)

# The full-gate validator is available under a distinct name
from agent.candidate.validator import (
    CandidateValidator as FullCandidateValidator,
)

# Gate functions
from agent.candidate.validator import (
    frequency_gate,
    resource_gate,
    validation_cost,
    can_afford_validation,
)

# Code extraction
from agent.candidate.validator import extract_code

# State-recording helpers (deprecated — use FullCandidateValidator directly)
from agent.candidate.validator import (
    validate_candidate,
    record_synth_gates,
    record_cosim_gate,
    mark_fully_verified,
)

__all__ = [
    "InterfaceContract",
    "CandidateValidation",
    "FrequencyGate",
    "ResourceGate",
    "CandidateValidator",       # InterfaceValidator for backward compat
    "FullCandidateValidator",   # the real full-gate validator
    "ValidationPlan",
    "frequency_gate",
    "resource_gate",
    "validation_cost",
    "can_afford_validation",
    "extract_code",
    "validate_candidate",
    "record_synth_gates",
    "record_cosim_gate",
    "mark_fully_verified",
]
