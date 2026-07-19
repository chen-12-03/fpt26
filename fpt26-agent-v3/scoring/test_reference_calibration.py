"""Regression tests for reference calibration math and Pareto semantics."""

from __future__ import annotations

import pytest

from scoring.analyze_reference_calibration import _pareto_audit, _weight_boundary
from scoring.scoring_v3 import hardware_qor


def _report(*, latency: int, ii: int, lut: int, ff: int, dsp: int) -> dict:
    return {
        "latency_worst": latency,
        "latency_avg": latency,
        "interval_max": ii,
        "clock_period_ns": 3.17,
        "resources": {
            "LUT": lut,
            "FF": ff,
            "DSP": dsp,
            "BRAM_18K": 0,
            "URAM": 0,
        },
    }


def _record(starter: dict, reference: dict) -> dict:
    return {
        "target": {"clock_ns": 5.0},
        "starter_synth": {"report": starter},
        "reference_synth": {"report": reference},
    }


def test_clean_dotproduct_boundary_and_required_weight_grid():
    performance = 1027 / 36
    area = 1 / 32
    boundary = _weight_boundary(performance, area)
    assert boundary["kind"] == "lower"
    assert boundary["boundary"] == pytest.approx(0.5084248300102405)
    scores = {
        weight: 100 * hardware_qor(
            performance,
            area,
            performance_weight=weight,
        )
        for weight in (0.50, 0.52, 0.55, 0.60)
    }
    assert scores[0.50] == pytest.approx(73.54407246513131)
    assert scores[0.52] == pytest.approx(76.9326932852259)
    assert scores[0.55] == pytest.approx(81.54266944943632)
    assert scores[0.60] == pytest.approx(87.83250085034067)


def test_pareto_tradeoff_is_not_mislabeled_dominated():
    audit = _pareto_audit(_record(
        _report(latency=1027, ii=1025, lut=156, ff=93, dsp=2),
        _report(latency=36, ii=34, lut=1809, ff=1135, dsp=64),
    ))
    assert not audit["reference_pareto_dominated"]
    assert audit["tradeoff"]


def test_pareto_dominated_requires_all_no_better_and_one_strictly_worse():
    audit = _pareto_audit(_record(
        _report(latency=10, ii=1, lut=100, ff=100, dsp=2),
        _report(latency=11, ii=1, lut=101, ff=100, dsp=2),
    ))
    assert audit["reference_pareto_dominated"]
    assert not audit["tradeoff"]


def test_identical_reference_is_neutral_not_dominated():
    report = _report(latency=10, ii=1, lut=100, ff=100, dsp=2)
    audit = _pareto_audit(_record(report, report))
    assert not audit["reference_pareto_dominated"]
    assert not audit["tradeoff"]
