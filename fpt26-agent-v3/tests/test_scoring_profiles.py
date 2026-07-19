"""Regression coverage for declared balanced and extreme-speed profiles."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent.agents.optimize import _score_candidate
from agent.main import parse_args
from agent.reporting import write_run_report
from scoring.profiles import (
    PROFILE_SCHEMA_VERSION,
    SCORING_PROFILE_CHOICES,
    grade_with_profile,
    resolve_scoring_profile,
)
from scoring.scoring_v3 import (
    Anchor,
    QoREvidence,
    TaskScoringConfig,
    ValidityGates,
    grade,
)


_AVAILABLE = {
    "LUT": 500_000,
    "FF": 500_000,
    "DSP": 500_000,
    "BRAM_18K": 500_000,
    "URAM": 500_000,
}


def _gates() -> ValidityGates:
    return ValidityGates(hidden_csim_pass=True, synth_pass=True)


def _cfg() -> TaskScoringConfig:
    return TaskScoringConfig(task_id="profile_probe", task_clock_ns=5.0)


def _anchor(resources: int = 100) -> Anchor:
    return Anchor(
        source="starter",
        valid=True,
        latency=100,
        ii=100,
        clock_ns=5.0,
        resources={key: resources for key in _AVAILABLE},
        available=dict(_AVAILABLE),
    )


def _evidence(*, latency: int, resources: int) -> QoREvidence:
    return QoREvidence(
        candidate_latency=latency,
        candidate_ii=latency,
        candidate_clock_ns=5.0,
        candidate_resources={key: resources for key in _AVAILABLE},
    )


def _report(*, latency: int, resources: int) -> SimpleNamespace:
    return SimpleNamespace(
        latency_worst=latency,
        latency_avg=latency,
        interval_max=latency,
        clock_period_ns=5.0,
        resources={key: resources for key in _AVAILABLE},
        available=dict(_AVAILABLE),
        loop_metrics=[],
    )


def test_public_profile_names_and_weights_are_explicit() -> None:
    assert SCORING_PROFILE_CHOICES == (
        "balanced",
        "extreme_speed",
        "extreme_speed_capped",
    )
    balanced = resolve_scoring_profile("balanced")
    speed = resolve_scoring_profile("extreme_speed")
    capped = resolve_scoring_profile("extreme_speed_capped")
    assert (balanced.performance_weight, balanced.area_weight) == (0.55, 0.45)
    assert (speed.performance_weight, speed.area_weight) == (0.70, 0.30)
    assert not speed.cap_area_reward
    assert capped.cap_area_reward
    with pytest.raises(ValueError, match="unknown scoring profile"):
        resolve_scoring_profile("fastest_seen_after_run")


def test_balanced_profile_is_numerically_identical_to_frozen_schema10() -> None:
    evidence = _evidence(latency=50, resources=200)
    frozen = grade(
        _cfg(), _anchor(), evidence,
        cost_spent=7, wall_time_s=31.2345, gates=_gates(),
    )
    profiled = grade_with_profile(
        _cfg(), _anchor(), evidence,
        scoring_profile="balanced",
        cost_spent=7, wall_time_s=31.2345, gates=_gates(),
    )
    assert profiled.schema_version == PROFILE_SCHEMA_VERSION
    assert profiled.scoring_profile == "balanced"
    assert profiled.performance_weight == 0.55
    assert profiled.area_weight == 0.45
    assert profiled.area_reward_capped is False
    assert profiled.hardware_ratio == frozen.hardware_ratio
    assert profiled.q_hw == frozen.q_hw
    assert profiled.score == frozen.score


def test_extreme_speed_changes_only_the_tradeoff_aggregation() -> None:
    # 2x faster but 4x worst-resource growth: below neutral in balanced mode,
    # above neutral at the proposed 0.70/0.30 speed weight.
    evidence = _evidence(latency=50, resources=400)
    balanced = grade_with_profile(
        _cfg(), _anchor(), evidence,
        scoring_profile="balanced", gates=_gates(),
    )
    speed = grade_with_profile(
        _cfg(), _anchor(), evidence,
        scoring_profile="extreme_speed", gates=_gates(),
    )
    assert balanced.performance_ratio == speed.performance_ratio == 2.0
    assert balanced.area_ratio == speed.area_ratio == 0.25
    assert balanced.growth_by_resource == speed.growth_by_resource
    assert balanced.q_hw == pytest.approx(0.6860, abs=1e-4)
    assert speed.q_hw == pytest.approx(0.7670, abs=1e-4)
    assert balanced.q_hw < 0.75 < speed.q_hw


def test_capped_area_reward_prevents_area_savings_from_hiding_slowdown() -> None:
    # 20% slower with 10x resource savings.
    evidence = _evidence(latency=125, resources=10)
    uncapped = grade_with_profile(
        _cfg(), _anchor(), evidence,
        scoring_profile="extreme_speed", gates=_gates(),
    )
    capped = grade_with_profile(
        _cfg(), _anchor(), evidence,
        scoring_profile="extreme_speed_capped", gates=_gates(),
    )
    assert uncapped.area_ratio == capped.area_ratio == 10.0
    assert uncapped.effective_area_ratio == 10.0
    assert capped.effective_area_ratio == 1.0
    assert uncapped.q_hw == pytest.approx(0.8635, abs=1e-4)
    assert capped.q_hw == pytest.approx(0.7094, abs=1e-4)
    assert uncapped.q_hw > 0.75 > capped.q_hw


def test_profiles_cannot_bypass_capacity_gate() -> None:
    evidence = _evidence(latency=1, resources=500_001)
    for profile in SCORING_PROFILE_CHOICES:
        card = grade_with_profile(
            _cfg(), _anchor(), evidence,
            scoring_profile=profile, gates=_gates(),
        )
        assert not card.valid
        assert card.gate_reason == "resource_capacity_exceeded"
        assert card.score == 0.0
        assert card.scoring_profile == profile


def test_optimizer_proxy_uses_the_selected_profile() -> None:
    task = SimpleNamespace(
        id="profile_probe",
        type="optimize",
        difficulty=1,
        requires_cosim=False,
        budget=40,
        clock_ns=5.0,
    )
    starter = _report(latency=100, resources=100)
    candidate = _report(latency=50, resources=400)
    balanced = _score_candidate(task, starter, candidate, "balanced")
    speed = _score_candidate(task, starter, candidate, "extreme_speed")
    assert balanced.q_hw < 0.75 < speed.q_hw


def test_cli_defaults_to_balanced_and_accepts_both_speed_variants() -> None:
    default = parse_args(["--task", "/tmp/task", "--mode", "optimize"])
    assert default.scoring_profile == "balanced"
    for profile in ("extreme_speed", "extreme_speed_capped"):
        parsed = parse_args([
            "--task", "/tmp/task", "--mode", "optimize",
            "--scoring-profile", profile,
        ])
        assert parsed.scoring_profile == profile


def test_run_report_records_profile_weights_and_effective_area(tmp_path) -> None:
    card = grade_with_profile(
        _cfg(), _anchor(), _evidence(latency=125, resources=10),
        scoring_profile="extreme_speed_capped", gates=_gates(),
    )
    task = SimpleNamespace(
        id="profile_probe", type="optimize", difficulty=1,
        requires_cosim=False,
    )
    state = SimpleNamespace(
        task=task,
        config=SimpleNamespace(
            output_root=str(tmp_path), mode="optimize", competition=False,
            scoring_profile="extreme_speed_capped",
        ),
        server=SimpleNamespace(
            budget=SimpleNamespace(total=40, spent=0),
            transcript=[], run_root=tmp_path / "profile_probe/agent",
        ),
        results=[], metadata={}, llm=None,
        scorecard=card, ref_scorecard=card,
        status="completed", stop_reason="",
        csim_ok=True, synth_ok=True, cosim_ok=False,
        best_latency=125,
    )
    report = json.loads(write_run_report(state).read_text())
    assert report["scoring_profile"] == "extreme_speed_capped"
    assert report["scoring"]["schema_version"] == PROFILE_SCHEMA_VERSION
    assert report["scoring"]["scoring_profile"] == "extreme_speed_capped"
    assert report["scoring"]["performance_weight"] == 0.70
    assert report["scoring"]["area_weight"] == 0.30
    assert report["scoring"]["area_reward_capped"] is True
    assert report["scoring"]["area_ratio"] == 10.0
    assert report["scoring"]["effective_area_ratio"] == 1.0
    assert report["scoring_vs_reference"]["area_ratio"] == 10.0
    assert report["scoring_vs_reference"]["effective_area_ratio"] == 1.0
