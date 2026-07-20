"""Agent-owned adapters around the read-only harness execution interfaces.

Every tool call delegates to :class:`agent.integrations.vitis.SecureToolExecutor`
for security validation and sanitised subprocess execution.  This module provides
only C++17 source preparation and a drop-in ``ToolServer`` subclass.
"""

from __future__ import annotations

import re
from pathlib import Path

from llm4hls import config
from llm4hls.harness import ToolServer as HarnessToolServer

from agent.integrations.vitis import SecureToolExecutor, SourceTransformer

_REGISTER_KW_RE = re.compile(r"\bregister\s+")


def _prepare_cpp17_sources(files: dict[str, str]) -> dict[str, str]:
    """Return runner-local C++17-compatible source copies."""
    return {name: _REGISTER_KW_RE.sub("", content) for name, content in files.items()}


# ═══════════════════════════════════════════════════════════════════════════════
# Thin adapters — C++17 prep + delegate to SecureToolExecutor
# ═══════════════════════════════════════════════════════════════════════════════

class CSimTool:
    """C-simulation with C++17 source prep, delegating security to the executor."""

    def __init__(
        self,
        executor: SecureToolExecutor | None = None,
        data_files: dict[str, bytes] | None = None,
        *,
        workspace_root: str | Path = "/workspace",
    ) -> None:
        self._executor = executor or SecureToolExecutor(workspace_root=workspace_root)
        self.data_files = data_files

    def run(
        self,
        build_dir: Path,
        files: dict[str, str],
        top: str,
        part: str = config.DEFAULT_PART,
        clock_ns: float = config.DEFAULT_CLOCK_NS,
        data_files: dict[str, bytes] | None = None,
    ):
        prepared = _prepare_cpp17_sources(files)
        fixtures = self.data_files if data_files is None else data_files
        return self._executor.csim(
            build_dir, prepared, top, part=part, clock_ns=clock_ns,
            data_files=fixtures,
        )


class SynthTool:
    """Synthesis with C++17 source prep, delegating security to the executor."""

    def __init__(
        self,
        executor: SecureToolExecutor | None = None,
        *,
        workspace_root: str | Path = "/workspace",
    ) -> None:
        self._executor = executor or SecureToolExecutor(workspace_root=workspace_root)

    def run(
        self,
        build_dir: Path,
        files: dict[str, str],
        synth_sources: list[str],
        top: str,
        part: str = config.DEFAULT_PART,
        clock_ns: float = config.DEFAULT_CLOCK_NS,
    ):
        prepared = _prepare_cpp17_sources(files)
        return self._executor.synth(
            build_dir, prepared, synth_sources=synth_sources,
            top=top, part=part, clock_ns=clock_ns,
        )


class CoSimTool:
    """Co-simulation with C++17 source prep, delegating security to the executor."""

    def __init__(
        self,
        executor: SecureToolExecutor | None = None,
        *,
        workspace_root: str | Path = "/workspace",
    ) -> None:
        self._executor = executor or SecureToolExecutor(workspace_root=workspace_root)

    def run(
        self,
        build_dir: Path,
        files: dict[str, str],
        synth_sources: list[str],
        tb_sources: list[str],
        top: str,
        part: str = config.DEFAULT_PART,
        clock_ns: float = config.DEFAULT_CLOCK_NS,
    ):
        prepared = _prepare_cpp17_sources(files)
        return self._executor.cosim(
            build_dir, prepared, synth_sources=synth_sources,
            tb_sources=tb_sources, top=top, part=part, clock_ns=clock_ns,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ToolServer — drop-in replacement using SecureToolExecutor
# ═══════════════════════════════════════════════════════════════════════════════

class ToolServer(HarnessToolServer):
    """Drop-in ToolServer whose tools delegate to a :class:`SecureToolExecutor`.

    The executor is exposed as ``.executor`` so callers can swap it for a
    fake in tests without touching the tool classes.
    """

    def __init__(self, task, budget, run_root: Path,
                 workspace_root: str | Path | None = None,
                 executor: SecureToolExecutor | None = None) -> None:
        super().__init__(task, budget, run_root)
        if executor is not None:
            self.executor = executor
        else:
            ws = workspace_root if workspace_root else str(Path(run_root).resolve())
            self.executor = SecureToolExecutor(
                workspace_root=ws,
                source_transformer=_prepare_cpp17_sources,
            )
        # Build adapters that delegate to the shared executor
        self._csim = CSimTool(
            self.executor, getattr(task, "public_data_files", None),
        )
        self._synth = SynthTool(self.executor)
        self._cosim = CoSimTool(self.executor)
