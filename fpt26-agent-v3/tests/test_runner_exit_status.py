"""Regression coverage for terminal status and CLI return-code semantics."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.main import main
from agent.workflow import step_finalize


_REAL_VITIS = os.environ.get("FPT26_REAL_VITIS_TESTS") == "1"
_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


def _state(tmp_path: Path, **overrides) -> SimpleNamespace:
    values = {
        "config": SimpleNamespace(output_root=str(tmp_path), mode="baseline"),
        "task": SimpleNamespace(
            id="terminal_status",
            kernel_name="kernel.cpp",
            requires_cosim=False,
        ),
        "kernel": "void kernel() {}\n",
        "scorecard": SimpleNamespace(valid=True, gate_reason="passed"),
        "csim_ok": True,
        "synth_ok": True,
        "cosim_ok": False,
        "status": "running",
        "stop_reason": "",
        "log": lambda message: None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_valid_scorecard_completes_and_persists_kernel(tmp_path) -> None:
    state = step_finalize(_state(tmp_path))

    assert state.status == "completed"
    assert state.stop_reason == ""
    assert (tmp_path / "terminal_status/final_kernel.cpp").read_text() == state.kernel


def test_invalid_scorecard_fails_with_gate_reason_and_keeps_kernel(tmp_path) -> None:
    state = _state(
        tmp_path,
        scorecard=SimpleNamespace(valid=False, gate_reason="hidden_csim_fail"),
    )

    state = step_finalize(state)

    assert state.status == "failed"
    assert state.stop_reason == "hidden_csim_fail"
    assert (tmp_path / "terminal_status/final_kernel.cpp").is_file()


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"scorecard": None, "csim_ok": False}, "csim_failed"),
        ({"scorecard": None, "synth_ok": False}, "synth_failed"),
        (
            {
                "scorecard": None,
                "task": SimpleNamespace(
                    id="terminal_status",
                    kernel_name="kernel.cpp",
                    requires_cosim=True,
                ),
                "config": SimpleNamespace(output_root="", mode="structural"),
                "cosim_ok": False,
            },
            "cosim_failed",
        ),
    ],
)
def test_no_score_uses_executed_stage_gates(tmp_path, overrides, reason) -> None:
    if "config" in overrides:
        overrides = dict(overrides)
        overrides["config"] = SimpleNamespace(
            output_root=str(tmp_path), mode=overrides["config"].mode
        )
    state = step_finalize(_state(tmp_path, **overrides))

    assert state.status == "failed"
    assert state.stop_reason == reason


@pytest.mark.skipif(not _REAL_VITIS, reason="set FPT26_REAL_VITIS_TESTS=1")
def test_real_vitis_invalid_official_task_returns_nonzero_and_reports_failure(
    tmp_path,
) -> None:
    rc = main(
        [
            "--task",
            str(_WORKSPACE_ROOT / "tasks/official/projection_bugfix"),
            "--mode",
            "baseline",
            "--output-root",
            str(tmp_path),
            "--quiet",
        ]
    )
    report_path = tmp_path / "projection_bugfix/run_report.json"
    report = json.loads(report_path.read_text())

    assert rc == 4
    assert report["status"] == "failed"
    assert report["stop_reason"] == "hidden_csim_fail"
    assert report["scoring"]["valid"] is False
    assert report["scoring"]["gate_reason"] == "hidden_csim_fail"
    trace = report["execution_trace"]
    assert trace["transcript"][0]["phase"] == "runtime_fail"
    assert trace["metered_results"][0]["return_code"] == 1
    assert "Test Case 1 Failed!" in trace["metered_results"][0]["log"]
    hidden_csim = next(
        item for item in trace["grading_results"] if item["stage"] == "hidden_csim"
    )
    assert hidden_csim["ok"] is False
    assert hidden_csim["phase"] == "runtime_fail"
    assert "Test Case 1 Failed!" in hidden_csim["log"]
    assert (tmp_path / "projection_bugfix/final_projection.cpp").is_file()
