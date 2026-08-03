import json
from types import SimpleNamespace

from agent.agents.optimize import (
    OptimizeAgent,
    _anti_repeat_action_violation,
    _candidate_fingerprint,
    _csim_failure_feedback,
    _diagnose,
    _ii_resource_intent_feedback,
    _latest_successful_synth,
    _rejection_feedback,
    _report_supported_action_violation,
    _score_candidate,
    _source_array_rank,
    candidate_action_summary,
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
    assert 0.0 < extreme_card.q_hw < 0.75
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
    assert feedback["candidate_q_hw"] == card.q_hw
    assert feedback["candidate_q_hw"] < feedback["current_best_q_hw"]
    assert feedback["current_best_q_hw"] == 0.75
    assert feedback["bottleneck_resource"] in {"LUT", "FF"}
    assert feedback["candidate_pragmas"] == [
        "#pragma HLS ARRAY_PARTITION variable=a complete",
        "#pragma HLS UNROLL factor=64",
    ]
    assert "For this exact candidate" in feedback[
        "directional_constraint"
    ]
    assert "Do not extrapolate this result to an entire family" in feedback[
        "directional_constraint"
    ]
    assert "Do not repeat the exact rejected action signature" in feedback[
        "required_next_action"
    ]
    assert "must state a new report/source-supported hypothesis" in feedback[
        "required_next_action"
    ]
    assert "forbidden_optimization_families" not in feedback
    assert "forbidden_targets" not in feedback
    assert feedback["rejected_action_signatures"]
    assert feedback["anti_repeat_priority"].startswith("Measured Q_HW")


def test_action_guard_blocks_exact_signature_not_family_and_keeps_report_guard() -> None:
    prior = {
        "action": {
            "families": ["LOOP_UNROLL"],
            "targets": {
                "loops": ["reduce"],
                "arrays": [],
                "functions": [],
            },
            "source_changed": False,
            "semantic_signature": (
                "families=LOOP_UNROLL|targets=loop:reduce|"
                "added_pragmas=#pragma hls unroll factor=2|"
                "removed_pragmas=|source_changed=False"
            ),
        }
    }
    same_family_other_loop = {
        "families": ["LOOP_UNROLL"],
        "targets": {"loops": ["other"], "arrays": [], "functions": []},
        "source_changed": False,
    }
    different_family_same_loop = {
        "families": ["PIPELINE"],
        "targets": {"loops": ["reduce"], "arrays": [], "functions": []},
        "source_changed": False,
    }

    assert _anti_repeat_action_violation(same_family_other_loop, [prior]) is None
    assert _anti_repeat_action_violation(different_family_same_loop, [prior]) is None
    exact_repeat = {
        "families": ["LOOP_UNROLL"],
        "targets": {"loops": ["reduce"], "arrays": [], "functions": []},
        "added_pragmas": ["#pragma HLS UNROLL factor=2"],
        "source_changed": False,
    }
    changed_factor = {
        **exact_repeat,
        "added_pragmas": ["#pragma HLS UNROLL factor=4"],
    }
    assert "semantic equivalent" in (
        _anti_repeat_action_violation(exact_repeat, [prior]) or ""
    )
    assert _anti_repeat_action_violation(changed_factor, [prior]) is None

    unmapped_unroll = {
        "families": ["LOOP_UNROLL"],
        "targets": {"loops": [], "arrays": [], "functions": []},
        "added_pragmas": ["#pragma HLS UNROLL factor=32"],
        "source_changed": False,
    }
    diagnosed_loop_contract = {
        "kind": "diagnosis_guided_optimization",
        "target": {"loop": "reduce"},
    }
    assert "could not be mapped to the diagnosed loop" in (
        _report_supported_action_violation(
            unmapped_unroll,
            SimpleNamespace(loop_metrics=[]),
            diagnosed_loop_contract,
        )
        or ""
    )
    mixed_action = {
        "families": ["LOOP_UNROLL", "SOURCE_RESTRUCTURE"],
        "targets": {
            "loops": ["reduce"],
            "arrays": [],
            "functions": ["top"],
        },
        "added_pragmas": ["#pragma HLS UNROLL factor=2"],
        "source_changed": True,
    }
    diagnosed_loop_contract["actionable"] = True
    diagnosed_loop_contract["candidate_families"] = [
        "LOOP_UNROLL",
        "SOURCE_RESTRUCTURE",
    ]
    assert "combines multiple optimization families" in (
        _report_supported_action_violation(
            mixed_action,
            SimpleNamespace(loop_metrics=[]),
            diagnosed_loop_contract,
        )
        or ""
    )

    ii_one_report = SimpleNamespace(
        loop_metrics=[{"name": "reduce", "pipeline_ii": 1}]
    )
    assert "PipelineII=1" in (
        _report_supported_action_violation(
            different_family_same_loop, ii_one_report, None
        )
        or ""
    )
    partially_measured_report = SimpleNamespace(
        loop_metrics=[
            {"name": "read_buf", "pipeline_ii": None},
            {"name": "calc_write", "pipeline_ii": 1},
        ]
    )
    assert (
        _report_supported_action_violation(
            different_family_same_loop, partially_measured_report, None
        )
        is None
    )
    mixed_ii_report = SimpleNamespace(
        loop_metrics=[
            {"name": "reduce", "pipeline_ii": 1},
            {"name": "other", "pipeline_ii": 2},
        ]
    )
    assert "target loop(s) already have PipelineII=1" in (
        _report_supported_action_violation(
            different_family_same_loop, mixed_ii_report, None
        )
        or ""
    )
    banking = {
        "families": ["MEMORY_BANKING"],
        "targets": {"loops": [], "arrays": ["a"], "functions": []},
        "source_changed": False,
    }
    assert "lacks source-proven concurrent-access evidence" in (
        _report_supported_action_violation(banking, ii_one_report, None) or ""
    )
    source_evidence = [
        {
            "array": "a",
            "dimension": 1,
            "array_extent": 64,
            "concurrent_lanes": 4,
            "lane_stride": 1,
            "factor_limit": 4,
            "reshape_eligible": True,
        }
    ]
    source_backed_banking = {
        **banking,
        "added_pragmas": [
            "#pragma HLS ARRAY_PARTITION variable=a cyclic factor=2 dim=1"
        ],
    }
    assert (
        _report_supported_action_violation(
            source_backed_banking,
            ii_one_report,
            None,
            source_banking_evidence=source_evidence,
        )
        is None
    )
    source_backed_factor_four = {
        **banking,
        "added_pragmas": [
            "#pragma HLS ARRAY_PARTITION variable=a cyclic factor=4 dim=1"
        ],
    }
    source_backed_reshape = {
        **banking,
        "added_pragmas": [
            "#pragma HLS ARRAY_RESHAPE variable=a cyclic factor=4 dim=1"
        ],
    }
    conflicting_block = {
        **banking,
        "added_pragmas": [
            "#pragma HLS ARRAY_PARTITION variable=a block factor=2 dim=1"
        ],
    }
    assert (
        _report_supported_action_violation(
            source_backed_factor_four,
            ii_one_report,
            None,
            source_banking_evidence=source_evidence,
        )
        is None
    )
    assert (
        _report_supported_action_violation(
            source_backed_reshape,
            ii_one_report,
            None,
            source_banking_evidence=source_evidence,
        )
        is None
    )
    assert "does not provably increase distinct banks" in (
        _report_supported_action_violation(
            conflicting_block,
            ii_one_report,
            None,
            source_banking_evidence=source_evidence,
        )
        or ""
    )
    assert (
        _report_supported_action_violation(
            banking,
            ii_one_report,
            {"kind": "measured_memory_port_ii"},
        )
        is None
    )


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
    assert "UNROLL" not in diagnosis
    assert "not evidence of a loop-II or memory-port problem" in diagnosis
    assert "II=1025>1" not in diagnosis


def test_action_guard_preserves_vitis_inferred_pipeline_hierarchy() -> None:
    report = SimpleNamespace(
        loop_metrics=[{"name": "middle", "pipeline_ii": 1}]
    )
    action = {
        "families": ["LOOP_UNROLL"],
        "targets": {"loops": ["inner"], "arrays": [], "functions": []},
        "added_pragmas": ["#pragma HLS UNROLL factor=2"],
    }
    source_metadata = {
        "loops": [
            {
                "name": "inner",
                "report_loop_name": "unknown",
                "auto_parallelism": {
                    "hierarchy_sensitive": True,
                    "pipeline_ancestors": ["middle"],
                },
            }
        ]
    }

    violation = _report_supported_action_violation(
        action,
        report,
        None,
        source_metadata=source_metadata,
    )

    assert violation is not None
    assert "inferred-pipelined ancestor(s) middle" in violation
    assert "pipeline boundary" in violation


def test_optimizer_rejects_inner_unroll_then_measures_source_backed_banking() -> None:
    task = SimpleNamespace(
        id="generic_matrix",
        type="optimize",
        difficulty=3,
        requires_cosim=False,
        budget=40,
        clock_ns=5.0,
        description="Optimize local matrix reuse.",
        headers={"top.h": "#define MAX_DIM 16\n"},
        top="top",
        kernel_name="top.cpp",
    )
    starter_report = _report(
        latency=1200,
        ii=1201,
        clock=5.0,
        lut=200,
        ff=200,
        dsp=2,
        loop_metrics=[
            {
                "name": "middle",
                "trip_count": 16,
                "latency": 1100,
                "pipeline_ii": 1,
            }
        ],
    )
    starter_report.inferred_directives = [
        {
            "kind": "pipeline",
            "target": "top/middle",
            "function": "top",
            "scope": "middle",
            "origin": "vitis_inferred",
        }
    ]
    improved_report = _report(
        latency=500,
        ii=501,
        clock=5.0,
        lut=200,
        ff=200,
        dsp=2,
        loop_metrics=[
            {
                "name": "middle",
                "trip_count": 16,
                "latency": 450,
                "pipeline_ii": 1,
            }
        ],
    )
    improved_report.inferred_directives = list(
        starter_report.inferred_directives
    )
    starter = """#include "top.h"
void top(int *out) {
  int A[MAX_DIM * MAX_DIM];
  int B[MAX_DIM * MAX_DIM];
outer:
  for (int i = 0; i < MAX_DIM; ++i) {
middle:
    for (int j = 0; j < MAX_DIM; ++j) {
inner:
      for (int k = 0; k < MAX_DIM; ++k) {
        out[i] += A[i * MAX_DIM + k] * B[k * MAX_DIM + j];
      }
    }
  }
}
"""
    forbidden_unroll = starter.replace(
        "        out[i] +=",
        "        #pragma HLS UNROLL factor=2\n        out[i] +=",
    )
    source_backed_banking = starter.replace(
        "  int B[MAX_DIM * MAX_DIM];",
        "  int B[MAX_DIM * MAX_DIM];\n"
        "  #pragma HLS ARRAY_PARTITION variable=A cyclic factor=2 dim=1\n"
        "  #pragma HLS ARRAY_PARTITION variable=B block factor=16 dim=1",
    )

    class Llm:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system, prompt):
            self.calls += 1
            payload = json.loads(prompt)
            evidence = {
                item["array"]: item
                for item in payload["source_banking_evidence"]
            }
            assert set(evidence) == {"A", "B"}
            assert evidence["A"]["factor_limit"] == 16
            assert evidence["A"]["banking_option_space"]["factor_min"] == 2
            assert evidence["A"]["banking_option_space"]["factor_max"] == 16
            assert evidence["B"]["banking_option_space"][
                "partition_types"
            ] == ["cyclic", "block"]
            if self.calls == 1:
                return forbidden_unroll
            assert payload["previous_candidate_feedback"]["status"] == (
                "REJECTED_BY_REPORT_EVIDENCE"
            )
            assert "pipeline boundary" in payload[
                "previous_candidate_feedback"
            ]["reason"]
            return source_backed_banking

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
    logs: list[str] = []
    state = SimpleNamespace(
        task=task,
        server=server,
        kernel=starter,
        best_latency=1200,
        results=[
            SimpleNamespace(
                kind="synth", ok=True, report=starter_report, log=""
            )
        ],
        metadata={},
        log=logs.append,
    )

    result = OptimizeAgent(llm, max_rounds=2).run(state)

    assert result.kernel == source_backed_banking
    assert llm.calls == 2
    assert server.csim_calls == 1
    assert server.synth_calls == 1
    assert result.metadata["report_evidence_action_rejections"] == 1
    assert result.metadata["synth_candidates"][-1]["decision"] == "ACCEPTED"
    assert any("source-backed banking targets=A" in entry for entry in logs)


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


def test_action_contract_targets_measured_array_without_prescribing_factor() -> None:
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
    assert target["candidate_parameter_space"] == {
        "pragma_classes": ["ARRAY_PARTITION", "ARRAY_RESHAPE"],
        "variable": "orig",
        "partition_type": "derive_from_source_bank_mapping",
        "factor_policy": (
            "Derive candidate factors from the number and affine mapping of "
            "concurrent accesses. The observed II lower bound describes the "
            "bottleneck and is not a factor."
        ),
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
    matched_block = best.replace(
        "  for",
        "  #pragma HLS ARRAY_PARTITION variable=orig block factor=2 dim=1\n  for",
    )
    invalid_factor = best.replace(
        "  for",
        "  #pragma HLS ARRAY_PARTITION variable=orig cyclic factor=1 dim=1\n  for",
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
    assert all(
        "pragma class must be ARRAY_PARTITION" not in item
        for item in multi_action_feedback["contract_violations"]
    )
    assert (
        _ii_resource_intent_feedback(synth_result, best, matched_block)
        is None
    )
    factor_feedback = _ii_resource_intent_feedback(
        synth_result, best, invalid_factor
    )
    assert factor_feedback is not None
    assert "finite factor >=2" in " ".join(
        factor_feedback["contract_violations"]
    )
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
                parameter_space = contract["targets"][0][
                    "candidate_parameter_space"
                ]
                assert parameter_space["pragma_classes"] == [
                    "ARRAY_PARTITION",
                    "ARRAY_RESHAPE",
                ]
                assert "factor" not in parameter_space
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
            },
            {
                "name": "distinct_report_target",
                "trip_count": 64,
                "latency": 128,
                "pipeline_ii": 2,
            },
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


def test_qhw_rejection_allows_a_distinct_parameter_hypothesis() -> None:
    task = SimpleNamespace(
        id="anti_repeat_qhw",
        type="optimize",
        difficulty=3,
        requires_cosim=False,
        budget=40,
        clock_ns=5.0,
        description="Optimize a measured reduction.",
        headers={},
        top="top",
        kernel_name="top.cpp",
    )
    starter_report = _report(
        latency=1000,
        ii=1000,
        clock=5.0,
        lut=100,
        ff=100,
        dsp=1,
        loop_metrics=[
            {
                "name": "reduce",
                "trip_count": 1000,
                "latency": 999,
                "pipeline_ii": 1,
            },
            {
                "name": "alternative_loop",
                "trip_count": 64,
                "latency": 128,
                "pipeline_ii": 2,
            },
        ],
    )
    rejected_report = _report(
        latency=500,
        ii=500,
        clock=5.0,
        lut=400,
        ff=400,
        dsp=4,
        loop_metrics=[
            {
                "name": "reduce",
                "trip_count": 500,
                "latency": 499,
                "pipeline_ii": 1,
            }
        ],
    )
    starter = """int top(int *a) {
  int sum = 0;
  for (int i = 0; i < 1000; ++i) {
    sum += a[i];
  }
  return sum;
}
"""
    factor_four = starter.replace(
        "    sum += a[i];",
        "    #pragma HLS UNROLL factor=4\n    sum += a[i];",
    )
    # A changed factor is a distinct hypothesis even when family and target match.
    factor_eight = factor_four.replace("factor=4", "factor=8").replace(
        "int sum = 0;", "int sum = 0; // layout-only semantic variant"
    )

    first_action = candidate_action_summary(
        starter, factor_four, top_function="top"
    )
    second_action = candidate_action_summary(
        starter, factor_eight, top_function="top"
    )
    assert first_action["families"] == ["LOOP_UNROLL"]
    assert first_action["targets"]["loops"] == ["loop_0"]
    assert first_action["semantic_signature"] != second_action[
        "semantic_signature"
    ]
    assert _candidate_fingerprint(factor_four) != _candidate_fingerprint(
        factor_eight
    )

    class Llm:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system, prompt):
            self.calls += 1
            payload = json.loads(prompt)
            if self.calls == 1:
                return factor_four
            contract = payload["anti_repeat_contract"]
            assert first_action["semantic_signature"] in contract[
                "rejected_action_signatures"
            ]
            assert "forbidden_optimization_families" not in contract
            assert "forbidden_targets" not in contract
            assert "overrides optimization_patterns" in contract["priority"]
            assert payload["previous_candidate_feedback"]["status"] == (
                "REJECTED_BY_SCORING_V3_Q_HW"
            )
            return factor_eight

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
        best_latency=1000,
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
    assert server.csim_calls == 2
    assert server.synth_calls == 2
    assert result.metadata["anti_repeat_action_rejections"] == 0
    assert len(result.metadata["measured_rejected_actions"]) == 2


def test_reordered_pipeline_on_unknown_ii_loop_is_measured_once_then_blocked() -> None:
    task = SimpleNamespace(
        id="burst_rw_repeat",
        type="repair",
        difficulty=3,
        requires_cosim=False,
        budget=60,
        clock_ns=5.0,
        description="Optimize burst read/write after compile repair.",
        headers={},
        top="vadd",
        kernel_name="vadd.cpp",
    )
    starter_report = _report(
        latency=100,
        ii=101,
        clock=3.65,
        lut=1900,
        ff=1470,
        dsp=0,
        loop_metrics=[
            {"name": "read_buf", "pipeline_ii": None},
            {"name": "calc_write", "pipeline_ii": 1},
        ],
    )
    rejected_report = _report(
        latency=300,
        ii=301,
        clock=3.65,
        lut=1700,
        ff=1400,
        dsp=0,
        loop_metrics=[{"name": "read_buf", "pipeline_ii": None}],
    )
    starter = """void vadd(int *a, int size) {
read_buf:
  for (int i = 0; i < size; i += 16) {
    #pragma HLS LOOP_TRIPCOUNT min=1 max=64
    a[i] += 1;
  }
}
"""
    first = starter.replace(
        "    #pragma HLS LOOP_TRIPCOUNT",
        "    #pragma HLS PIPELINE II=11\n"
        "    #pragma HLS LOOP_TRIPCOUNT",
    )
    reordered = starter.replace(
        "    a[i] += 1;",
        "    #pragma HLS PIPELINE II=11\n"
        "    a[i] += 1;",
    )

    first_action = candidate_action_summary(
        starter, first, top_function="vadd"
    )
    reordered_action = candidate_action_summary(
        starter, reordered, top_function="vadd"
    )
    assert first_action["targets"]["loops"] == ["read_buf"]
    assert first_action["semantic_signature"] == reordered_action[
        "semantic_signature"
    ]
    assert _candidate_fingerprint(first) != _candidate_fingerprint(reordered)

    class Llm:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system, prompt):
            self.calls += 1
            if self.calls > 1:
                raise AssertionError(
                    "no report-supported alternative means no second LLM call"
                )
            return first

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
    assert llm.calls == 1
    assert server.csim_calls == 1
    assert server.synth_calls == 1
    assert result.metadata["report_evidence_action_rejections"] == 0
    assert result.metadata["anti_repeat_action_rejections"] == 0
    assert result.metadata["report_supported_convergence"] is True
    assert "no distinct evidence-backed action signature" in result.metadata[
        "optimization_convergence_reason"
    ]
    assert "semantic equivalent" in (
        _anti_repeat_action_violation(
            reordered_action,
            [{"action": first_action}],
        )
        or ""
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
