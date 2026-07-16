from types import SimpleNamespace

from agent.agents.optimize import (
    OptimizeAgent,
    _candidate_fingerprint,
    _diagnose,
    _is_minimum_unroll_frontier,
    _latest_successful_synth,
    _rejection_feedback,
    _score_candidate,
)


def _report(
    *,
    latency: int,
    ii: int,
    clock: float,
    lut: int,
    ff: int,
    dsp: int,
    pipeline_type: str | None = None,
    loop_metrics: list[dict] | None = None,
):
    return SimpleNamespace(
        latency_worst=latency,
        latency_avg=latency,
        interval_max=ii,
        clock_period_ns=clock,
        resources={"LUT": lut, "FF": ff, "DSP": dsp, "BRAM_18K": 0, "URAM": 0},
        pipeline_type=pipeline_type,
        loop_metrics=loop_metrics or [],
    )


def test_scorer_aligned_quality_rejects_cycle_only_area_explosion() -> None:
    task = SimpleNamespace(
        id="dotProduct_optimize",
        type="optimize",
        difficulty=3,
        requires_cosim=False,
        budget=40,
        clock_ns=5.0,
    )
    starter = _report(latency=1027, ii=1025, clock=3.17, lut=156, ff=93, dsp=2)
    extreme = _report(latency=34, ii=32, clock=31.133, lut=11817, ff=1561, dsp=64)

    starter_card = _score_candidate(task, starter, starter)
    extreme_card = _score_candidate(task, starter, extreme)

    assert starter_card.q_hw == 0.75
    assert extreme_card.q_hw == 0.1585
    assert extreme_card.q_hw < starter_card.q_hw


def test_scorer_aligned_quality_accepts_real_improvement_without_area_growth() -> None:
    task = SimpleNamespace(
        id="balanced",
        type="optimize",
        difficulty=3,
        requires_cosim=False,
        budget=40,
        clock_ns=5.0,
    )
    starter = _report(latency=1000, ii=1000, clock=5.0, lut=200, ff=100, dsp=2)
    balanced = _report(latency=500, ii=500, clock=5.0, lut=200, ff=100, dsp=2)

    starter_card = _score_candidate(task, starter, starter)
    balanced_card = _score_candidate(task, starter, balanced)

    assert balanced_card.q_hw > starter_card.q_hw


def test_rejection_feedback_contains_metrics_and_pragma_evidence() -> None:
    task = SimpleNamespace(
        id="dotProduct_optimize",
        type="optimize",
        difficulty=3,
        requires_cosim=False,
        budget=40,
        clock_ns=5.0,
    )
    starter = _report(latency=1027, ii=1025, clock=3.17, lut=156, ff=93, dsp=2)
    rejected = _report(
        latency=342, ii=16, clock=3.17, lut=103858, ff=117342, dsp=128
    )
    card = _score_candidate(task, starter, rejected)
    code = """void dotProduct() {
#pragma HLS ARRAY_PARTITION variable=a complete
#pragma HLS UNROLL factor=64
}
"""

    feedback = _rejection_feedback(card, rejected, code, best_q_hw=0.75)

    assert feedback["status"] == "REJECTED_BY_SCORING_V3_Q_HW"
    assert feedback["candidate_q_hw"] == 0.0385
    assert feedback["current_best_q_hw"] == 0.75
    assert feedback["bottleneck_resource"] in {"LUT", "FF"}
    assert feedback["candidate_pragmas"] == [
        "#pragma HLS ARRAY_PARTITION variable=a complete",
        "#pragma HLS UNROLL factor=64",
    ]
    assert "Increasing any UNROLL or ARRAY_PARTITION factor" in feedback[
        "directional_constraint"
    ]
    assert "Do not increase or repeat" in feedback["required_next_action"]
    assert "return the current editable kernel unchanged" in feedback[
        "required_next_action"
    ]


def test_latest_successful_synth_ignores_failures_and_other_tools() -> None:
    older = SimpleNamespace(kind="synth", ok=True, report=object())
    failed = SimpleNamespace(kind="synth", ok=False, report=None)
    csim = SimpleNamespace(kind="csim", ok=True, report=None)

    assert _latest_successful_synth([older, failed, csim]) is older
    assert _latest_successful_synth([failed, csim]) is None


def test_diagnosis_uses_loop_ii_not_top_function_interval() -> None:
    starter = _report(
        latency=1027,
        ii=1025,
        clock=3.17,
        lut=156,
        ff=93,
        dsp=2,
        pipeline_type="loop auto-rewind stp (delay=1 cycles)",
        loop_metrics=[
            {
                "name": "VITIS_LOOP_7_1",
                "trip_count": 1024,
                "latency": 1025,
                "pipeline_ii": 1,
                "pipeline_depth": 3,
            }
        ],
    )

    diagnosis = _diagnose(SimpleNamespace(report=starter))

    assert "PipelineII=1 is already optimal" in diagnosis
    assert "TopInterval=1025 is the function transaction interval" in diagnosis
    assert "partial UNROLL factor=2 inside that loop body" in diagnosis
    assert "II=1025>1" not in diagnosis


def test_candidate_fingerprint_ignores_comments_and_layout_not_factor() -> None:
    first = """// first explanation
for (int i = 0; i < n; i++) {
    #pragma HLS UNROLL factor=2
    sum += a[i];
}
"""
    repeated = """/* different explanation */
for (int i = 0; i < n; i++) {
#pragma   HLS   UNROLL   factor=2
    sum += a[i]; // same operation
}
"""
    different = repeated.replace("factor=2", "factor=4")

    assert _candidate_fingerprint(first) == _candidate_fingerprint(repeated)
    assert _candidate_fingerprint(first) != _candidate_fingerprint(different)


def test_optimize_skips_tools_for_semantically_repeated_rejection() -> None:
    task = SimpleNamespace(
        id="dotProduct_optimize",
        type="optimize",
        difficulty=3,
        requires_cosim=False,
        budget=40,
        clock_ns=5.0,
        description="",
        headers={},
        top="top",
        kernel_name="top.cpp",
    )
    starter_report = _report(
        latency=1027,
        ii=1025,
        clock=3.17,
        lut=156,
        ff=93,
        dsp=2,
        pipeline_type="loop auto-rewind stp",
        loop_metrics=[
            {
                "name": "loop",
                "trip_count": 1024,
                "latency": 1025,
                "pipeline_ii": 1,
            }
        ],
    )
    rejected_report = _report(
        latency=515,
        ii=513,
        clock=3.17,
        lut=211,
        ff=138,
        dsp=4,
        pipeline_type="loop auto-rewind stp",
        loop_metrics=[
            {
                "name": "loop",
                "trip_count": 512,
                "latency": 513,
                "pipeline_ii": 1,
            }
        ],
    )
    starter = """int top(int *a) {
  int sum = 0;
  for (int i = 0; i < 1024; ++i) { sum += a[i]; }
  return sum;
}
"""
    first = """int top(int *a) {
  int sum = 0;
  for (int i = 0; i < 1024; ++i) {
    #pragma HLS UNROLL factor=4
    sum += a[i];
  }
  return sum;
}
"""
    repeated = first.replace(
        "int top", "// different comment\nint top"
    ).replace("    #pragma", "#pragma")

    class FakeLlm:
        def __init__(self) -> None:
            self.responses = [first, repeated]

        def complete(self, system, prompt):
            return self.responses.pop(0)

    class FakeServer:
        def __init__(self) -> None:
            self.csim_calls = 0
            self.synth_calls = 0

        def csim(self, kernel):
            self.csim_calls += 1
            return SimpleNamespace(kind="csim", ok=True, report=None, log="")

        def synth(self, kernel):
            self.synth_calls += 1
            return SimpleNamespace(
                kind="synth", ok=True, report=rejected_report, log=""
            )

    server = FakeServer()
    state = SimpleNamespace(
        task=task,
        server=server,
        kernel=starter,
        best_latency=1027,
        results=[
            SimpleNamespace(
                kind="synth", ok=True, report=starter_report, log=""
            )
        ],
        metadata={},
        log=lambda message: None,
    )

    result = OptimizeAgent(FakeLlm(), max_rounds=5).run(state)

    assert result.kernel == starter
    assert server.csim_calls == 1
    assert server.synth_calls == 1
    assert result.metadata["semantic_duplicate_skips"] == 1


def test_minimum_unroll_frontier_requires_only_factor_two_and_loop_ii_one() -> None:
    best = """int top(int *a) {
  int sum = 0;
  for (int i = 0; i < 1024; ++i) {
    sum += a[i];
  }
  return sum;
}
"""
    candidate = best.replace(
        "    sum += a[i];",
        "    #pragma HLS UNROLL factor=2\n    sum += a[i];",
    )
    card = SimpleNamespace(latency_ratio=1.99, area_growth=2.0)
    report = SimpleNamespace(loop_metrics=[{"pipeline_ii": 1}])

    assert _is_minimum_unroll_frontier(best, candidate, card, report)
    assert not _is_minimum_unroll_frontier(
        best,
        candidate.replace("factor=2", "factor=4"),
        card,
        report,
    )
    assert not _is_minimum_unroll_frontier(
        best,
        candidate.replace("sum += a[i];", "sum += 2 * a[i];"),
        card,
        report,
    )
    assert not _is_minimum_unroll_frontier(
        best,
        candidate,
        card,
        SimpleNamespace(loop_metrics=[{"pipeline_ii": 2}]),
    )


def test_optimize_stops_api_after_rejected_minimum_unroll() -> None:
    task = SimpleNamespace(
        id="dotProduct_optimize",
        type="optimize",
        difficulty=3,
        requires_cosim=False,
        budget=40,
        clock_ns=5.0,
        description="",
        headers={},
        top="top",
        kernel_name="top.cpp",
    )
    starter_report = _report(
        latency=1027,
        ii=1025,
        clock=3.17,
        lut=156,
        ff=93,
        dsp=2,
        pipeline_type="loop auto-rewind stp",
        loop_metrics=[
            {
                "name": "loop",
                "trip_count": 1024,
                "latency": 1025,
                "pipeline_ii": 1,
            }
        ],
    )
    rejected_report = _report(
        latency=515,
        ii=513,
        clock=3.17,
        lut=211,
        ff=138,
        dsp=4,
        pipeline_type="loop auto-rewind stp",
        loop_metrics=[{"name": "loop", "pipeline_ii": 1}],
    )
    starter = """int top(int *a) {
  int sum = 0;
  for (int i = 0; i < 1024; ++i) {
    sum += a[i];
  }
  return sum;
}
"""
    candidate = starter.replace(
        "    sum += a[i];",
        "    #pragma HLS UNROLL factor=2\n    sum += a[i];",
    )

    class Llm:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system, prompt):
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("minimum frontier should stop reflection API")
            return candidate

    class Server:
        def __init__(self) -> None:
            self.csim_calls = 0
            self.synth_calls = 0

        def csim(self, kernel):
            self.csim_calls += 1
            return SimpleNamespace(kind="csim", ok=True, report=None, log="")

        def synth(self, kernel):
            self.synth_calls += 1
            return SimpleNamespace(
                kind="synth", ok=True, report=rejected_report, log=""
            )

    llm = Llm()
    server = Server()
    state = SimpleNamespace(
        task=task,
        server=server,
        kernel=starter,
        best_latency=1027,
        results=[
            SimpleNamespace(
                kind="synth", ok=True, report=starter_report, log=""
            )
        ],
        metadata={},
        log=lambda message: None,
    )

    result = OptimizeAgent(llm, max_rounds=5).run(state)

    assert result.kernel == starter
    assert llm.calls == 1
    assert server.csim_calls == 1
    assert server.synth_calls == 1
    assert result.metadata["minimum_factor_convergence"] is True
