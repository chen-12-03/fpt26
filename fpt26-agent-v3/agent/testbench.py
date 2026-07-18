"""Agent-side preparation of testbench fixture data.

The harness stages fixture bytes verbatim.  Some imported benchmark vectors use
Windows line endings while their C/C++ parsers look specifically for ``%%\n``
section markers.  Normalize only text-like fixtures before handing the task to
the runner; task sources and binary fixtures remain byte-for-byte unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


_TEXT_FIXTURE_SUFFIXES = frozenset(
    {".data", ".txt", ".hex", ".dat", ".in", ".out", ".golden", ".coe", ".mif"}
)
_DATA_SUFFIXES = frozenset(
    {
        ".data", ".txt", ".hex", ".bin", ".dat", ".in", ".out", ".golden",
        ".ppm", ".bmp", ".pgm", ".raw", ".coe", ".mif",
    }
)


def _data_files_in(directory: Path) -> dict[str, bytes]:
    if not directory.is_dir():
        return {}
    discovered = {}
    for candidate in sorted(directory.iterdir()):
        if not candidate.is_file() or candidate.suffix.lower() not in _DATA_SUFFIXES:
            continue
        if candidate.name.lower().startswith("output"):
            continue
        discovered[candidate.name] = candidate.read_bytes()
    return discovered


def discover_task_data_files(
    task_dir: Path, *, include_hidden: bool = False
) -> dict[str, bytes]:
    """Discover public fixtures, optionally overlaying hidden fixture bytes."""
    discovered = _data_files_in(task_dir)
    if include_hidden:
        discovered.update(_data_files_in(task_dir / "hidden"))
    return discovered


def _normalize_text_fixtures(data_files: dict[str, bytes]) -> tuple[dict[str, bytes], list[str]]:
    prepared = dict(data_files)
    changed: list[str] = []
    for name, content in data_files.items():
        if Path(name).suffix.lower() not in _TEXT_FIXTURE_SUFFIXES:
            continue
        if not isinstance(content, bytes) or b"\x00" in content or b"\r" not in content:
            continue
        normalized = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        if normalized != content:
            prepared[name] = normalized
            changed.append(name)
    return prepared, changed


def normalize_task_testbench_data(task: Any) -> tuple[str, ...]:
    """Normalize CRLF/CR newlines in text fixtures attached to ``task``.

    Returns the sorted fixture names whose staged bytes changed.  Binary data
    and text that is already LF-only are preserved exactly.
    """
    task_dir = getattr(task, "dir", None)
    if task_dir is not None:
        public_data = discover_task_data_files(Path(task_dir))
        hidden_data = discover_task_data_files(Path(task_dir), include_hidden=True)
        public_prepared, public_changed = _normalize_text_fixtures(public_data)
        hidden_prepared, hidden_changed = _normalize_text_fixtures(hidden_data)
        task.public_data_files = public_prepared
        task.hidden_data_files = hidden_prepared
        task.data_files = public_prepared
        return tuple(sorted(set(public_changed + hidden_changed)))

    data_files = getattr(task, "data_files", None)
    if not isinstance(data_files, dict):
        return ()
    prepared, changed = _normalize_text_fixtures(data_files)
    task.data_files = prepared
    return tuple(sorted(changed))
