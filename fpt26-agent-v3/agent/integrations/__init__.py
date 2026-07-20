"""Narrow, replaceable interfaces for external dependencies.

Each interface here is a :class:`typing.Protocol` — structural subtyping means
any object with the right methods satisfies the interface without needing to
inherit.  This keeps the agent core testable and lets us swap implementations
(local fake, Dockerised Vitis, real Vitis) without changing business logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ToolExecutor(Protocol):
    """Run a metered HLS tool (csim / synth / cosim) and return a result.

    Implementations must:
    - validate all paths against the workspace root before launching a subprocess
    - sanitise the child environment (no API keys, tokens, or secrets)
    - honour the configured timeout (raise / return error, do not hang)
    - return a structured result with ``ok``, ``log``, and (for synth/cosim) a report
    """

    def csim(
        self,
        build_dir: Path,
        files: dict[str, str],
        top: str,
        *,
        part: str = ...,
        clock_ns: float = ...,
        data_files: dict[str, bytes] | None = ...,
    ) -> Any: ...

    def synth(
        self,
        build_dir: Path,
        files: dict[str, str],
        synth_sources: list[str],
        top: str,
        *,
        part: str = ...,
        clock_ns: float = ...,
    ) -> Any: ...

    def cosim(
        self,
        build_dir: Path,
        files: dict[str, str],
        synth_sources: list[str],
        tb_sources: list[str],
        top: str,
        *,
        part: str = ...,
        clock_ns: float = ...,
    ) -> Any: ...


class LLMClient(Protocol):
    """Complete a prompt and return the model's text response."""

    def complete(self, system: str, user: str) -> str: ...


class TaskRepository(Protocol):
    """Load a task by directory path, returning only public artifacts."""

    def load(self, task_dir: str | Path) -> Any: ...
    def preflight(self, task_dir: str | Path) -> Any: ...


class ArtifactStore(Protocol):
    """Persist and retrieve run artifacts (kernels, reports, evidence)."""

    def write_kernel(self, task_id: str, kernel: str) -> Path: ...
    def write_report(self, task_id: str, report: dict[str, Any]) -> Path: ...
    def write_evidence(self, task_id: str, evidence: dict[str, Any]) -> Path: ...
    def read_report(self, task_id: str) -> dict[str, Any] | None: ...
