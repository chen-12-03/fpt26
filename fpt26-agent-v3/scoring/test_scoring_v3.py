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
# Edge case tests: clock, II, extreme ratios, multi-resource
# ═══════════════════════════════════════════════════════════════════════════════

class TestClockDegradation:
    """Effective latency = max(task_clock, estimated_clock) × cycles."""

    def test_clock_degradation_penalizes_cycle_improvement(self):
        """2x fewer cycles but 3x worse clock → effective speedup < 2x."""
        cfg = TaskScoringConfig(task_id="clk", task_clock_ns=5.0)
        a = _anchor(lat=200, res={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        # Anchor: 5ns × 200 = 1000ns  |  Candidate: 10ns × 100 = 1000ns → same effective time
        ev = QoREvidence(candidate_latency=100, candidate_ii=1, candidate_clock_ns=10.0,
                         candidate_resources={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(cfg, a, ev, cost_spent=0, gates=_gates())
        # Same effective time → latency_ratio = 1.0
        assert card.latency_ratio == pytest.approx(1.0, abs=0.01)
        assert card.q_hw == pytest.approx(0.75, abs=0.01)

    def test_clock_improvement_boosts_effective_speedup(self):
        """2x fewer cycles AND 2x faster clock → 4x effective speedup."""
        cfg = TaskScoringConfig(task_id="clk2", task_clock_ns=5.0)
        a = _anchor(lat=200, res={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        ev = QoREvidence(candidate_latency=100, candidate_clock_ns=2.5,
                         candidate_resources={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(cfg, a, ev, cost_spent=0, gates=_gates())
        # Anchor: 5ns × 200 = 1000ns  |  Candidate: max(5,2.5)=5ns × 100 = 500ns → 2x effective
        assert card.latency_ratio == pytest.approx(2.0, abs=0.01)
        assert card.q_perf > 0.75

    def test_task_clock_floors_candidate_clock(self):
        """Candidate clock below task target → task_clock is used."""
        cfg = TaskScoringConfig(task_id="clk3", task_clock_ns=5.0)
        a = _anchor(lat=200, res={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        ev = QoREvidence(candidate_latency=100, candidate_clock_ns=3.0,
                         candidate_resources={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(cfg, a, ev, cost_spent=0, gates=_gates())
        # Anchor: 5ns × 200 = 1000ns  |  Candidate: max(5,3)=5ns × 100 = 500ns
        assert card.latency_ratio == pytest.approx(2.0, abs=0.01)


class TestIIWeighting:
    """II ratio affects performance_ratio via weighted geometric mean."""

    def test_ii_applicable_uses_weighted_geometric_mean(self):
        """With II applicable, performance_ratio = lat^0.85 × ii^0.15."""
        cfg = TaskScoringConfig(task_id="ii1")
        a = _anchor(lat=100, ii=10, res={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        ev = QoREvidence(candidate_latency=50, candidate_ii=5,
                         candidate_resources={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(cfg, a, ev, cost_spent=0, gates=_gates(), ii_applicable=True)
        # lat_ratio = 2.0, ii_ratio = 2.0
        # perf_ratio = 2.0^0.85 × 2.0^0.15 = 2.0
        assert card.performance_ratio == pytest.approx(2.0, abs=0.01)
        # q_perf should match ratio_quality(perf_ratio)
        assert card.q_perf == pytest.approx(ratio_quality(2.0), abs=0.01)

    def test_ii_improvement_alone_is_weighted(self):
        """Only II improves → smaller perf gain than latency improvement."""
        cfg = TaskScoringConfig(task_id="ii2")
        a = _anchor(lat=100, ii=10, res={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        ev = QoREvidence(candidate_latency=100, candidate_ii=5,  # latency unchanged
                         candidate_resources={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(cfg, a, ev, cost_spent=0, gates=_gates(), ii_applicable=True)
        # lat_ratio=1.0, ii_ratio=2.0 → perf_ratio = 1.0^0.85 × 2.0^0.15 = 1.1096
        assert 1.10 < card.performance_ratio < 1.12
        assert card.q_perf > 0.75  # slight improvement

    def test_ii_not_applicable_ignores_ii(self):
        """When ii_applicable=False, II ratio is not used."""
        cfg = TaskScoringConfig(task_id="ii3")
        a = _anchor(lat=100, ii=10, res={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        ev = QoREvidence(candidate_latency=100, candidate_ii=200,  # II regression
                         candidate_resources={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(cfg, a, ev, cost_spent=0, gates=_gates(), ii_applicable=False)
        # II ignored → perf_ratio = 1.0, q_perf = 0.75
        assert card.performance_ratio == 1.0
        assert card.q_perf == 0.75


class TestExtremeRatios:
    """Scoring remains continuous at extreme ratio values."""

    def test_very_large_speedup_modest_area(self):
        """100x speedup, 2x area → high score, no ceiling."""
        cfg = TaskScoringConfig(task_id="extreme1")
        a = _anchor(lat=10000, res={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        ev = QoREvidence(candidate_latency=100, candidate_ii=1,
                         candidate_resources={"LUT": 200, "FF": 200, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(cfg, a, ev, cost_spent=10, gates=_gates())
        # perf_ratio ≈ 100, area_ratio ≈ 0.5, hw_ratio ≈ sqrt(50) ≈ 7.07
        # q_hw = ratio_quality(7.07) > 0.98
        assert card.q_hw > 0.95
        assert card.score > 90

    def test_very_large_area_modest_speedup(self):
        """2x speedup, 50x area → low score."""
        cfg = TaskScoringConfig(task_id="extreme2")
        a = _anchor(lat=100, res={"LUT": 10, "FF": 10, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        ev = QoREvidence(candidate_latency=50, candidate_ii=1,
                         candidate_resources={"LUT": 500, "FF": 500, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(cfg, a, ev, cost_spent=10, gates=_gates())
        # perf_ratio = 2.0, area_ratio = 1/50 = 0.02, hw_ratio = sqrt(0.04) = 0.2
        # q_hw = ratio_quality(0.2) = 1 - 1/1.44 = 0.3056
        assert card.q_hw < 0.4
        assert card.score < 40

    def test_both_extreme_cancels(self):
        """100x speedup, 100x area → approximately neutral."""
        cfg = TaskScoringConfig(task_id="extreme3")
        a = _anchor(lat=10000, res={"LUT": 1, "FF": 1, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        ev = QoREvidence(candidate_latency=100, candidate_ii=1,
                         candidate_resources={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(cfg, a, ev, cost_spent=10, gates=_gates())
        # perf_ratio ≈ 100, area_ratio ≈ 0.01, hw_ratio ≈ sqrt(1.0) = 1.0
        assert card.hardware_ratio == pytest.approx(1.0, abs=0.01)
        assert card.q_hw == pytest.approx(0.75, abs=0.01)

    def test_regression_with_very_small_latency_ratio(self):
        """Very small latency_ratio → q_hw near zero (continuous, not zero)."""
        cfg = TaskScoringConfig(task_id="extreme4")
        a = _anchor(lat=100, res={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        ev = QoREvidence(candidate_latency=100000, candidate_ii=1,
                         candidate_resources={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(cfg, a, ev, cost_spent=10, gates=_gates())
        # latency_ratio ≈ 0.001, hw_ratio ≈ sqrt(0.001) ≈ 0.0316
        # ratio_quality is asymptotic → q_hw ≈ 0.06, not exactly 0
        assert card.q_hw < 0.1
        assert card.score < 10
        assert card.score > 0  # not exactly zero — ratio_quality is continuous


class TestMultiResourceGrowth:
    """Bottleneck = max growth among significant resources."""

    def test_bottleneck_is_worst_resource(self):
        """LUT 3x, FF 2x, DSP 1x → bottleneck = LUT at 3x."""
        a = _anchor(res={"LUT": 100, "FF": 100, "DSP": 5, "BRAM_18K": 0, "URAM": 0})
        ev = _ev(res={"LUT": 300, "FF": 200, "DSP": 5, "BRAM_18K": 0, "URAM": 0})
        card = grade(TaskScoringConfig(task_id="multi1"), a, ev, cost_spent=0, gates=_gates())
        assert card.bottleneck_resource == "LUT"
        assert card.area_growth == pytest.approx(3.0, abs=0.01)
        assert card.growth_by_resource["LUT"] == pytest.approx(3.0, abs=0.01)
        assert card.growth_by_resource["FF"] == pytest.approx(2.0, abs=0.01)

    def test_multiple_near_bottleneck_only_max_counts(self):
        """LUT 3.0x, FF 2.9x → only LUT matters (max)."""
        a = _anchor(res={"LUT": 100, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        ev = _ev(res={"LUT": 300, "FF": 290, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(TaskScoringConfig(task_id="multi2"), a, ev, cost_spent=0, gates=_gates())
        assert card.bottleneck_resource == "LUT"
        # FF at 2.9x doesn't matter — only LUT at 3.0x drives area_quality
        assert card.area_growth == pytest.approx(3.0, abs=0.01)

    def test_all_zero_resources_with_floor(self):
        """All resources zero → floor=1.0 → all growth=1.0."""
        a = _anchor(res={"LUT": 0, "FF": 0, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        ev = _ev(res={"LUT": 0, "FF": 0, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(TaskScoringConfig(task_id="multi3"), a, ev, cost_spent=0, gates=_gates())
        for r in RESOURCES:
            assert card.growth_by_resource[r] == pytest.approx(1.0, abs=0.01)
        assert card.area_growth == pytest.approx(1.0, abs=0.01)

    def test_zero_to_nonzero_first_unit_is_free(self):
        """V9: 0→1 of any resource = 1.0x growth (floor=1.0)."""
        a = _anchor(res={"LUT": 0, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        ev = _ev(res={"LUT": 1, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(TaskScoringConfig(task_id="multi4"), a, ev, cost_spent=0, gates=_gates())
        # Going from 0→1 LUT with floor=1.0 means both normalized to 1.0 → growth=1.0
        assert card.growth_by_resource["LUT"] == pytest.approx(1.0, abs=0.01)
        assert card.area_growth == pytest.approx(1.0, abs=0.01)

    def test_zero_to_many_is_count_ratio(self):
        """V9: 0→5 of any resource = 5.0x growth (natural count ratio)."""
        a = _anchor(res={"LUT": 0, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        ev = _ev(res={"LUT": 5, "FF": 100, "DSP": 0, "BRAM_18K": 0, "URAM": 0})
        card = grade(TaskScoringConfig(task_id="multi5"), a, ev, cost_spent=0, gates=_gates())
        # anchor LUT → max(0,1.0)=1.0, candidate LUT → max(5,1.0)=5.0, ratio=5.0
        assert card.growth_by_resource["LUT"] == pytest.approx(5.0, abs=0.01)
        assert card.area_growth == pytest.approx(5.0, abs=0.01)


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
