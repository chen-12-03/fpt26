"""Regression coverage for CRLF-sensitive testbench fixture parsers."""

from types import SimpleNamespace

from agent.testbench import normalize_task_testbench_data


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
