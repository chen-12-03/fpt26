"""Verify that load_task discovers and surfaces testbench data files."""
import tempfile, os
from pathlib import Path

from llm4hls.task import _DATA_SUFFIXES, _discover_data_files, load_task


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)


def test_data_suffix_set_is_non_empty():
    assert len(_DATA_SUFFIXES) > 0
    assert ".data" in _DATA_SUFFIXES
    assert ".txt" in _DATA_SUFFIXES
    assert ".hex" in _DATA_SUFFIXES


def test_ignores_source_and_header_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root / "kernel.cpp", "int main(){}")
        _write(root / "kernel.h", "#pragma once")
        _write(root / "tb.cpp", "#include <cstdio>")
        found = _discover_data_files(root)
        assert found == {}


def test_collects_known_data_extensions():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root / "input.data", b"1 2 3\n")
        _write(root / "check.txt", b"42\n")
        _write(root / "lut.hex", b"DEADBEEF")
        found = _discover_data_files(root)
        assert "input.data" in found
        assert "check.txt" in found
        assert "lut.hex" in found
        assert found["input.data"] == b"1 2 3\n"


def test_collects_hidden_data_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root / "hidden" / "secret.data", b"hidden content")
        _write(root / "input.data", b"public")
        found = _discover_data_files(root)
        assert "secret.data" in found
        assert "input.data" in found
        assert found["secret.data"] == b"hidden content"


def test_ignores_non_data_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root / ".gitignore", b"*.o\n")
        _write(root / "README.md", b"docs")
        _write(root / "Makefile", b"all:")
        found = _discover_data_files(root)
        assert ".gitignore" not in found
        assert "README.md" not in found
        assert "Makefile" not in found


def test_real_machsuite_task_discovers_data(monkeypatch):
    """load_task on gemm_blocked should surface input.data + check.data."""
    task_dir = Path("/home/chen1/projects/fpt26_new/tasks/generated/machsuite__gemm_blocked")
    if not task_dir.is_dir():
        return  # skip when the task repo isn't mounted
    # Prevent Vitis env checks from blocking
    monkeypatch.setattr("llm4hls.task.config", type("cfg", (), {
        "DEFAULT_PART": "xcu55c-fsvh2892-2L-e",
        "DEFAULT_CLOCK_NS": 5.0,
        "DEFAULT_FLOW_TARGET": "vivado",
    })())
    t = load_task(str(task_dir))
    assert len(t.data_files) >= 2, f"Expected >=2 data files, got {len(t.data_files)}"
    assert "input.data" in t.data_files
    assert "check.data" in t.data_files
    assert len(t.data_files["input.data"]) > 0
