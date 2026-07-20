"""Pipeline context, status, and unified termination rules."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from agent.models import RunStatus


class PipelinePhase(str, Enum):
    INIT = "init"
    BASELINE = "baseline"
    REPAIR = "repair"
    STRUCTURAL = "structural"
    OPTIMIZE = "optimize"
    SCORING = "scoring"
    FINALIZE = "finalize"


class StopReason(str, Enum):
    NONE = ""
    COMPLETED = "completed"
    CSIM_FAILED = "csim_failed"
    SYNTH_FAILED = "synth_failed"
    COSIM_FAILED = "cosim_failed"
    INTERFACE_FAILED = "interface_failed"
    FREQUENCY_FAILED = "frequency_failed"
    RESOURCE_FAILED = "resource_failed"
    BUDGET_EXCEEDED = "budget_exceeded"
    TIMEOUT = "timeout"
    INFRA_ERROR = "infrastructure_error"
    EVIDENCE_INVALID = "evidence_invalid"
    ANCHOR_INVALID = "anchor_invalid"
    SCORING_INVALID = "scoring_invalid"


@dataclass
class PipelineContext:
    """Structured context that flows through every pipeline phase.

    Replaces the ad-hoc ``metadata`` dict and string-based status tracking
    with typed, serialisable fields.
    """

    task_id: str = ""
    run_role: str = "submission"     # "submission" | "evaluator"
    mode: str = "auto"

    # ── terminal status ──────────────────────────────────────────────────
    status: str = RunStatus.RUNNING.value
    stop_reason: str = StopReason.NONE.value
    current_phase: str = PipelinePhase.INIT.value

    # ── kernel state ─────────────────────────────────────────────────────
    kernel: str = ""
    safe_fallback_kernel: str = ""
    last_verified_kernel: str | None = None

    # ── gate results ─────────────────────────────────────────────────────
    interface_ok: bool = False
    csim_ok: bool = False
    synth_ok: bool = False
    cosim_ok: bool = False
    frequency_ok: bool = False
    resource_ok: bool = False

    # ── budget & timing ──────────────────────────────────────────────────
    credits_total: int = 0
    credits_spent: int = 0
    started_at: float = field(default_factory=time.monotonic)
    deadline_s: float = 3600.0

    # ── scoring ──────────────────────────────────────────────────────────
    scoring_profile: str = "balanced"
    scorecard: Any = None
    ref_scorecard: Any = None

    # ── dependencies (injected) ──────────────────────────────────────────
    task: Any = None
    tool_executor: Any = None
    llm_client: Any = None

    # ── structured metadata (migrated from ad-hoc dict) ──────────────────
    interface_validations: list[dict[str, Any]] = field(default_factory=list)
    synth_gate_history: list[dict[str, Any]] = field(default_factory=list)
    cosim_gate_history: list[dict[str, Any]] = field(default_factory=list)
    grading_results: list[Any] = field(default_factory=list)
    model_compliance: dict[str, Any] = field(default_factory=dict)
    task_preflight: dict[str, Any] = field(default_factory=dict)
    optimization_search: dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def is_terminal(self) -> bool:
        return self.status != RunStatus.RUNNING.value

    def terminate(self, status: str, reason: str) -> None:
        """Set terminal status and stop reason (idempotent)."""
        if self.is_terminal:
            return
        self.status = status
        self.stop_reason = reason

    def fail_if(self, condition: bool, status: str, reason: str) -> bool:
        """If *condition* is True, set terminal status and return True."""
        if condition:
            self.terminate(status, reason)
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "run_role": self.run_role,
            "mode": self.mode,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "current_phase": self.current_phase,
            "interface_ok": self.interface_ok,
            "csim_ok": self.csim_ok,
            "synth_ok": self.synth_ok,
            "cosim_ok": self.cosim_ok,
            "frequency_ok": self.frequency_ok,
            "resource_ok": self.resource_ok,
            "credits_total": self.credits_total,
            "credits_spent": self.credits_spent,
            "elapsed_s": self.elapsed_s,
            "scoring_profile": self.scoring_profile,
        }
