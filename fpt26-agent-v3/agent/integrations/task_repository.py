"""Task repository — the single boundary for loading task data.

``PublicTaskRepository`` reads only public artifacts.  ``EvaluatorTaskRepository``
may also read hidden/reference (only in evaluator mode).  Pipeline code must
not parse TOML, read description files, or discover fixtures directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PublicTaskRepository:
    """Load only public task artifacts.  Hidden/reference are never read."""

    def load(self, task_dir: str | Path) -> tuple[Any, dict[str, Any]]:
        """Return ``(Task, preflight_dict)`` from public artifacts only."""
        from agent.task_io import load_public_task
        task, preflight = load_public_task(task_dir)
        return task, preflight.to_dict()

    def load_task_only(self, task_dir: str | Path) -> Any:
        """Return just the ``Task`` object (no preflight)."""
        t, _ = self.load(task_dir)
        return t

    def preflight(self, task_dir: str | Path) -> dict[str, Any]:
        """Return preflight metadata dict."""
        _, pf = self.load(task_dir)
        return pf

    def normalize_testbench(self, task: Any) -> tuple[str, ...]:
        """Normalize CRLF in text fixtures. Returns changed fixture names."""
        from agent.testbench import normalize_task_testbench_data
        return normalize_task_testbench_data(task, include_hidden=False)


class EvaluatorTaskRepository:
    """Load full task data including hidden/reference (evaluator-only)."""

    def load(self, task_dir: str | Path) -> Any:
        """Return a ``Task`` object with hidden/reference populated."""
        from llm4hls.task import load_task
        return load_task(task_dir)

    def load_public(self, task_dir: str | Path) -> Any:
        """Return public-only task (same as PublicTaskRepository.load)."""
        return PublicTaskRepository().load(task_dir)

    def preflight(self, task_dir: str | Path) -> dict[str, Any]:
        return PublicTaskRepository().preflight(task_dir)

    def normalize_testbench(self, task: Any) -> tuple[str, ...]:
        from agent.testbench import normalize_task_testbench_data
        return normalize_task_testbench_data(task, include_hidden=True)

    def hidden_source(self, task_dir: Path) -> tuple[bool, str]:
        """Return (hidden_available, source_label)."""
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib
        spec = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
        public_name = spec["public_tb"]
        hidden_name = spec.get("hidden_tb", public_name)
        available = (task_dir / "hidden" / hidden_name).is_file()
        return available, "hidden" if available else "public_fallback"


# In-memory fake for unit tests
class InMemoryTaskRepository:
    """Fake task repository returning a pre-built task object."""

    def __init__(self, task: Any, preflight_data: dict[str, Any] | None = None) -> None:
        self._task = task
        self._preflight = preflight_data or {}

    def load(self, task_dir: str | Path) -> Any:
        return self._task

    def preflight(self, task_dir: str | Path) -> dict[str, Any]:
        return dict(self._preflight)
