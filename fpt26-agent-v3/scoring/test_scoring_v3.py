#!/usr/bin/env python3
"""V8 measured-cosim, capacity-integrated scoring engine — test suite.

All tasks use the single ``valid_then_optimize`` objective.
Task type labels do not affect scoring.

Usage::

    python -m pytest fpt26-agent-v3/test_scoring_v3.py -v
    python fpt26-agent-v3/test_scoring_v3.py
"""

from __future__ import annotations

import math
import os
import sys

_V3_DIR = os.path.dirname(os.path.abspath(__file__))
if _V3_DIR not in sys.path:
    sys.path.insert(0, _V3_DIR)

import pytest
from scoring_v3 import (
    RESOURCES,
    Anchor,
    QoREvidence,
    Scorecard,
    TaskScoringConfig,
    ValidityGates,
    aggregate_performance_ratio,
    area_quality,
    check_capacity,
    combine_score,
    efficiency_factor,
    grade,
    hardware_ratio,
    hardware_qor,
    performance_quality,
    ratio_quality,
    select_anchor,
    verified_available_resources,
)

U55C = {"LUT": 872640, "FF": 1745280, "DSP": 9024, "BRAM_18K": 2016, "URAM": 960}
BASE_RES = {"LUT": 100, "FF": 100, "DSP": 10, "BRAM_18K": 0, "URAM": 0}


def _gates(pass_all: bool = True) -> ValidityGates:
    return ValidityGates(
        hidden_csim_pass=pass_all, synth_pass=pass_all,
        hidden_cosim_pass=True if pass_all else None)


def _anchor(lat=100, ii=1, res=None):
    return Anchor(source="starter", valid=True, latency=lat, ii=ii,
                  clock_ns=5.0, resources=res or dict(BASE_RES),
                  available=dict(U55C), hash="abc")


def _ev(lat=50, ii=1, res=None):
    return QoREvidence(
        candidate_latency=lat, candidate_ii=ii, candidate_clock_ns=5.0,
        candidate_resources=res or dict(BASE_RES))


# ═══════════════════════════════════════════════════════════════════════════════
# ratio_quality
# ═══════════════════════════════════════════════════════════════════════════════

class TestRatioQuality:
    """1 - 1/(1+r)² — unified utility for all tasks."""

    def test_landmarks(self):
        assert ratio_quality(0) == 0.0
        assert ratio_quality(0.5) == pytest.approx(0.5556, abs=1e-3)
        assert ratio_quality(1.0) == pytest.approx(0.75, abs=1e-6)
        assert ratio_quality(2.0) == pytest.approx(0.8889, abs=1e-3)
        assert ratio_quality(4.0) == pytest.approx(0.96, abs=1e-3)

    def test_strictly_monotonic(self):
        vals = [0.1, 0.5, 1.0, 2.0, 4.0, 8.0, 27.0, 100.0, 1000.0]
        scores = [ratio_quality(v) for v in vals]
        for i in range(len(scores) - 1):
            assert scores[i] < scores[i + 1], f"Not monotonic at {vals[i]}"

    def test_no_hard_cap(self):
        assert ratio_quality(8.0) < ratio_quality(27.0) < ratio_quality(100.0)

    def test_negative_is_zero(self):
        assert ratio_quality(-1.0) == 0.0

    def test_no_nan_inf(self):
        for v in [0, 0.5, 1, 10, 100, 1e6]:
            q = ratio_quality(v)
            assert not math.isnan(q)
            assert not math.isinf(q)
            assert 0.0 <= q <= 1.0

    def test_baseline_not_perfect(self):
        """1x baseline gets 0.75 — decent but not perfect."""
        assert ratio_quality(1.0) > 0.70
        assert ratio_quality(1.0) < 0.80


class TestLogSymmetricHardwareRatio:
    """Schema 8 retains V6 raw-ratio composition before bounded utility."""

    @pytest.mark.parametrize("growth", [1.0, 1.25, 1.5, 2.0, 4.0, 10.0])
    def test_equal_speedup_and_growth_are_baseline_neutral(self, growth):
        assert hardware_ratio(growth, 1.0 / growth) == pytest.approx(1.0)
        assert hardware_qor(growth, 1.0 / growth) == pytest.approx(0.75)

    def test_speed_per_growth_controls_baseline_order(self):
        assert hardware_qor(1.6, 1.0 / 1.5) > 0.75
        assert hardware_qor(1.5, 1.0 / 1.5) == pytest.approx(0.75)
        assert hardware_qor(1.4, 1.0 / 1.5) < 0.75

    def test_no_finite_resource_growth_creates_performance_ceiling(self):
        for growth in (2.0, 4.0, 10.0, 1000.0):
            assert hardware_qor(growth * 2.0, 1.0 / growth) > 0.75


class TestCapacityEvidence:
    def test_complete_positive_integer_totals_are_verified(self):
        assert verified_available_resources(U55C) == U55C

    @pytest.mark.parametrize(
        "available",
        [
            None,
            {},
            {**U55C, "URAM": None},
            {**U55C, "URAM": 0},
            {**U55C, "URAM": 960.0},
        ],
    )
    def test_partial_or_placeholder_totals_are_not_verified(self, available):
        assert verified_available_resources(available) == {}
        assert not check_capacity(BASE_RES, available or {})

    def test_missing_capacity_fails_closed_as_required_metric(self):
        anchor = _anchor()
        anchor.available = {}
        card = grade(
            TaskScoringConfig(task_id="missing_capacity"),
            anchor,
            _ev(),
            gates=_gates(),
        )
        assert not card.valid
        assert card.gate_reason == "required_metric_missing"
        assert card.score == 0.0
        assert card.available_resources == {}

    def test_over_capacity_is_a_distinct_hard_gate(self):
        candidate = dict(BASE_RES)
        candidate["DSP"] = U55C["DSP"] + 1
        card = grade(
            TaskScoringConfig(task_id="over_capacity"),
            _anchor(),
            _ev(res=candidate),
            gates=_gates(),
        )
        assert not card.valid
        assert card.gate_reason == "resource_capacity_exceeded"
        assert card.resource_capacity_pass is False
        assert card.available_resources == U55C
        assert card.score == 0.0

    def test_gate_reason_does_not_mislabel_false_infrastructure_flag(self):
        gates = _gates()
        gates.resource_capacity_pass = False
        assert gates.first_failure == "resource_capacity_exceeded"


class TestLogSymmetricHardwareRatioExamples:
    def test_optional_ii_uses_weighted_geometric_ratio(self):
        combined = aggregate_performance_ratio(
            latency_ratio=4.0, ii_ratio=1.0, ii_applicable=True
        )
        assert combined == pytest.approx(4.0 ** 0.85)

    def test_real_stencil_near_pareto_beats_baseline(self):
        q_hw = hardware_qor(1.666837, 1.0 / 1.5)
        old_v5_q_hw = math.sqrt(
            ratio_quality(1.666837) * ratio_quality(1.0 / 1.5)
        )
        assert old_v5_q_hw < 0.75
        assert q_hw == pytest.approx(0.763006, abs=1e-6)
        assert q_hw > 0.75

    def test_real_dot_minimum_unroll_stays_below_baseline(self):
        assert hardware_qor(1.994175, 1.0 / 2.0) == pytest.approx(
            0.749635, abs=1e-6
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Anchor selection
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnchorSelection:
    """Anchor priority: starter > reference > none."""

    def test_starter_valid_uses_starter(self):
        a = select_anchor(
            starter_latency=100, starter_ii=1, starter_clock_ns=5.0,
            starter_resources=BASE_RES, starter_valid=True,
            reference_latency=80, reference_resources=BASE_RES, reference_hash="ref01",
            available_resources=U55C)
        assert a.source == "starter"
        assert a.valid
        assert a.latency == 100

    def test_starter_invalid_uses_reference(self):
        a = select_anchor(
            starter_latency=100, starter_ii=None, starter_clock_ns=None,
            starter_resources=BASE_RES, starter_valid=False,
            reference_latency=80, reference_resources=BASE_RES, reference_hash="ref01",
            available_resources=U55C)
        assert a.source == "reference"
        assert a.valid
        assert a.latency == 80
        assert a.hash == "ref01"

    def test_no_valid_anchor_rejects(self):
        a = select_anchor(
            starter_latency=None, starter_ii=None, starter_clock_ns=None,
            starter_resources={}, starter_valid=False,
            reference_latency=None, available_resources=U55C)
        assert a.source == "none"
        assert not a.valid

    def test_starter_has_correct_latency(self):
        """Starter anchor matches reference latency when given."""
        a = select_anchor(
            starter_latency=200, starter_ii=2, starter_clock_ns=5.0,
            starter_resources={"LUT": 50, "FF": 50, "DSP": 0, "BRAM_18K": 0, "URAM": 0},
            starter_valid=True, available_resources=U55C)
        assert a.latency == 200
        assert a.ii == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Same evidence, different labels → same score
# ═══════════════════════════════════════════════════════════════════════════════

class TestLabelIndependence:
    """task_type label does not affect scoring."""

    def test_optimize_repair_same_score(self):
        labels = ["optimize", "repair", "structural", "generate", "synth_fix"]
        scores = {}
        for label in labels:
            cfg = TaskScoringConfig(task_id="t", task_type=label)
            card = grade(cfg, _anchor(), _ev(), gates=_gates())
            scores[label] = card.score
        unique = set(round(s, 6) for s in scores.values())
        assert len(unique) == 1, f"All labels must give same score: {scores}"

    def test_requires_cosim_only_changes_gate(self):
        """requires_cosim changes validation, not scoring formula."""
        cfg = TaskScoringConfig(task_id="t", requires_cosim=True)
        ev = QoREvidence(
            candidate_latency=50, candidate_ii=1,
            cosim_latency=50,
            candidate_resources=dict(BASE_RES))
        # cosim pass → valid
        gates_pass = ValidityGates(hidden_csim_pass=True, synth_pass=True,
                                    hidden_cosim_pass=True)
        card_pass = grade(cfg, _anchor(), ev, gates=gates_pass)
        # cosim fail → score 0
        gates_fail = ValidityGates(hidden_csim_pass=True, synth_pass=True,
                                    hidden_cosim_pass=False)
        card_fail = grade(cfg, _anchor(), ev, gates=gates_fail)
        assert card_pass.valid
        assert card_pass.score > 0
        assert not card_fail.valid
        assert card_fail.score == 0.0

    def test_required_cosim_pass_without_measured_latency_fails_closed(self):
        cfg = TaskScoringConfig(task_id="t", requires_cosim=True)
        evidence = QoREvidence(
            candidate_latency=50,
            candidate_ii=1,
            cosim_latency=None,
            candidate_resources=dict(BASE_RES),
        )
        gates = ValidityGates(
            hidden_csim_pass=True,
            synth_pass=True,
            hidden_cosim_pass=True,
        )
        card = grade(cfg, _anchor(), evidence, gates=gates)
        assert not card.valid
        assert card.gate_reason == "required_metric_missing"

    def test_required_cosim_with_unset_gate_is_not_trivially_optional(self):
        cfg = TaskScoringConfig(task_id="t", requires_cosim=True)
        evidence = QoREvidence(
            candidate_latency=50,
            candidate_ii=1,
            cosim_latency=60,
            candidate_resources=dict(BASE_RES),
        )
        gates = ValidityGates(hidden_csim_pass=True, synth_pass=True)
        card = grade(cfg, _anchor(), evidence, gates=gates)
        assert not card.valid
        assert card.gate_reason == "hidden_cosim_fail"


# ═══════════════════════════════════════════════════════════════════════════════
# Scorecard anchor reporting
# ═══════════════════════════════════════════════════════════════════════════════

class TestScorecardAnchor:
    def test_anchor_fields_reported(self):
        a = _anchor()
        card = grade(TaskScoringConfig(task_id="t"), a, _ev(), gates=_gates())
        assert card.anchor_source == a.source
        assert card.anchor_valid
        assert card.anchor_hash == a.hash

    def test_invalid_anchor_rejected(self):
        a = Anchor(source="none", valid=False, latency=None, ii=None, clock_ns=None)
        card = grade(TaskScoringConfig(task_id="t"), a, _ev(), gates=_gates())
        assert not card.valid
        assert "no_valid_anchor" in card.gate_reason
        assert card.score == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Score behaviour: baseline, improvement, regression
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreBehaviour:
    """Baseline gets ~75, improvement raises, regression lowers."""

    def test_baseline_score(self):
        """1x latency, 1x resources → q_perf=0.75, q_area=0.75, Q_HW=0.75, score≈75."""
        a = _anchor(lat=100, res=BASE_RES)
        ev = _ev(lat=100, res=BASE_RES)  # matched baseline
        card = grade(TaskScoringConfig(task_id="t"), a, ev, gates=_gates())
        assert card.valid
        assert 70 < card.score < 80, f"Baseline should get ~75, got {card.score:.2f}"

    def test_improvement_raises_score(self):
        """Faster AND smaller → higher than baseline."""
        a = _anchor(lat=100, res={"LUT": 100, "FF": 100, "DSP": 10, "BRAM_18K": 0, "URAM": 0})
        ev = _ev(lat=50, res={"LUT": 50, "FF": 50, "DSP": 5, "BRAM_18K": 0, "URAM": 0})
        card = grade(TaskScoringConfig(task_id="t"), a, ev, gates=_gates())
        assert card.score > 75, f"Improvement should beat baseline 75, got {card.score:.2f}"

    def test_regression_lowers_score(self):
        """Slower AND larger → lower than baseline."""
        a = _anchor(lat=100, res={"LUT": 100, "FF": 100, "DSP": 10, "BRAM_18K": 0, "URAM": 0})
        ev = _ev(lat=200, res={"LUT": 200, "FF": 200, "DSP": 20, "BRAM_18K": 0, "URAM": 0})
        card = grade(TaskScoringConfig(task_id="t"), a, ev, gates=_gates())
        assert card.score < 75, f"Regression should be below baseline 75, got {card.score:.2f}"

    def test_perf_strictly_monotonic(self):
        """Fixed resources, faster → higher score."""
        cfg = TaskScoringConfig(task_id="t")
        a = _anchor(lat=100)

        def s(l):
            return grade(cfg, a, _ev(lat=l), gates=_gates()).score

        assert s(200) < s(100) < s(50) < s(10)

    def test_area_strictly_monotonic(self):
        """Fixed perf, smaller → higher score."""
        cfg = TaskScoringConfig(task_id="t")
        a = _anchor(lat=100, res={"LUT": 100, "FF": 100, "DSP": 10, "BRAM_18K": 0, "URAM": 0})

        def s(lut):
            return grade(cfg, a, _ev(lat=50, res={"LUT": lut, "FF": lut, "DSP": 5, "BRAM_18K": 0, "URAM": 0}), gates=_gates()).score

        assert s(50) > s(100) > s(200)

    def test_pareto_dominance(self):
        """A faster and smaller than B → A scores higher."""
        cfg = TaskScoringConfig(task_id="t")
        a = _anchor(lat=100, res={"LUT": 100, "FF": 100, "DSP": 10, "BRAM_18K": 0, "URAM": 0})
        ev_a = _ev(lat=10, res={"LUT": 50, "FF": 50, "DSP": 5, "BRAM_18K": 0, "URAM": 0})
        ev_b = _ev(lat=50, res={"LUT": 80, "FF": 80, "DSP": 8, "BRAM_18K": 0, "URAM": 0})
        assert grade(cfg, a, ev_a, gates=_gates()).score > grade(cfg, a, ev_b, gates=_gates()).score

    def test_no_hard_cap(self):
        """8x < 27x < 100x, all else equal."""
        cfg = TaskScoringConfig(task_id="t")
        a = _anchor(lat=800, res={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        s8 = grade(cfg, a, _ev(lat=100, res=a.resources), gates=_gates()).score
        s27 = grade(cfg, a, _ev(lat=30, res=a.resources), gates=_gates()).score
        s100 = grade(cfg, a, _ev(lat=8, res=a.resources), gates=_gates()).score
        assert s8 < s27 < s100

    def test_extreme_bloat_penalised(self):
        """Good speedup + massive area → score stays low."""
        cfg = TaskScoringConfig(task_id="t")
        a = _anchor(lat=100, res={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        ev = _ev(lat=10, res={"LUT": 50000, "FF": 200000, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(cfg, a, ev, gates=_gates())
        assert card.score < 30, f"Extreme bloat score={card.score:.2f} should be < 30"


# ═══════════════════════════════════════════════════════════════════════════════
# Validity gates and infrastructure
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidityGates:
    def test_csim_fail_zero(self):
        a = _anchor()
        ev = _ev()
        gates = ValidityGates(hidden_csim_pass=False, synth_pass=True)
        card = grade(TaskScoringConfig(task_id="t"), a, ev, gates=gates)
        assert card.score == 0.0

    def test_synth_fail_zero(self):
        gates = ValidityGates(hidden_csim_pass=True, synth_pass=False)
        card = grade(TaskScoringConfig(task_id="t"), _anchor(), _ev(), gates=gates)
        assert card.score == 0.0

    def test_cosim_fail_zero(self):
        cfg = TaskScoringConfig(task_id="t", requires_cosim=True)
        gates = ValidityGates(hidden_csim_pass=True, synth_pass=True, hidden_cosim_pass=False)
        card = grade(cfg, _anchor(), _ev(), gates=gates)
        assert card.score == 0.0

    def test_infrastructure_error_distinct(self):
        ev = QoREvidence(infrastructure_error=True, infrastructure_reason="timeout",
                         candidate_latency=50, candidate_resources=dict(BASE_RES))
        card = grade(TaskScoringConfig(task_id="t"), _anchor(), ev, gates=_gates())
        assert "evaluation_invalid" in card.gate_reason
        assert card.stage == "infrastructure_error"


# ═══════════════════════════════════════════════════════════════════════════════
# Score always in range
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreRange:
    def test_score_in_0_100(self):
        cfg = TaskScoringConfig(task_id="t")
        a = _anchor(lat=100, res={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        cases = [
            (10, {"LUT": 10, "FF": 10, "DSP": 0, "BRAM_18K": 0, "URAM": 0}),
            (100, {"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0}),
            (200, {"LUT": 500, "FF": 500, "DSP": 0, "BRAM_18K": 0, "URAM": 0}),
            (50, {"LUT": 50000, "FF": 200000, "DSP": 0, "BRAM_18K": 0, "URAM": 0}),
        ]
        for lat, res in cases:
            ev = QoREvidence(candidate_latency=lat, candidate_resources=dict(res))
            card = grade(cfg, a, ev, gates=_gates())
            assert 0.0 <= card.score <= 100.0
            assert not math.isnan(card.score)
            assert not math.isinf(card.score)

    def test_scorecard_audit_fields(self):
        card = grade(TaskScoringConfig(task_id="audit"), _anchor(), _ev(), gates=_gates())
        assert card.schema_version == 9
        assert card.latency_ratio > 0
        assert card.performance_ratio > 0
        assert card.q_perf > 0
        assert card.q_area > 0
        assert card.area_ratio > 0
        assert card.hardware_ratio > 0
        assert card.bottleneck_resource in RESOURCES
        assert len(card.growth_by_resource) == len(RESOURCES)
        assert card.efficiency > 0
        assert card.utility_name == "1-1/(1+r)²"


# ═══════════════════════════════════════════════════════════════════════════════
# Efficiency + combine
# ═══════════════════════════════════════════════════════════════════════════════

class TestEfficiency:
    def test_zero_cost_is_one(self):
        assert efficiency_factor(0, 100) == 1.0

    def test_full_cost_is_0_9(self):
        assert efficiency_factor(100, 100) == 0.9

    def test_full_both_is_0_8(self):
        assert efficiency_factor(100, 100, 3600, 3600) == 0.8

    def test_never_below_0_8(self):
        assert efficiency_factor(99999, 100, 99999, 3600) == 0.8


# ═══════════════════════════════════════════════════════════════════════════════
# 3 real FPT26 tasks
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealTasks:
    def test_projection_bugfix(self):
        """Repair label: fix passes, no regression, 10/20 credits.
        ratio_quality(1)=0.75, Q_HW=0.75, E=0.95, score=71.25."""
        cfg = TaskScoringConfig(task_id="projection_bugfix", task_type="repair",
                                 difficulty=2, budget_limit=20)
        a = Anchor(source="starter", valid=True, latency=135, ii=1, clock_ns=5.0,
                    resources={"LUT": 406, "FF": 231, "DSP": 0, "BRAM_18K": 0, "URAM": 0},
                    available=dict(U55C), hash="abc")
        ev = QoREvidence(candidate_latency=135, candidate_ii=1,
                         candidate_resources={"LUT": 406, "FF": 231, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(cfg, a, ev, cost_spent=10, gates=_gates())

        print(f"\nprojection_bugfix V8:")
        print(card.render())

        assert card.valid
        # Baseline match: q_perf=0.75, q_area=0.75, Q_HW=0.75, E=0.95
        assert card.q_perf == pytest.approx(0.75, abs=0.01)
        assert card.q_area == pytest.approx(0.75, abs=0.01)
        assert card.efficiency == pytest.approx(0.95, abs=0.01)
        assert 68 < card.score < 75

    def test_dotProduct_optimize(self):
        """Optimize label: 27x speedup, massive area bloat."""
        cfg = TaskScoringConfig(task_id="dotProduct_optimize", task_type="optimize",
                                 difficulty=3, budget_limit=40)
        a = Anchor(source="starter", valid=True, latency=1027, ii=1025, clock_ns=5.0,
                    resources={"LUT": 156, "FF": 93, "DSP": 2, "BRAM_18K": 0, "URAM": 0},
                    available=dict(U55C), hash="abc")
        ev = QoREvidence(candidate_latency=38, candidate_ii=39, candidate_clock_ns=5.0,
                         candidate_resources={"LUT": 13189, "FF": 54194, "DSP": 64, "BRAM_18K": 0, "URAM": 0})
        card = grade(cfg, a, ev, cost_spent=15, gates=_gates())

        print(f"\ndotProduct_optimize V8:")
        print(card.render())

        assert card.valid
        assert card.anchor_source == "starter"
        # Good perf, terrible area
        assert card.q_perf > 0.95
        assert card.bottleneck_resource == "FF"
        assert card.area_growth > 500
        assert card.q_area < 0.01
        assert 25 < card.score < 40

    def test_dotProduct_four_candidates(self):
        """Ranking follows measured speedup/worst-growth, not labels."""
        cfg = TaskScoringConfig(task_id="dp", task_type="optimize", difficulty=3, budget_limit=40)
        a = Anchor(source="starter", valid=True, latency=1027, ii=1025, clock_ns=5.0,
                    resources={"LUT": 156, "FF": 93, "DSP": 2, "BRAM_18K": 0, "URAM": 0},
                    available=dict(U55C), hash="abc")

        def c(lat, ii, lut, ff, dsp):
            ev = QoREvidence(candidate_latency=lat, candidate_ii=ii, candidate_clock_ns=5.0,
                             candidate_resources={"LUT": lut, "FF": ff, "DSP": dsp, "BRAM_18K": 0, "URAM": 0})
            return grade(cfg, a, ev, cost_spent=15, gates=_gates())

        ca = c(38, 39, 13189, 54194, 64)       # A: real run
        cb = c(100, 102, 500, 200, 4)           # B: efficient
        cc = c(68, 68, 2000, 800, 8)            # C: balanced
        cd = c(10, 10, 50000, 200000, 200)      # D: extreme

        print(f"\ndotProduct V8 — 4 candidates:")
        for name, card in [("A", ca), ("B", cb), ("C", cc), ("D", cd)]:
            print(f"  {name}: score={card.score:.2f}  q_perf={card.q_perf:.4f}  "
                  f"q_area={card.q_area:.4f}  bottleneck={card.bottleneck_resource}")

        # D is far larger than A, but its 102.7x speedup / 2150x worst growth
        # is slightly better than A's 27x / 583x. Both remain far below the
        # 1x baseline; the log-symmetric formula preserves that ratio order.
        assert cb.score > cc.score > cd.score > ca.score, (
            f"B={cb.score:.2f} C={cc.score:.2f} A={ca.score:.2f} D={cd.score:.2f}"
        )
        assert ca.q_hw < 0.5
        assert cd.q_hw < 0.5

    def test_residual_stream_deadlock(self):
        """Structural: cosim pass, modest speedup, area improved."""
        cfg = TaskScoringConfig(task_id="residual_stream_deadlock", task_type="structural",
                                 difficulty=4, budget_limit=80, requires_cosim=True)
        a = Anchor(source="starter", valid=True, latency=135, ii=1, clock_ns=5.0,
                    resources={"LUT": 539, "FF": 248, "DSP": 0, "BRAM_18K": 0, "URAM": 0},
                    available=dict(U55C), hash="abc")
        ev = QoREvidence(candidate_latency=97, candidate_ii=1,
                         cosim_latency=97,
                         candidate_resources={"LUT": 406, "FF": 231, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        gates = ValidityGates(hidden_csim_pass=True, synth_pass=True, hidden_cosim_pass=True)
        card = grade(cfg, a, ev, cost_spent=66, gates=gates)

        print(f"\nresidual_stream_deadlock V8:")
        print(card.render())

        assert card.valid
        assert card.acceleration_source == "cosim"
        # 1.39x speedup → latency_ratio ≈ 1.39
        assert 1.3 < card.latency_ratio < 1.5
        # Area improved → q_area > 0.75
        assert card.q_area > 0.75
        # E = 1 - 0.1*(66/80) = 0.9175
        assert card.efficiency == pytest.approx(0.9175, abs=0.01)
        assert 70 < card.score < 85, f"Expected 70-85, got {card.score:.2f}"


# ═══════════════════════════════════════════════════════════════════════════════
# CLI runner
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  FPT26 V8 Measured-CoSim Scoring Engine — Test Suite")
    print("=" * 70)

    trt = TestRealTasks()
    for name, fn in [("projection_bugfix", trt.test_projection_bugfix),
                      ("dotProduct_optimize", trt.test_dotProduct_optimize),
                      ("dotProduct 4-way ranking", trt.test_dotProduct_four_candidates),
                      ("residual_stream_deadlock", trt.test_residual_stream_deadlock)]:
        print(f"\n{'─'*70}\n  {name}\n{'─'*70}")
        fn()

    print("\n" + "=" * 70)
    print("  Running full pytest suite...")
    print("=" * 70)
    try:
        pytest.main([__file__, "-v", "--tb=short"])
    except SystemExit:
        pass
