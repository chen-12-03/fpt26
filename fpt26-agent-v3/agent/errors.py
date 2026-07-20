"""Unified exception hierarchy for the agent pipeline.

All agent-raised exceptions derive from :class:`AgentError` so callers can
catch infrastructure and validation failures without depending on harness or
stdlib exception types.
"""

from __future__ import annotations


class AgentError(Exception):
    """Base for all agent-originated exceptions."""


# ── Preflight / configuration ────────────────────────────────────────────────

class PreflightError(AgentError):
    """A required precondition is not met before the run starts."""


class TaskPreflightError(PreflightError):
    """The public task package or target contract is invalid."""


class VitisEnvironmentError(PreflightError):
    """The configured Vitis installation cannot be probed or is wrong version."""


class BudgetOverrideError(PreflightError):
    """The requested budget override is invalid."""


# ── Security ─────────────────────────────────────────────────────────────────

class SecurityError(AgentError):
    """A security policy violation was detected."""


class PathEscapesWorkspaceError(SecurityError):
    """A resolved path lies outside the permitted workspace or artifact root."""


class SymlinkNotAllowedError(SecurityError):
    """A required file is a symbolic link, which is forbidden by policy."""


class HiddenReferenceAccessError(SecurityError):
    """Attempted to read, stat, or probe a hidden or reference artifact."""


class InvalidIdentifierError(SecurityError):
    """A user-controlled identifier (task_id, top name, Tcl token) is unsafe."""


# ── Evidence / validation ────────────────────────────────────────────────────

class EvidenceError(AgentError):
    """Submission or anchor evidence is missing, damaged, or inconsistent."""


class MissingEvidenceError(EvidenceError):
    """Required evidence fields are absent."""


class DigestMismatchError(EvidenceError):
    """A computed digest does not match the recorded evidence digest."""


# ── Pipeline / tool ──────────────────────────────────────────────────────────

class PipelineError(AgentError):
    """The pipeline cannot continue."""


class ToolExecutionError(PipelineError):
    """A tool (CSim / Synth / CoSim) failed in an unrecoverable way."""


class BudgetExhaustedError(PipelineError):
    """The credit budget has been fully consumed."""


class InvalidCandidateError(PipelineError):
    """A proposed candidate kernel is structurally invalid."""
