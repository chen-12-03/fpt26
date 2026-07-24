"""Verify that the agent runner discovers public and hidden data files."""
import tempfile
from pathlib import Path

from agent.testbench import (
    _DATA_SUFFIXES,
    discover_task_data_files,
    normalize_task_testbench_data,
)
from agent.integrations.task_repository import PublicTaskRepository
from llm4hls.task import load_task


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
        found = discover_task_data_files(root)
        assert found == {}


def test_collects_known_data_extensions():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root / "input.data", b"1 2 3\n")
        _write(root / "check.txt", b"42\n")
        _write(root / "lut.hex", b"DEADBEEF")
        found = discover_task_data_files(root)
        assert "input.data" in found
        assert "check.txt" in found
        assert "lut.hex" in found
        assert found["input.data"] == b"1 2 3\n"


def test_collects_hidden_data_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root / "hidden" / "secret.data", b"hidden content")
        _write(root / "input.data", b"public")
        found = discover_task_data_files(root, include_hidden=True)
        assert "secret.data" in found
        assert "input.data" in found
        assert found["secret.data"] == b"hidden content"


def test_ignores_non_data_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root / ".gitignore", b"*.o\n")
        _write(root / "README.md", b"docs")
        _write(root / "Makefile", b"all:")
        found = discover_task_data_files(root)
        assert ".gitignore" not in found
        assert "README.md" not in found
        assert "Makefile" not in found


def test_real_machsuite_task_discovers_data():
    """Agent preparation surfaces separate public and hidden fixture maps."""
    task_dir = Path(__file__).resolve().parents[2] / "tasks/generated/machsuite__gemm_blocked"
    if not task_dir.is_dir():
        return  # skip when the task repo isn't mounted
    t = load_task(str(task_dir))
    normalize_task_testbench_data(t)
    assert len(t.public_data_files) >= 2
    assert "input.data" in t.public_data_files
    assert "check.data" in t.public_data_files
    assert len(t.public_data_files["input.data"]) > 0
    assert t.hidden_data_files["input.data"] == t.public_data_files["input.data"]


def test_public_repository_attaches_public_fixtures_during_load():
    """Submission loading must stage fixtures before ToolServer construction."""
    task_dir = (
        Path(__file__).resolve().parents[2]
        / "tasks/generated/machsuite__gemm_ncubed"
    )
    if not task_dir.is_dir():
        return

    task, _ = PublicTaskRepository().load(task_dir)

    assert sorted(task.public_data_files) == ["check.data", "input.data"]
    assert task.data_files == task.public_data_files
    assert not hasattr(task, "reference_code") or task.reference_code is None
