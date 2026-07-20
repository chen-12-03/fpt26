"""Secure HLS tool executor — the single integration point for all Vitis subprocess calls.

Every CSim, Synth, and CoSim invocation MUST go through this module's
:class:`SecureToolExecutor`.  Direct use of ``llm4hls.tools`` or
``llm4hls.vitis`` from agent logic is deprecated.

Security enforced on every call:
1. ``build_dir`` containment within ``workspace_root``
2. ``top`` / ``part`` / file-name Tcl-injection prevention
3. Child-process environment sanitisation (no API keys, tokens, secrets)
4. ``clock_ns`` validity (positive, finite)
5. Optional source transformation (e.g. C++17 register-stripping)
6. Result-log redaction before returning to caller

Official inputs (task sources, headers) are treated as read-only — the
executor copies them into the build directory but never modifies the originals.
"""

from __future__ import annotations

import math
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from agent.errors import SecurityError
from agent.security.execution_policy import ExecutionPolicy, sanitise_env
from agent.security.paths import (
    resolve_safe_path,
    validate_hls_identifier,
    validate_tcl_token,
)
from agent.security.redaction import redact_sensitive_text

# ═══════════════════════════════════════════════════════════════════════════════
# Secure tool executor — single authority for all HLS tool calls
# ═══════════════════════════════════════════════════════════════════════════════

SourceTransformer = Callable[[dict[str, str]], dict[str, str]]
"""A callable that pre-processes source files before they reach the harness."""


class SecureToolExecutor:
    """Run HLS tools with mandatory security checks.

    All agent code that needs to invoke CSim / Synth / CoSim should obtain
    an instance of this class (directly or via ``runner.ToolServer``) and
    call its methods.  The executor validates parameters, sanitises the
    subprocess environment, runs the harness tool, and redacts the result log
    before returning.
    """

    def __init__(
        self,
        *,
        workspace_root: str | Path = "/workspace",
        policy: ExecutionPolicy | None = None,
        source_transformer: SourceTransformer | None = None,
    ) -> None:
        self._workspace_root = Path(workspace_root).resolve()
        self._policy = policy or ExecutionPolicy(workspace_root=str(self._workspace_root))
        # Optional source preprocessing (e.g. C++17 register stripping)
        self._source_transformer = source_transformer
        # Harness tool instances created lazily
        self._csim: Any = None
        self._synth: Any = None
        self._cosim: Any = None

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    # ── Public API ───────────────────────────────────────────────────────

    def csim(
        self,
        build_dir: Path,
        files: dict[str, str],
        top: str,
        *,
        part: str = "xcu55c-fsvh2892-2L-e",
        clock_ns: float = 5.0,
        data_files: dict[str, bytes] | None = None,
    ) -> Any:
        """Run C-simulation with security checks and sanitised env."""
        self._validate(build_dir, files, top, part, clock_ns, kind="csim")
        prepared = self._transform(files)
        with _clean_subprocess_env():
            return self._redact_result(
                self._get_csim().run(
                    build_dir, prepared, top=top, part=part,
                    clock_ns=clock_ns, data_files=data_files,
                )
            )

    def synth(
        self,
        build_dir: Path,
        files: dict[str, str],
        synth_sources: list[str],
        top: str,
        *,
        part: str = "xcu55c-fsvh2892-2L-e",
        clock_ns: float = 5.0,
    ) -> Any:
        """Run C-synthesis with security checks and sanitised env."""
        self._validate(build_dir, files, top, part, clock_ns,
                       extra_names=list(synth_sources), kind="synth")
        prepared = self._transform(files)
        with _clean_subprocess_env():
            return self._redact_result(
                self._get_synth().run(
                    build_dir, prepared, synth_sources=synth_sources,
                    top=top, part=part, clock_ns=clock_ns,
                )
            )

    def cosim(
        self,
        build_dir: Path,
        files: dict[str, str],
        synth_sources: list[str],
        tb_sources: list[str],
        top: str,
        *,
        part: str = "xcu55c-fsvh2892-2L-e",
        clock_ns: float = 5.0,
    ) -> Any:
        """Run C/RTL co-simulation with security checks and sanitised env."""
        self._validate(build_dir, files, top, part, clock_ns,
                       extra_names=list(synth_sources) + list(tb_sources),
                       kind="cosim")
        prepared = self._transform(files)
        with _clean_subprocess_env():
            return self._redact_result(
                self._get_cosim().run(
                    build_dir, prepared, synth_sources=synth_sources,
                    tb_sources=tb_sources, top=top, part=part,
                    clock_ns=clock_ns,
                )
            )

    # ── Validation ───────────────────────────────────────────────────────

    def _validate(
        self,
        build_dir: Path,
        files: dict[str, str],
        top: str,
        part: str,
        clock_ns: float,
        *,
        extra_names: list[str] | None = None,
        kind: str = "tool",
    ) -> None:
        """Raise :class:`SecurityError` on first violation (before Vitis)."""
        ws = self._workspace_root

        # 1. Build directory containment (when workspace exists)
        if ws.is_dir():
            try:
                resolve_safe_path(build_dir, root=ws, allow_symlink=False,
                                  must_exist=False)
            except Exception as exc:
                raise SecurityError(f"{kind}: build_dir rejected: {exc}") from exc

        # 2. Identifier validation
        validate_hls_identifier(top, field=f"{kind}.top")
        validate_tcl_token(part, field=f"{kind}.part")

        # 3. File names (also validates no path traversal in filenames)
        names = list(files.keys()) + (extra_names or [])
        for name in names:
            validate_tcl_token(name, field=f"{kind}.filename")
            # Reject any filename that looks like an absolute path or traversal
            if name.startswith("/") or ".." in name:
                raise SecurityError(
                    f"{kind}: filename {name!r} must be a plain basename, "
                    f"not a path"
                )

        # 4. Clock validity
        if (not isinstance(clock_ns, (int, float))
                or clock_ns <= 0
                or not math.isfinite(clock_ns)):
            raise SecurityError(f"{kind}: clock_ns must be positive and finite")

    def _transform(self, files: dict[str, str]) -> dict[str, str]:
        """Apply optional source transformation (e.g. C++17 prep)."""
        if self._source_transformer is None:
            return files
        return self._source_transformer(files)

    @staticmethod
    def _redact_result(result: Any) -> Any:
        """Redact credential-shaped strings from tool result logs."""
        raw = getattr(result, "log", "")
        if raw:
            try:
                result.log = redact_sensitive_text(raw)
            except Exception:
                pass
        return result

    # ── Lazy harness tool access ─────────────────────────────────────────

    def _get_csim(self) -> Any:
        if self._csim is None:
            from llm4hls.tools import CSimTool
            self._csim = CSimTool()
        return self._csim

    def _get_synth(self) -> Any:
        if self._synth is None:
            from llm4hls.tools import SynthTool
            self._synth = SynthTool()
        return self._synth

    def _get_cosim(self) -> Any:
        if self._cosim is None:
            from llm4hls.tools import CoSimTool
            self._cosim = CoSimTool()
        return self._cosim


# ═══════════════════════════════════════════════════════════════════════════════
# Environment sanitisation context manager
# ═══════════════════════════════════════════════════════════════════════════════

_clean_env_cache: dict[str, str] | None = None


def _get_clean_env() -> dict[str, str]:
    global _clean_env_cache
    if _clean_env_cache is None:
        _clean_env_cache = sanitise_env()
    return dict(_clean_env_cache)


@contextmanager
def _clean_subprocess_env():
    """Context manager that temporarily replaces ``vitis._prepared_env``
    with a sanitised copy (no API keys, tokens, or secrets).

    The original function is restored on exit, even if an exception occurs.
    """
    import llm4hls.vitis as _v

    original = _v._prepared_env
    _v._prepared_env = _get_clean_env
    try:
        yield
    finally:
        _v._prepared_env = original
