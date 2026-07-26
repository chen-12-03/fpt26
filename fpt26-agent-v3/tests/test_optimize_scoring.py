import json
from types import SimpleNamespace

from agent.agents.optimize import (
    OptimizeAgent,
    _candidate_fingerprint,
    _csim_failure_feedback,
    _diagnose,
    _ii_resource_intent_feedback,
    _is_minimum_unroll_frontier,
    _latest_successful_synth,
    _rejection_feedback,
    _score_candidate,
    _source_array_rank,
)
from agent.analysis.action_contract import build_ii_resource_action_contract
from agent.analysis.synth_diagnostics import extract_ii_resource_limits

_AVAILABLE = {
    "LUT": 1303680,
    "FF": 2607360,
    "DSP": 9024,
    "BRAM_18K": 4032,
    "URAM": 960,
}


def _report(
    *,
    latency: int,
    ii: int,
    clock: float,
    lut: int,
    ff: int,
    dsp: int,
    available: dict | None = None,
    pipeline_type: str | None = None,
    loop_metrics: list[dict] | None = None,
):
    return SimpleNamespace(
        latency_worst=latency,
        latency_avg=latency,
        interval_max=ii,
        clock_period_ns=clock,
        resources={"LUT": lut, "FF": ff, "DSP": dsp, "BRAM_18K": 0, "URAM": 0},
        available=dict(_AVAILABLE if available is None else available),
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
    assert extreme_card.q_hw == 0.4431
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


def test_scorer_aligned_quality_rejects_candidate_over_device_capacity() -> None:
    task = SimpleNamespace(
        id="capacity",
        type="optimize",
        difficulty=3,
        requires_cosim=False,
        budget=40,
        clock_ns=5.0,
    )
    small_device = {
        "LUT": 200,
        "FF": 200,
        "DSP": 10,
        "BRAM_18K": 10,
        "URAM": 10,
    }
    starter = _report(
        latency=1000,
        ii=1000,
        clock=5.0,
        lut=100,
        ff=100,
        dsp=2,
        available=small_device,
    )
    over_capacity = _report(
        latency=100,
        ii=100,
        clock=5.0,
        lut=201,
        ff=100,
        dsp=2,
        available=small_device,
    )

    card = _score_candidate(task, starter, over_capacity)

    assert not card.valid
    assert card.gate_reason == "resource_capacity_exceeded"
    assert card.q_hw == 0.0


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
    assert feedback["candidate_q_hw"] == 0.1325
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


def test_csim_failure_feedback_contains_concise_error_and_candidate_diff() -> None:
    best = "void top() {}\n"
    failed = '#include "top.h"\nvoid top() { hls::stream<int> q; }\n'
    result = SimpleNamespace(
        phase="compile_error",
        log=(
            "/tmp/run/top.cpp:2:14: error: use of undeclared identifier 'hls'\n"
            "1 error generated.\n"
        ),
    )

    feedback = _csim_failure_feedback(result, best, failed)

    assert feedback["status"] == "REJECTED_BY_CSIM_COMPILE_ERROR"
    assert "undeclared identifier 'hls'" in feedback["error_summary"]
    assert "hls::stream<int> q" in feedback["failed_candidate_diff"]
    assert "/tmp/run" not in json.dumps(feedback)
    assert "add the required existing header" in feedback["required_next_action"]


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


def test_diagnosis_extracts_vitis_memory_port_ii_limit() -> None:
    report = _report(
        latency=39069,
        ii=39070,
        clock=3.17,
        lut=909,
        ff=649,
        dsp=6,
        loop_metrics=[
            {
                "name": "stencil_label1_stencil_label2",
                "trip_count": 7812,
                "latency": 39061,
                "pipeline_ii": 5,
            }
        ],
    )
    warning = (
        "WARNING: [HLS 200-448] Lower bound of II is 5 due to multiple "
        "'load' operation 32 bit ('orig_load', stencil_stencil2d.cpp:20) "
        "on array 'orig', 'load' operation 32 bit ('orig_load_1', "
        "stencil_stencil2d.cpp:20) on array 'orig' accessing core:RAM:orig"
    )

    limits = extract_ii_resource_limits(warning + "\n" + warning)
    diagnosis = _diagnose(SimpleNamespace(report=report, log=warning))

    assert len(limits) == 1
    assert limits[0].lower_bound == 5
    assert limits[0].array == "orig"
    assert limits[0].source == "stencil_stencil2d.cpp:20"
    assert limits[0].core == "RAM:orig"
    assert "Measured loop PipelineII=5>1" in diagnosis
    assert "memory-port resource limit on array 'orig'" in diagnosis
    assert "II lower bound=5" in diagnosis
    assert "another PIPELINE directive alone cannot lower II" in diagnosis


def test_action_contract_targets_measured_array_with_one_bounded_trial() -> None:
    warning = (
        "WARNING: [HLS 200-448] Lower bound of II is 5 due to multiple "
        "'load' operation 32 bit ('orig_load', stencil.cpp:20) on array "
        "'orig' accessing core:RAM:orig"
    )

    contract = build_ii_resource_action_contract(warning)

    assert contract is not None
    assert contract["kind"] == "measured_memory_port_ii"
    assert contract["evidence_id"] == "HLS 200-448"
    target = contract["targets"][0]
    assert target["array"] == "orig"
    assert target["observed_ii_lower_bound"] == 5
    assert target["recommended_minimal_trial"] == {
        "pragma_class": "ARRAY_PARTITION",
        "variable": "orig",
        "style": "cyclic",
        "factor": 2,
        "dimension_policy": (
            "Choose only the dimension indexed by concurrent loop "
            "iterations. Omit this trial when the source does not prove "
            "that dimension."
        ),
    }
    assert "unreported array" in contract["forbidden_as_non_responsive"][1]
    assert build_ii_resource_action_contract("Synthesis completed") is None


def test_ii_resource_intent_gate_requires_evidence_matched_banking() -> None:
    best = """void top(int orig[64]) {
  for (int i = 0; i < 64; ++i) { orig[i] += 1; }
}
"""
    warning = (
        "WARNING: [HLS 200-448] Lower bound of II is 5 due to multiple "
        "'load' operation 32 bit ('orig_load', top.cpp:2) on array 'orig' "
        "accessing core:RAM:orig"
    )
    synth_result = SimpleNamespace(log=warning)
    standalone_unroll = best.replace(
        "  for", "  #pragma HLS UNROLL factor=2\n  for"
    )
    matched_partition = best.replace(
        "  for",
        "  #pragma HLS ARRAY_PARTITION variable=orig cyclic factor=2 dim=1\n  for",
    )
    unmatched_partition = best.replace(
        "  for",
        "  #pragma HLS ARRAY_PARTITION variable=filter complete dim=1\n"
        "  #pragma HLS UNROLL factor=2\n  for",
    )
    matched_partition_and_unroll = best.replace(
        "  for",
        "  #pragma HLS ARRAY_RESHAPE variable = orig cyclic factor=2 dim=1\n"
        "  #pragma HLS UNROLL factor=2\n  for",
    )
    wrong_style = best.replace(
        "  for",
        "  #pragma HLS ARRAY_PARTITION variable=orig block factor=2 dim=1\n  for",
    )
    invalid_dimension = best.replace(
        "  for",
        "  #pragma HLS ARRAY_PARTITION variable=orig cyclic factor=2 dim=2\n  for",
    )
    locality_change = best.replace(
        "  for", "  int cached = orig[0];\n  for"
    )
    other_storage_action = best.replace(
        "  for",
        "  #pragma HLS BIND_STORAGE variable=orig type=ram_2p\n  for",
    )

    feedback = _ii_resource_intent_feedback(
        synth_result, best, standalone_unroll
    )

    assert feedback is not None
    assert feedback["status"] == "REJECTED_BY_SYNTH_EVIDENCE_INTENT"
    assert feedback["ii_resource_limits"][0]["array"] == "orig"
    assert "No candidate tool was run" in feedback["reason"]
    unmatched_feedback = _ii_resource_intent_feedback(
        synth_result, best, unmatched_partition
    )
    assert unmatched_feedback is not None
    assert unmatched_feedback["unmatched_banking_variables"] == ["filter"]
    assert (
        _ii_resource_intent_feedback(synth_result, best, matched_partition)
        is None
    )
    multi_action_feedback = _ii_resource_intent_feedback(
        synth_result, best, matched_partition_and_unroll
    )
    assert multi_action_feedback is not None
    assert "expected exactly one" in " ".join(
        multi_action_feedback["contract_violations"]
    )
    assert "pragma class must be ARRAY_PARTITION" in multi_action_feedback[
        "contract_violations"
    ]
    style_feedback = _ii_resource_intent_feedback(
        synth_result, best, wrong_style
    )
    assert style_feedback is not None
    assert "partition style must be cyclic" in style_feedback[
        "contract_violations"
    ]
    dimension_feedback = _ii_resource_intent_feedback(
        synth_result, best, invalid_dimension
    )
    assert dimension_feedback is not None
    assert "dim=2 exceeds visible array rank=1" in " ".join(
        dimension_feedback["contract_violations"]
    )
    assert (
        _ii_resource_intent_feedback(synth_result, best, locality_change)
        is None
    )
    assert (
        _ii_resource_intent_feedback(synth_result, best, other_storage_action)
        is None
    )


def test_source_array_rank_handles_flattened_and_multidimensional_arrays() -> None:
    source = "void top(int flat[64], int matrix[8][8]) { flat[0] = matrix[0][0]; }"

    assert _source_array_rank(source, "flat") == 1
    assert _source_array_rank(source, "matrix") == 2
    assert _source_array_rank(source, "unknown") is None


def test_optimize_reflects_ii_intent_rejection_without_candidate_tools() -> None:
    task = SimpleNamespace(
        id="ii_intent",
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
    report = _report(
        latency=500,
        ii=500,
        clock=5.0,
        lut=200,
        ff=100,
        dsp=0,
        loop_metrics=[
            {"name": "loop", "trip_count": 100, "latency": 499, "pipeline_ii": 5}
        ],
    )
    warning = (
        "WARNING: [HLS 200-448] Lower bound of II is 5 due to multiple "
        "'load' operation 32 bit ('orig_load', top.cpp:2) on array 'orig' "
        "accessing core:RAM:orig"
    )
    starter = """void top(int orig[100], int filter[3]) {
  for (int i = 0; i < 100; ++i) { orig[i] += 1; }
}
"""
    unmatched_banking = starter.replace(
        "  for",
        "  #pragma HLS ARRAY_PARTITION variable=filter complete dim=1\n"
        "  #pragma HLS UNROLL factor=2\n  for",
    )

    class Llm:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system, prompt):
            self.calls += 1
            if self.calls == 1:
                contract = json.loads(prompt)["measured_action_contract"]
                assert contract["targets"][0]["array"] == "orig"
                assert contract["targets"][0]["recommended_minimal_trial"][
                    "factor"
                ] == 2
                return unmatched_banking
            payload = json.loads(prompt)
            feedback = payload["previous_candidate_feedback"]
            assert feedback["status"] == "REJECTED_BY_SYNTH_EVIDENCE_INTENT"
            assert feedback["ii_resource_limits"][0]["array"] == "orig"
            assert feedback["unmatched_banking_variables"] == ["filter"]
            assert "no candidate tool was run" in payload["instruction"].lower()
            return "// stop after evidence reflection\n" + starter

    class Server:
        def csim(self, kernel):
            raise AssertionError("intent-rejected candidate must skip C-sim")

        def synth(self, kernel):
            raise AssertionError("intent-rejected candidate must skip synthesis")

    llm = Llm()
    state = SimpleNamespace(
        task=task,
        server=Server(),
        kernel=starter,
        best_latency=500,
        results=[
            SimpleNamespace(kind="synth", ok=True, report=report, log=warning)
        ],
        metadata={},
        log=lambda message: None,
    )

    result = OptimizeAgent(llm, max_rounds=2).run(state)

    assert result.kernel == starter
    assert llm.calls == 2
    assert result.metadata["ii_resource_intent_rejections"] == 1
    assert result.metadata["semantic_current_best_skips"] == 1


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
        lut=2110,
        ff=1380,
        dsp=20,
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


def test_optimize_accepts_minimum_unroll_then_converges_on_no_change() -> None:
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
    improved_report = _report(
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
            if self.calls > 2:
                raise AssertionError("accepted candidate should converge on semantic no-op")
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
                kind="synth", ok=True, report=improved_report, log=""
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

    assert result.kernel == candidate
    assert llm.calls == 2
    assert server.csim_calls == 1
    assert server.synth_calls == 1
    assert result.metadata["minimum_factor_convergence"] is False
    assert result.metadata["semantic_current_best_skips"] == 0


def test_optimize_reflects_csim_compile_error_into_next_round() -> None:
    task = SimpleNamespace(
        id="compile_reflection",
        type="optimize",
        difficulty=3,
        requires_cosim=False,
        budget=40,
        clock_ns=5.0,
        description="",
        headers={"top.h": "void top(int *out);"},
        top="top",
        kernel_name="top.cpp",
    )
    starter_report = _report(
        latency=100,
        ii=100,
        clock=5.0,
        lut=200,
        ff=100,
        dsp=0,
    )
    improved_report = _report(
        latency=50,
        ii=50,
        clock=5.0,
        lut=200,
        ff=100,
        dsp=0,
    )
    starter = '#include "top.h"\nvoid top(int *out) { *out = 1; }\n'
    failed = starter.replace(
        "void top", "void helper() { hls::stream<int> q; }\nvoid top"
    )
    corrected = '#include "hls_stream.h"\n' + failed

    class Llm:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system, prompt):
            self.calls += 1
            if self.calls == 1:
                return failed
            payload = json.loads(prompt)
            feedback = payload["previous_candidate_feedback"]
            assert feedback["status"] == "REJECTED_BY_CSIM_COMPILE_ERROR"
            assert "undeclared identifier 'hls'" in feedback["error_summary"]
            assert "hls::stream<int> q" in feedback["failed_candidate_diff"]
            return corrected

    class Server:
        def __init__(self) -> None:
            self.csim_calls = 0
            self.synth_calls = 0

        def csim(self, kernel):
            self.csim_calls += 1
            if '#include "hls_stream.h"' not in kernel:
                return SimpleNamespace(
                    kind="csim",
                    ok=False,
                    phase="compile_error",
                    report=None,
                    log="top.cpp:2:17: error: use of undeclared identifier 'hls'",
                )
            return SimpleNamespace(
                kind="csim", ok=True, phase="pass", report=None, log=""
            )

        def synth(self, kernel):
            self.synth_calls += 1
            return SimpleNamespace(
                kind="synth",
                ok=True,
                phase="pass",
                report=improved_report,
                log="",
            )

    llm = Llm()
    server = Server()
    state = SimpleNamespace(
        task=task,
        server=server,
        kernel=starter,
        best_latency=100,
        results=[
            SimpleNamespace(
                kind="synth", ok=True, report=starter_report, log=""
            )
        ],
        metadata={},
        log=lambda message: None,
    )

    result = OptimizeAgent(llm, max_rounds=2).run(state)

    assert result.kernel == corrected
    assert result.best_latency == 50
    assert llm.calls == 2
    assert server.csim_calls == 2
    assert server.synth_calls == 1


def test_optimize_reflects_interface_shape_failure_into_next_round() -> None:
    task = SimpleNamespace(
        id="interface_shape_reflection",
        type="optimize",
        difficulty=3,
        requires_cosim=False,
        budget=40,
        clock_ns=5.0,
        description="",
        headers={"top.h": "void top(int *out);"},
        top="top",
        kernel_name="top.cpp",
    )
    starter_report = _report(
        latency=100,
        ii=100,
        clock=5.0,
        lut=200,
        ff=100,
        dsp=0,
    )
    starter = '#include "top.h"\nvoid top(int *out) { *out = 1; }\n'
    malformed_helper_only = """int helper(int x) {
  if (x > 0) {
    return x + 1;
"""

    class Llm:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system, prompt):
            self.calls += 1
            if self.calls == 1:
                return malformed_helper_only
            payload = json.loads(prompt)
            feedback = payload["previous_candidate_feedback"]
            assert feedback["status"] == "REJECTED_BY_INTERFACE_GATE"
            assert feedback["reason"] == "unbalanced_cpp_delimiters"
            assert feedback["no_candidate_tools_run"] is True
            assert feedback["top_function"] == "top"
            assert feedback["source_diagnostics"]["has_top_function_token"] is False
            assert feedback["source_diagnostics"]["markdown_fence_count"] == 0
            assert "complete C/C++ translation unit" in feedback[
                "required_next_action"
            ]
            assert "REJECTED_BY_INTERFACE_GATE" in payload["instruction"]
            return starter

    class Server:
        def csim(self, kernel):
            raise AssertionError("interface-rejected candidate must skip C-sim")

        def synth(self, kernel):
            raise AssertionError("interface-rejected candidate must skip synthesis")

    llm = Llm()
    state = SimpleNamespace(
        task=task,
        server=Server(),
        kernel=starter,
        best_latency=100,
        results=[
            SimpleNamespace(
                kind="synth", ok=True, report=starter_report, log=""
            )
        ],
        metadata={},
        log=lambda message: None,
    )

    result = OptimizeAgent(llm, max_rounds=2).run(state)

    assert result.kernel == starter
    assert llm.calls == 2
    validation = result.metadata["interface_validations"][-1]
    assert validation["reason"] == "unbalanced_cpp_delimiters"
    assert validation["source_diagnostics"]["has_top_function_token"] is False


def test_optimize_skips_tools_for_semantic_current_best_noop() -> None:
    task = SimpleNamespace(
        id="semantic_noop",
        type="optimize",
        difficulty=2,
        requires_cosim=False,
        budget=40,
        clock_ns=5.0,
        description="",
        headers={"top.h": "void top(int *out);"},
        top="top",
        kernel_name="top.cpp",
    )
    starter_report = _report(
        latency=100,
        ii=100,
        clock=5.0,
        lut=200,
        ff=100,
        dsp=0,
    )
    starter = '#include "top.h"\nvoid top(int *out) { *out = 1; }\n'
    comment_only = "// top.cpp\n" + starter

    class Llm:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system, prompt):
            self.calls += 1
            return comment_only

    class Server:
        def csim(self, kernel):
            raise AssertionError("semantic current-best no-op must skip C-sim")

        def synth(self, kernel):
            raise AssertionError("semantic current-best no-op must skip synthesis")

    llm = Llm()
    state = SimpleNamespace(
        task=task,
        server=Server(),
        kernel=starter,
        best_latency=100,
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
    assert result.metadata["semantic_current_best_skips"] == 1
