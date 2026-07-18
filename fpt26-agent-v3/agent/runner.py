"""Agent-owned adapters around the read-only harness execution interfaces."""

from __future__ import annotations

import re
from pathlib import Path

from llm4hls import config
from llm4hls.harness import ToolServer as HarnessToolServer
from llm4hls.tools import (
    CoSimTool as HarnessCoSimTool,
    CSimTool as HarnessCSimTool,
    SynthTool as HarnessSynthTool,
)


_REGISTER_KW_RE = re.compile(r"\bregister\s+")


def _prepare_cpp17_sources(files: dict[str, str]) -> dict[str, str]:
    """Return runner-local C++17-compatible source copies."""
    return {name: _REGISTER_KW_RE.sub("", content) for name, content in files.items()}


class CSimTool(HarnessCSimTool):
    """Harness C-simulation with agent-owned fixture and source preparation."""

    def __init__(self, data_files: dict[str, bytes] | None = None) -> None:
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
        fixtures = self.data_files if data_files is None else data_files
        return super().run(
            build_dir,
            _prepare_cpp17_sources(files),
            top=top,
            part=part,
            clock_ns=clock_ns,
            data_files=fixtures,
        )


class SynthTool(HarnessSynthTool):
    """Harness synthesis with agent-owned C++17 source preparation."""

    def run(
        self,
        build_dir,
        files,
        synth_sources,
        top,
        part=config.DEFAULT_PART,
        clock_ns=config.DEFAULT_CLOCK_NS,
    ):
        return super().run(
            build_dir,
            _prepare_cpp17_sources(files),
            synth_sources=synth_sources,
            top=top,
            part=part,
            clock_ns=clock_ns,
        )


class CoSimTool(HarnessCoSimTool):
    """Harness co-simulation with agent-owned C++17 source preparation."""

    def run(
        self,
        build_dir,
        files,
        synth_sources,
        tb_sources,
        top,
        part=config.DEFAULT_PART,
        clock_ns=config.DEFAULT_CLOCK_NS,
    ):
        return super().run(
            build_dir,
            _prepare_cpp17_sources(files),
            synth_sources=synth_sources,
            tb_sources=tb_sources,
            top=top,
            part=part,
            clock_ns=clock_ns,
        )


class ToolServer(HarnessToolServer):
    """Drop-in ToolServer using agent-owned adapters behind the same API."""

    def __init__(self, task, budget, run_root: Path) -> None:
        super().__init__(task, budget, run_root)
        self._csim = CSimTool(getattr(task, "public_data_files", None))
        self._synth = SynthTool()
        self._cosim = CoSimTool()
