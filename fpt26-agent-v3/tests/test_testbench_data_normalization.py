"""Regression coverage for CRLF-sensitive testbench fixture parsers."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.testbench import normalize_task_testbench_data
from llm4hls.task import load_task
from agent.runner import CSimTool


_REAL_VITIS = os.environ.get("FPT26_REAL_VITIS_TESTS") == "1"
_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


def test_normalizes_crlf_section_markers_for_text_fixtures() -> None:
    task = SimpleNamespace(
        data_files={
            "input.data": b"%%\r\n1\r\n%%\r\n2\r\n",
            "check.txt": b"%%\r3\r",
        }
    )

    changed = normalize_task_testbench_data(task)

    assert changed == ("check.txt", "input.data")
    assert task.data_files["input.data"] == b"%%\n1\n%%\n2\n"
    assert task.data_files["check.txt"] == b"%%\n3\n"


def test_preserves_lf_text_and_binary_fixtures() -> None:
    task = SimpleNamespace(
        data_files={
            "input.data": b"%%\n1\n",
            "image.bin": b"\x00\r\n\xff",
            "opaque.data": b"\x00\r\n",
        }
    )
    original = dict(task.data_files)

    changed = normalize_task_testbench_data(task)

    assert changed == ()
    assert task.data_files == original


def test_task_without_fixture_mapping_is_a_noop() -> None:
    task = SimpleNamespace()

    assert normalize_task_testbench_data(task) == ()


@pytest.mark.skipif(not _REAL_VITIS, reason="set FPT26_REAL_VITIS_TESTS=1")
def test_real_vitis_crlf_fixture_passes_and_writes_expected_output(tmp_path) -> None:
    task = load_task(_WORKSPACE_ROOT / "tasks/generated/machsuite__aes_aes")
    assert normalize_task_testbench_data(task) == ("check.data", "input.data")

    result = CSimTool().run(
        tmp_path / "pass",
        task.assemble(task.kernel_code, task.public_tb_code, task.public_tb_name),
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
        data_files=task.public_data_files,
    )

    output = tmp_path / "pass/csim_proj/sol/csim/build/output.data"
    assert result.ok is True
    assert result.phase == "pass"
    assert result.return_code == 0
    assert "Success." in result.log
    assert output.read_bytes() == task.public_data_files["check.data"]


@pytest.mark.skipif(not _REAL_VITIS, reason="set FPT26_REAL_VITIS_TESTS=1")
def test_real_vitis_bad_expected_data_remains_runtime_failure(tmp_path) -> None:
    task = load_task(_WORKSPACE_ROOT / "tasks/generated/machsuite__aes_aes")
    normalize_task_testbench_data(task)
    task.public_data_files["check.data"] = b"%%\n" + b"0\n" * 16

    result = CSimTool().run(
        tmp_path / "fail",
        task.assemble(task.kernel_code, task.public_tb_code, task.public_tb_name),
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
        data_files=task.public_data_files,
    )

    output = tmp_path / "fail/csim_proj/sol/csim/build/output.data"
    assert result.ok is False
    assert result.phase == "runtime_fail"
    assert result.return_code == 255
    assert "Benchmark results are incorrect" in result.log
    assert output.is_file()
