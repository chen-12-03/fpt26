import hashlib
import json
from pathlib import Path

import pytest

from scoring.isolated_role_entrypoint import (
    assert_evaluator_isolation,
    assert_submission_isolation,
    resolve_submission_artifacts,
)


def _write_public_task(root: Path, task_id: str) -> Path:
    task = root / task_id
    task.mkdir(parents=True)
    (task / "task.toml").write_text(
        f'''task_id = "{task_id}"
task_type = "repair"
difficulty = 1
top = "top"
kernel_file = "kernel.cpp"
header_files = []
public_tb = "tb.cpp"
budget = 10
requires_cosim = false
initial_condition = "invalid"

[target]
part = "xcu55c-fsvh2892-2L-e"
clock_ns = 10.0
''',
        encoding="utf-8",
    )
    (task / "kernel.cpp").write_text("void top() {}\n", encoding="utf-8")
    (task / "tb.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    return task


def test_submission_isolation_accepts_public_only_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _write_public_task(tmp_path / "public", "ta2_cr_001")
    # The unit test itself runs from a repository-mounted development
    # container.  The production Submission container has no /workspace mount,
    # so isolate the filesystem-tree assertion from the outer test harness.
    monkeypatch.setattr(
        "scoring.isolated_role_entrypoint.mounted_paths",
        lambda: [],
    )

    result = assert_submission_isolation(task)

    assert result["physical_isolation_proven"] is True
    assert result["private_task_paths_visible"] is False
    assert result["public_task_identity"]["task_id"] == "ta2_cr_001"


@pytest.mark.parametrize("private_name", ["hidden", "reference"])
def test_submission_isolation_rejects_private_tree(
    tmp_path: Path,
    private_name: str,
) -> None:
    task = _write_public_task(tmp_path / "public", "ta2_cr_001")
    (task / private_name).mkdir()

    with pytest.raises(RuntimeError, match="contains private paths"):
        assert_submission_isolation(task)


def test_evaluator_requires_private_inputs_and_no_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    task = _write_public_task(tmp_path / "private", "ta2_cr_001")
    (task / "hidden").mkdir()
    (task / "reference").mkdir()
    monkeypatch.setenv("FPT26_LLM_API_KEY", "must-not-cross-boundary")
    network_root = tmp_path / "network"
    (network_root / "lo").mkdir(parents=True)

    with pytest.raises(RuntimeError, match="inherited API credentials"):
        assert_evaluator_isolation(task, network_root)

    monkeypatch.delenv("FPT26_LLM_API_KEY")
    result = assert_evaluator_isolation(task, network_root)
    assert result["api_credentials_visible"] is False
    assert result["network_isolated"] is True


def test_evaluator_rejects_a_non_loopback_interface(tmp_path: Path) -> None:
    task = _write_public_task(tmp_path / "private", "ta2_cr_001")
    (task / "hidden").mkdir()
    (task / "reference").mkdir()
    network_root = tmp_path / "network"
    (network_root / "lo").mkdir(parents=True)
    (network_root / "eth0").mkdir()

    with pytest.raises(RuntimeError, match="not network-isolated"):
        assert_evaluator_isolation(task, network_root)


def test_submission_boundary_authenticates_final_kernel(tmp_path: Path) -> None:
    task_id = "ta2_cr_001"
    task_output = tmp_path / "submission" / task_id
    task_output.mkdir(parents=True)
    final = task_output / "final_kernel.cpp"
    final.write_text("void top() {}\n", encoding="utf-8")
    digest = hashlib.sha256(final.read_bytes()).hexdigest()
    (task_output / "run_report.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "run_role": "submission",
                "status": "completed",
                "final_artifact": {
                    "path": "/fpt26-output/ta2_cr_001/final_kernel.cpp",
                    "sha256": digest,
                },
            }
        ),
        encoding="utf-8",
    )
    (task_output / "submission_evidence.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "task_id": task_id,
                "status": "completed",
                "kernel_sha256": digest,
            }
        ),
        encoding="utf-8",
    )

    resolved, evidence, report = resolve_submission_artifacts(
        tmp_path / "submission",
        task_id,
    )

    assert resolved == final
    assert evidence.name == "submission_evidence.json"
    assert report["final_artifact"]["sha256"] == digest

    final.write_text("void top() { int changed = 1; }\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="hash disagrees"):
        resolve_submission_artifacts(tmp_path / "submission", task_id)
