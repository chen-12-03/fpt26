"""Public data models for state, evidence, gates, and artifacts.

These models are serialisable, carry explicit schema versions, and distinguish
"unknown / not applicable" from the numeric value 0.  They are the single source
of truth for fields that cross process or module boundaries (submission →
evaluator, agent → report).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from agent.errors import DigestMismatchError, EvidenceError, MissingEvidenceError


# ═══════════════════════════════════════════════════════════════════════════════
# Status vocabulary
# ═══════════════════════════════════════════════════════════════════════════════

class RunStatus(str, Enum):
    """Canonical terminal statuses.  ``RUNNING`` is only valid mid-pipeline."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BUDGET_EXCEEDED = "budget_exceeded"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


class GateResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    NOT_RUN = "not_run"


# ═══════════════════════════════════════════════════════════════════════════════
# Gate evidence (deterministic)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class InterfaceGateEvidence:
    """Evidence from the deterministic public interface / source contract gate."""

    ok: bool
    reason: str | None = None
    fingerprint: str | None = None
    canonical_signature: str | None = None
    required_includes_present: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "fingerprint": self.fingerprint,
            "canonical_signature": self.canonical_signature,
            "required_includes_present": self.required_includes_present,
        }


@dataclass(frozen=True)
class FrequencyGateEvidence:
    """Evidence from the mandatory 100 MHz timing gate."""

    ok: bool
    reason: str | None = None
    target_clock_ns: float | None = None
    candidate_clock_ns: float | None = None
    frequency_mhz: float | None = None
    minimum_frequency_mhz: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "target_clock_ns": self.target_clock_ns,
            "candidate_clock_ns": self.candidate_clock_ns,
            "frequency_mhz": self.frequency_mhz,
            "minimum_frequency_mhz": self.minimum_frequency_mhz,
        }


@dataclass(frozen=True)
class ResourceGateEvidence:
    """Evidence from the device-capacity gate."""

    ok: bool
    reason: str | None = None
    resources: dict[str, int] = field(default_factory=dict)
    available: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "resources": dict(self.resources),
            "available": dict(self.available),
        }


@dataclass(frozen=True)
class CoSimGateEvidence:
    """Evidence from the required C/RTL co-simulation gate."""

    ok: bool
    phase: str | None = None
    source_sha256: str | None = None
    latency_min: int | None = None
    latency_avg: int | None = None
    latency_max: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "phase": self.phase,
            "source_sha256": self.source_sha256,
            "latency_min": self.latency_min,
            "latency_avg": self.latency_avg,
            "latency_max": self.latency_max,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Candidate evaluation
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CandidateEvaluation:
    """Complete public-gate evaluation of one candidate kernel."""

    source_sha256: str
    interface: InterfaceGateEvidence = field(
        default_factory=lambda: InterfaceGateEvidence(ok=False)
    )
    csim: GateResult = GateResult.NOT_RUN
    synth: GateResult = GateResult.NOT_RUN
    frequency: FrequencyGateEvidence | None = None
    resource: ResourceGateEvidence | None = None
    cosim: CoSimGateEvidence | None = None
    stage: str = ""
    accepted: bool = False
    failure_reason: str = ""
    elapsed_s: float = 0.0
    # Synth PPA (populated when synth passes)
    synth_latency: int | None = None
    synth_ii: int | None = None
    synth_clock_ns: float | None = None
    synth_resources: dict[str, int] = field(default_factory=dict)

    def fail(self, reason: str) -> None:
        self.accepted = False
        self.failure_reason = reason

    def to_dict(self) -> dict[str, Any]:
        csim_val = self.csim.value if isinstance(self.csim, GateResult) else self.csim
        synth_val = self.synth.value if isinstance(self.synth, GateResult) else self.synth
        return {
            "source_sha256": self.source_sha256,
            "interface": self.interface.to_dict(),
            "csim": csim_val,
            "synth": synth_val,
            "frequency": self.frequency.to_dict() if self.frequency else None,
            "resource": self.resource.to_dict() if self.resource else None,
            "cosim": self.cosim.to_dict() if self.cosim else None,
            "stage": self.stage,
            "accepted": self.accepted,
            "failure_reason": self.failure_reason,
            "elapsed_s": self.elapsed_s,
            "synth_latency": self.synth_latency,
            "synth_ii": self.synth_ii,
            "synth_clock_ns": self.synth_clock_ns,
            "synth_resources": dict(self.synth_resources),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Error record
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ErrorRecord:
    """Serialisable record of an infrastructure or pipeline error."""

    error_type: str
    message: str
    step: str = ""
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "error_type": self.error_type,
            "message": self.message,
            "step": self.step,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Artifact manifest (immutable record of what was produced)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ArtifactManifest:
    """Immutable record of a persisted artifact."""

    path: str
    sha256: str
    role: str = "unknown"           # "kernel" | "report" | "evidence"
    fully_verified: bool = False
    fallback_starter_used: bool = False
    schema_version: int = 1

    @classmethod
    def from_path(cls, path: str, *, role: str = "kernel") -> "ArtifactManifest":
        """Create a manifest by reading and hashing the file at *path*."""
        from pathlib import Path

        fp = Path(path)
        if not fp.is_file():
            raise FileNotFoundError(f"artifact not found: {path}")
        sha256 = hashlib.sha256(fp.read_bytes()).hexdigest()
        return cls(path=path, sha256=sha256, role=role)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "path": self.path,
            "sha256": self.sha256,
            "role": self.role,
            "fully_verified": self.fully_verified,
            "fallback_starter_used": self.fallback_starter_used,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Evaluation accounting — the single source of truth for cost and time
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EvaluationAccounting:
    """Complete cost/time accounting for a graded evaluation.

    This is the **business source of truth** for scoring.  ``metadata`` may
    hold a serialised mirror, but scoring functions MUST receive this object
    directly — never read cost/time from metadata dicts.

    All fields are required; missing accounting must raise, not default to 0.
    """

    submission_credits: int
    evaluator_credits: int
    submission_wall_seconds: float
    evaluator_wall_seconds: float

    @property
    def total_credits(self) -> int:
        return self.submission_credits + self.evaluator_credits

    @property
    def total_wall_seconds(self) -> float:
        return self.submission_wall_seconds + self.evaluator_wall_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "submission_credits": self.submission_credits,
            "evaluator_credits": self.evaluator_credits,
            "total_credits": self.total_credits,
            "submission_wall_seconds": self.submission_wall_seconds,
            "evaluator_wall_seconds": self.evaluator_wall_seconds,
            "total_wall_seconds": self.total_wall_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationAccounting":
        return cls(
            submission_credits=int(data.get("submission_credits", 0)),
            evaluator_credits=int(data.get("evaluator_credits", 0)),
            submission_wall_seconds=float(data.get("submission_wall_seconds", 0.0)),
            evaluator_wall_seconds=float(data.get("evaluator_wall_seconds", 0.0)),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Submission evidence (crosses submission → evaluator boundary)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SubmissionEvidence:
    """Complete, serialisable evidence from a submission run.

    The evaluator reads this to verify that the submitted kernel was produced
    by a legitimate submission run, and to carry forward cost accounting.
    """

    schema_version: int = 1
    run_id: str = ""                         # unique per run
    task_id: str = ""

    # Status
    status: str = RunStatus.RUNNING.value     # terminal status from RunStatus

    # Kernel identity
    kernel_sha256: str = ""

    # Cost accounting (credits are NOT reset to 0 in the evaluator)
    credits_spent: int = 0
    credits_total: int = 0

    # LLM usage
    model: str | None = None
    token_usage: dict[str, Any] | None = None

    # Timing
    submission_started_at: str = ""           # ISO 8601 UTC
    submission_wall_seconds: float = 0.0
    tool_wall_seconds: float = 0.0

    # Public gate results
    interface_ok: bool | None = None
    csim_ok: bool | None = None
    synth_ok: bool | None = None
    frequency_ok: bool | None = None
    resource_ok: bool | None = None
    cosim_ok: bool | None = None

    # Scoring profile
    scoring_profile: str = "balanced"

    # Stop reason (empty if completed)
    stop_reason: str = ""

    @classmethod
    def from_run_state(cls, state: Any, *, run_id: str = "") -> "SubmissionEvidence":
        """Construct evidence from a terminal :class:`RunState`."""
        from datetime import datetime, timezone

        started = state.metadata.get("submission_started_at", "")
        if not started:
            started = datetime.now(timezone.utc).isoformat()

        kernel_text = getattr(state, "kernel", "") or ""
        kernel_sha256 = hashlib.sha256(kernel_text.encode("utf-8")).hexdigest()

        budget = getattr(getattr(state, "server", None), "budget", None)
        spent = getattr(budget, "spent", 0) if budget is not None else 0
        total = getattr(budget, "total", 0) if budget is not None else 0

        # Aggregate tool wall time
        tool_wall = sum(
            getattr(r, "elapsed_s", 0.0) for r in getattr(state, "results", [])
        )

        llm_summary: dict[str, Any] | None = None
        llm = getattr(state, "llm", None)
        if llm is not None:
            token_usage = getattr(llm, "token_usage", None)
            snapshot = getattr(token_usage, "snapshot", None)
            llm_summary = {
                "model": getattr(llm, "model", None),
                "token_usage": snapshot() if callable(snapshot) else None,
            }

        return cls(
            schema_version=1,
            run_id=run_id,
            task_id=getattr(getattr(state, "task", None), "id", ""),
            status=state.status,
            kernel_sha256=kernel_sha256,
            credits_spent=spent,
            credits_total=total,
            model=llm_summary.get("model") if llm_summary else None,
            token_usage=(
                llm_summary.get("token_usage") if llm_summary else None
            ),
            submission_started_at=started,
            tool_wall_seconds=round(tool_wall, 3),
            interface_ok=getattr(state, "interface_ok", None),
            csim_ok=getattr(state, "csim_ok", None),
            synth_ok=getattr(state, "synth_ok", None),
            frequency_ok=getattr(state, "frequency_ok", None),
            resource_ok=getattr(state, "resource_ok", None),
            cosim_ok=getattr(state, "cosim_ok", None),
            scoring_profile=getattr(
                getattr(state, "config", None), "scoring_profile", "balanced"
            ),
            stop_reason=getattr(state, "stop_reason", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "status": self.status,
            "kernel_sha256": self.kernel_sha256,
            "credits_spent": self.credits_spent,
            "credits_total": self.credits_total,
            "model": self.model,
            "token_usage": self.token_usage,
            "submission_started_at": self.submission_started_at,
            "submission_wall_seconds": self.submission_wall_seconds,
            "tool_wall_seconds": self.tool_wall_seconds,
            "interface_ok": self.interface_ok,
            "csim_ok": self.csim_ok,
            "synth_ok": self.synth_ok,
            "frequency_ok": self.frequency_ok,
            "resource_ok": self.resource_ok,
            "cosim_ok": self.cosim_ok,
            "scoring_profile": self.scoring_profile,
            "stop_reason": self.stop_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubmissionEvidence":
        """Deserialise, tolerating missing optional fields."""
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            run_id=str(data.get("run_id", "")),
            task_id=str(data.get("task_id", "")),
            status=str(data.get("status", "running")),
            kernel_sha256=str(data.get("kernel_sha256", "")),
            credits_spent=int(data.get("credits_spent", 0)),
            credits_total=int(data.get("credits_total", 0)),
            model=data.get("model"),
            token_usage=data.get("token_usage"),
            submission_started_at=str(data.get("submission_started_at", "")),
            submission_wall_seconds=float(data.get("submission_wall_seconds", 0.0)),
            tool_wall_seconds=float(data.get("tool_wall_seconds", 0.0)),
            interface_ok=data.get("interface_ok"),
            csim_ok=data.get("csim_ok"),
            synth_ok=data.get("synth_ok"),
            frequency_ok=data.get("frequency_ok"),
            resource_ok=data.get("resource_ok"),
            cosim_ok=data.get("cosim_ok"),
            scoring_profile=str(data.get("scoring_profile", "balanced")),
            stop_reason=str(data.get("stop_reason", "")),
        )

    def validate_against_kernel(self, kernel_path: str) -> None:
        """Raise :class:`EvidenceError` if the kernel digest does not match."""
        actual = ArtifactManifest.from_path(kernel_path, role="kernel")
        if actual.sha256 != self.kernel_sha256:
            raise DigestMismatchError(
                f"kernel digest mismatch: evidence={self.kernel_sha256[:16]}… "
                f"actual={actual.sha256[:16]}…"
            )

    def require_completed(self) -> None:
        """Raise if the submission did not reach a terminal pass state."""
        if self.status != RunStatus.COMPLETED.value:
            raise EvidenceError(
                f"submission did not complete (status={self.status}, "
                f"stop_reason={self.stop_reason})"
            )
        if not self.kernel_sha256:
            raise MissingEvidenceError("submission evidence is missing kernel digest")


# ═══════════════════════════════════════════════════════════════════════════════
# Anchor evidence (records WHY the anchor was chosen)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AnchorEvidence:
    """Complete gate evidence for anchor qualification.

    An anchor is valid for scoring only when it passes every required gate.
    This evidence is recorded so the choice is auditable.
    """

    source: str = "none"                     # "starter" | "reference" | "candidate_self" | "none"
    valid: bool = False

    # Identity
    source_sha256: str = ""

    # Gate evidence
    csim_ok: bool | None = None              # None = not run
    synth_ok: bool | None = None
    interface_ok: bool | None = None
    frequency: FrequencyGateEvidence | None = None
    resource: ResourceGateEvidence | None = None
    cosim: CoSimGateEvidence | None = None   # None = not required

    # PPA from synthesis (only when synth passes)
    latency: int | None = None
    ii: int | None = None
    clock_ns: float | None = None
    resources: dict[str, int] = field(default_factory=dict)
    available: dict[str, int] = field(default_factory=dict)

    # Failure diagnostics
    failure_reason: str = ""

    schema_version: int = 1

    @property
    def latency_available(self) -> bool:
        return self.latency is not None

    @property
    def passes_all_required_gates(self) -> bool:
        """An anchor requires CSim + Synth + interface + frequency + resource + latency.

        Every required gate must be explicitly ``True``.  ``None`` means "not
        executed" and is treated as a failure (fail-closed).
        """
        if not self.valid:
            return False
        # Every gate must be explicitly True; None = not executed → fail
        if self.csim_ok is not True:
            return False
        if self.synth_ok is not True:
            return False
        if self.interface_ok is not True:
            return False
        if self.frequency is None or not self.frequency.ok:
            return False
        if self.resource is None or not self.resource.ok:
            return False
        if self.latency is None:
            return False
        if self.ii is None:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "valid": self.valid,
            "source_sha256": self.source_sha256,
            "csim_ok": self.csim_ok,
            "synth_ok": self.synth_ok,
            "interface_ok": self.interface_ok,
            "frequency": self.frequency.to_dict() if self.frequency else None,
            "resource": self.resource.to_dict() if self.resource else None,
            "cosim": self.cosim.to_dict() if self.cosim else None,
            "latency": self.latency,
            "ii": self.ii,
            "clock_ns": self.clock_ns,
            "resources": dict(self.resources),
            "available": dict(self.available),
            "failure_reason": self.failure_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnchorEvidence":
        freq_data = data.get("frequency")
        resource_data = data.get("resource")
        cosim_data = data.get("cosim")
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            source=str(data.get("source", "none")),
            valid=bool(data.get("valid", False)),
            source_sha256=str(data.get("source_sha256", "")),
            csim_ok=data.get("csim_ok"),
            synth_ok=data.get("synth_ok"),
            interface_ok=data.get("interface_ok"),
            frequency=(
                FrequencyGateEvidence(**freq_data)
                if isinstance(freq_data, dict) else None
            ),
            resource=(
                ResourceGateEvidence(**resource_data)
                if isinstance(resource_data, dict) else None
            ),
            cosim=(
                CoSimGateEvidence(**cosim_data)
                if isinstance(cosim_data, dict) else None
            ),
            latency=data.get("latency"),
            ii=data.get("ii"),
            clock_ns=data.get("clock_ns"),
            resources=dict(data.get("resources", {})),
            available=dict(data.get("available", {})),
            failure_reason=str(data.get("failure_reason", "")),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _serialise_model(obj: Any, indent: int = 2) -> str:
    """Serialise any model with a ``to_dict()`` method to JSON."""
    return json.dumps(obj.to_dict(), indent=indent, sort_keys=True, ensure_ascii=False)


def _model_from_json(cls: type, text: str) -> Any:
    """Deserialise a model from JSON text via ``cls.from_dict()``."""
    return cls.from_dict(json.loads(text))
