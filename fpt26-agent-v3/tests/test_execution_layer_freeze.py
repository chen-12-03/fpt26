"""Enforce the post-validation runner/testbench/harness freeze manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _WORKSPACE_ROOT / "fpt26-agent-v3/execution-freeze.json"
_DATA_SUFFIXES = {
    ".data", ".txt", ".hex", ".bin", ".dat", ".in", ".out", ".golden",
    ".ppm", ".bmp", ".pgm", ".raw", ".coe", ".mif",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _selected_files(root: Path, kind: str) -> list[Path]:
    files = [path for path in root.rglob("*") if path.is_file()]
    if kind == "python_sources":
        return sorted(
            path for path in files
            if path.suffix == ".py" and "__pycache__" not in path.parts
        )
    if kind == "testbench_assets":
        return sorted(
            path for path in files
            if path.name == "task.toml"
            or path.name.endswith("_tb.cpp")
            or path.suffix.lower() in _DATA_SUFFIXES
        )
    raise AssertionError(f"unknown freeze tree kind: {kind}")


def _tree_digest(root: Path, kind: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    selected = _selected_files(root, kind)
    for path in selected:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest(), len(selected)


def test_frozen_execution_files_match_manifest() -> None:
    manifest = json.loads(_MANIFEST.read_text())

    for relative, expected in manifest["files"].items():
        path = _WORKSPACE_ROOT / relative
        assert path.is_file(), f"frozen file missing: {relative}"
        assert _sha256(path) == expected, f"frozen file changed: {relative}"


def test_frozen_execution_trees_match_manifest() -> None:
    manifest = json.loads(_MANIFEST.read_text())

    for name, spec in manifest["trees"].items():
        actual_digest, actual_count = _tree_digest(
            _WORKSPACE_ROOT / spec["root"], spec["kind"]
        )
        assert actual_count == spec["count"], f"frozen tree count changed: {name}"
        assert actual_digest == spec["sha256"], f"frozen tree changed: {name}"
