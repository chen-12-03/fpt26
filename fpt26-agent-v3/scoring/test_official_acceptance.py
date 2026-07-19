"""Regression tests for the fresh official acceptance auditor."""

from __future__ import annotations

from pathlib import Path

import pytest

from scoring.analyze_official_acceptance import (
    _assert_display_equal,
    _stage,
    _validate_api,
    _workspace_path,
)
from scoring.scoring_v3 import (
    Anchor,
    QoREvidence,
    TaskScoringConfig,
    calculate_qor_components,
    hardware_qor,
)


def _api_report(*, client: str = "OpenAICompatClient") -> dict:
    return {
        "llm": {
            "client": client,
            "model": "real-model",
            "temperature": 0.7,
            "max_tokens": 4096,
            "token_usage": {
                "complete": True,
                "request_count": 2,
                "response_count": 2,
                "failed_request_count": 0,
                "unreported_response_count": 0,
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        }
    }


def test_real_api_usage_is_accepted():
    result = _validate_api(_api_report())
    assert result["client"] == "OpenAICompatClient"
    assert result["usage"]["total_tokens"] == 120


@pytest.mark.parametrize("client", ["ScriptedClient", "MockClient", "ReplayClient"])
def test_mock_scripted_and_replay_clients_are_rejected(client: str):
    with pytest.raises(RuntimeError, match="real OpenAI-compatible client"):
        _validate_api(_api_report(client=client))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("complete", False),
        ("response_count", 1),
        ("failed_request_count", 1),
        ("unreported_response_count", 1),
        ("total_tokens", 119),
    ],
)
def test_incomplete_api_evidence_is_rejected(field: str, value):
    report = _api_report()
    report["llm"]["token_usage"][field] = value
    with pytest.raises(RuntimeError, match="incomplete or failed"):
        _validate_api(report)


def test_container_artifact_path_maps_only_inside_workspace(tmp_path: Path):
    artifact = tmp_path / "runs" / "task" / "report.xml"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("evidence")
    assert _workspace_path(
        "/workspace/runs/task/report.xml", tmp_path
    ) == artifact.resolve()
    with pytest.raises(RuntimeError, match="unexpected container artifact path"):
        _workspace_path("runs/task/report.xml", tmp_path)
    with pytest.raises(RuntimeError, match="escapes workspace"):
        _workspace_path("/workspace/../secret", tmp_path)


def test_failed_or_duplicate_tool_stage_is_rejected():
    passed = {
        "execution_trace": {
            "grading_results": [
                {"stage": "candidate_synth", "ok": True, "return_code": 0}
            ]
        }
    }
    assert _stage(passed, "candidate_synth")["ok"] is True
    passed["execution_trace"]["grading_results"][0]["return_code"] = 1
    with pytest.raises(RuntimeError, match="failed candidate_synth"):
        _stage(passed, "candidate_synth")
    passed["execution_trace"]["grading_results"] *= 2
    with pytest.raises(RuntimeError, match="exactly one"):
        _stage(passed, "candidate_synth")


def test_score_display_comparison_uses_declared_precision():
    _assert_display_equal(73.6049, 73.60, 2)
    _assert_display_equal(0.76661, 0.7666, 4)
    with pytest.raises(RuntimeError, match="disagrees"):
        _assert_display_equal(73.6049, 73.50, 2)


def test_real_dotproduct_frontier_ordering_regression():
    """Freeze the ordering observed in the fresh Vitis official run."""
    available = {
        "LUT": 1_303_680,
        "FF": 2_607_360,
        "DSP": 9_024,
        "BRAM_18K": 4_032,
        "URAM": 960,
    }
    anchor = Anchor(
        source="starter",
        valid=True,
        latency=1027,
        ii=1025,
        clock_ns=3.17,
        resources={"LUT": 156, "FF": 93, "DSP": 2, "BRAM_18K": 0, "URAM": 0},
        available=available,
    )
    cfg = TaskScoringConfig(task_id="dotProduct_optimize", task_clock_ns=5.0)

    def score(latency: int, lut: int, ff: int, dsp: int, weight: float) -> float:
        evidence = QoREvidence(
            candidate_latency=latency,
            candidate_ii=513,
            candidate_clock_ns=3.17,
            candidate_resources={
                "LUT": lut,
                "FF": ff,
                "DSP": dsp,
                "BRAM_18K": 0,
                "URAM": 0,
            },
        )
        components = calculate_qor_components(cfg, anchor, evidence)
        return 100 * hardware_qor(
            components.performance_ratio,
            components.area_ratio,
            performance_weight=weight,
        )

    baseline = 75.0
    accepted = {w: score(515, 211, 138, 4, w) for w in (0.50, 0.52, 0.55, 0.60)}
    rejected = {w: score(515, 446, 179, 4, w) for w in (0.50, 0.52, 0.55, 0.60)}
    assert accepted[0.50] < baseline
    assert all(accepted[w] > baseline for w in (0.52, 0.55, 0.60))
    assert all(rejected[w] < accepted[w] for w in accepted)
    assert accepted[0.55] == pytest.approx(76.66348201758386)
