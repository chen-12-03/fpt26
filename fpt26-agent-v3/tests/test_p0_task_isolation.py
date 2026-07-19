from __future__ import annotations

from pathlib import Path

import pytest

from agent.task_io import TaskPreflightError, load_public_task
from agent.evaluator import _hidden_source


def _task(root: Path) -> Path:
    root.mkdir()
    (root / "task.toml").write_text(
        "\n".join(
            [
                'task_id = "isolation"',
                'task_type = "repair"',
                'top = "kernel"',
                'kernel_file = "kernel.cpp"',
                'header_files = ["kernel.h"]',
                'public_tb = "kernel_tb.cpp"',
                "budget = 20",
                "",
                "[target]",
                'part = "xcu55c-fsvh2892-2L-e"',
                "clock_ns = 5.0",
            ]
        )
        + "\n"
    )
    (root / "description.md").write_text("public description\n")
    (root / "kernel.h").write_text("void kernel(int a[4]);\n")
    (root / "kernel.cpp").write_text(
        '#include "kernel.h"\nvoid kernel(int a[4]) { a[0] = 1; }\n'
    )
    (root / "kernel_tb.cpp").write_text("int main() { return 0; }\n")
    (root / "hidden").mkdir()
    (root / "hidden" / "kernel_tb.cpp").write_text("SECRET_HIDDEN\n")
    (root / "reference").mkdir()
    (root / "reference" / "kernel.cpp").write_text("SECRET_REFERENCE\n")
    return root


def test_submission_loader_never_reads_hidden_or_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _task(tmp_path / "task")
    original = Path.read_text
    reads: list[Path] = []

    def guarded(path: Path, *args, **kwargs):
        reads.append(path)
        if "hidden" in path.parts or "reference" in path.parts:
            raise AssertionError(f"submission accessed evaluator artifact: {path}")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    task, preflight = load_public_task(root)

    assert task.hidden_tb_name == ""
    assert task.hidden_tb_code == ""
    assert task.reference_code is None
    assert preflight.task_id == "isolation"
    assert preflight.observed_vitis_version == "2025.2"
    assert preflight.observed_vitis_build
    assert preflight.forbidden_artifact_accesses == 0
    assert all("hidden" not in path.parts for path in reads)
    assert all("reference" not in path.parts for path in reads)


def test_submission_preflight_rejects_non_u55c(tmp_path: Path) -> None:
    root = _task(tmp_path / "task")
    task_toml = (root / "task.toml").read_text()
    (root / "task.toml").write_text(
        task_toml.replace("xcu55c-fsvh2892-2L-e", "xc7z020clg400-1")
    )
    with pytest.raises(TaskPreflightError, match="U55C"):
        load_public_task(root)


def test_submission_preflight_rejects_missing_public_tb(tmp_path: Path) -> None:
    root = _task(tmp_path / "task")
    (root / "kernel_tb.cpp").unlink()
    with pytest.raises(TaskPreflightError, match="public_tb"):
        load_public_task(root)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kernel_file", "reference/kernel.cpp"),
        ("public_tb", "hidden/kernel_tb.cpp"),
    ],
)
def test_submission_rejects_evaluator_owned_paths_before_read(
    tmp_path: Path,
    field: str,
    value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _task(tmp_path / "task")
    text = (root / "task.toml").read_text()
    old = (
        'kernel_file = "kernel.cpp"'
        if field == "kernel_file"
        else 'public_tb = "kernel_tb.cpp"'
    )
    (root / "task.toml").write_text(text.replace(old, f'{field} = "{value}"'))

    original = Path.read_text

    def guarded(path: Path, *args, **kwargs):
        if "hidden" in path.parts or "reference" in path.parts:
            raise AssertionError(f"forbidden file was opened: {path}")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    with pytest.raises(TaskPreflightError, match="hidden/reference"):
        load_public_task(root)


def test_evaluator_labels_hidden_and_public_fallback(tmp_path: Path) -> None:
    root = _task(tmp_path / "task")

    assert _hidden_source(root) == (True, "hidden")

    (root / "hidden" / "kernel_tb.cpp").unlink()
    assert _hidden_source(root) == (False, "public_fallback")
