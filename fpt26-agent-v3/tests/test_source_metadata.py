from __future__ import annotations

import json

from agent.analysis.source_metadata import (
    bounded_metadata_payload,
    evaluate_source_banking_trial,
    extract_design_metadata,
    source_architecture_evidence,
    source_reduction_parallelism_evidence,
    source_supported_banking_evidence,
)


def test_extracts_nested_loops_trip_counts_pragmas_and_report_names() -> None:
    source = """
void top(float matrix[8][16], int n) {
outer: for (int i = 0; i < 8; ++i) {
  #pragma   HLS   PIPELINE   II = 1
  inner: for (int j = 2; j <= 14; j += 2) {
    #pragma HLS UNROLL factor = 2
    matrix[i][j] += 1;
  }
}
}
"""
    metrics = [
        {"name": "outer", "trip_count": 8, "pipeline_ii": 1},
        {"name": "inner", "trip_count": 7, "pipeline_ii": 1},
    ]

    metadata = extract_design_metadata(source, loop_metrics=metrics).to_dict()
    loops = metadata["loops"]

    assert [loop["label"] for loop in loops] == ["outer", "inner"]
    assert [loop["nesting_depth"] for loop in loops] == [0, 1]
    assert loops[0]["trip_count"] == 8
    assert loops[0]["pipeline"] == {"enabled": True, "ii": 1}
    assert loops[0]["report_loop_name"] == "outer"
    assert loops[1]["trip_count"] == 7
    assert loops[1]["pipeline"]["enabled"] is False
    assert loops[1]["unroll"] == {"enabled": True, "factor": 2}
    assert loops[1]["report_loop_name"] == "inner"


def test_dynamic_loop_bounds_are_preserved_without_guessing_trip_count() -> None:
    source = """
void top(int *a, int n) {
  for (int k = 1; k < n; k += 3) {
    a[k] += 1;
  }
}
"""

    loop = extract_design_metadata(source).to_dict()["loops"][0]

    assert loop["induction_variable"] == "k"
    assert loop["lower_bound"] == "1"
    assert loop["upper_bound"] == "n"
    assert loop["step"] == "3"
    assert loop["trip_count"] == "unknown"
    assert loop["report_loop_name"] == "unknown"


def test_extracts_array_shapes_partition_reshape_and_access_patterns() -> None:
    source = """
void top(int a[64], float matrix[8][8], int coeff[16]) {
#pragma HLS ARRAY_PARTITION variable = a complete dim = 1
#pragma HLS ARRAY_PARTITION variable=matrix type=cyclic factor=4 dim=2
#pragma HLS ARRAY_PARTITION variable=coeff block factor = 2 dim = 1
#pragma HLS ARRAY_RESHAPE variable = matrix type = block factor=2 dim=1
  for (int i = 0; i < 64; ++i) {
    a[i] += coeff[3];
    matrix[i * 2][0] += 1;
  }
}
"""

    arrays = {
        item["name"]: item
        for item in extract_design_metadata(source).to_dict()["arrays"]
    }

    assert arrays["a"]["element_type"] == "int"
    assert arrays["a"]["rank"] == 1
    assert arrays["a"]["extents"] == ["64"]
    assert arrays["a"]["partition"] == {
        "type": "complete",
        "factor": "unknown",
        "dim": 1,
    }
    assert arrays["a"]["access_pattern"] == {
        "kind": "contiguous",
        "stride": 1,
    }
    assert arrays["matrix"]["rank"] == 2
    assert arrays["matrix"]["extents"] == ["8", "8"]
    assert arrays["matrix"]["partition"]["type"] == "cyclic"
    assert arrays["matrix"]["partition"]["factor"] == 4
    assert arrays["matrix"]["reshape"] == {
        "type": "block",
        "factor": 2,
        "dim": 1,
    }
    assert arrays["matrix"]["access_pattern"] == {
        "kind": "fixed_stride",
        "stride": 2,
    }
    assert arrays["coeff"]["partition"]["type"] == "block"
    assert arrays["coeff"]["access_pattern"]["kind"] == "constant_index"


def test_no_pragmas_and_incomplete_source_degrade_safely() -> None:
    no_pragmas = extract_design_metadata(
        "void top(int a[4]) { for (int i=0; i<4; ++i) a[i]++; }"
    ).to_dict()
    assert no_pragmas["loops"][0]["pipeline"]["enabled"] is False
    assert no_pragmas["loops"][0]["unroll"]["enabled"] is False
    assert no_pragmas["arrays"][0]["partition"] == "none"
    assert no_pragmas["arrays"][0]["reshape"] == "none"

    incomplete = extract_design_metadata(
        "void top(int broken[8]) { for (int i = 0; i <"
    )
    payload = incomplete.to_dict()
    assert payload["arrays"][0]["name"] == "broken"
    assert payload["loops"] == []
    json.dumps(payload, sort_keys=True)


def test_pointer_parameter_is_reported_with_unknown_shape_and_access() -> None:
    source = """
void top(const float *input, float output[64]) {
  for (int i=0; i<64; ++i) {
    #pragma HLS PIPELINE II=1
    output[i] = input[i];
  }
}
"""

    metadata = extract_design_metadata(source).to_dict()
    arrays = {item["name"]: item for item in metadata["arrays"]}
    loop = metadata["loops"][0]

    assert arrays["input"]["element_type"] == "const float"
    assert arrays["input"]["rank"] == "unknown"
    assert arrays["input"]["extents"] == ["unknown"]
    assert arrays["input"]["access_pattern"] == {
        "kind": "contiguous",
        "stride": 1,
    }
    assert loop["pipeline"] == {"enabled": True, "ii": 1}


def test_metadata_serialization_is_deterministic_and_prompt_payload_bounded() -> None:
    arrays = ", ".join(f"int a{i}[1024]" for i in range(80))
    accesses = "\n".join(f"a{i}[i] += 1;" for i in range(80))
    source = (
        f"void top({arrays}) {{\n"
        "for (int i=0; i<1024; ++i) {\n"
        f"{accesses}\n"
        "}\n}\n"
    )

    first = extract_design_metadata(source)
    second = extract_design_metadata(source)
    assert first.to_json() == second.to_json()

    payload = bounded_metadata_payload(first, max_chars=2_000)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert len(encoded) <= 2_000
    assert payload["truncated"] is True
    assert payload["loop_count"] == 1
    assert payload["array_count"] == 80
    assert payload["loops"]
    assert payload["arrays"]


def test_default_prompt_projection_is_compact_and_retains_required_fields() -> None:
    source = """
void top(int a[64], int b[64]) {
outer: for (int i=0; i<64; ++i) {
  #pragma HLS PIPELINE II=1
  #pragma HLS UNROLL factor=2
  a[i] = b[i];
}
}
"""

    payload = bounded_metadata_payload(extract_design_metadata(source))
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )

    assert len(encoded) <= 700
    assert payload["loop_count"] == 1
    assert payload["array_count"] == 2
    assert payload["loops"][0]["name"] == "outer"
    assert payload["loops"][0]["pipeline_ii"] == 1
    assert payload["loops"][0]["unroll_factor"] == 2
    assert payload["arrays"][0]["name"] == "a"
    assert payload["arrays"][0]["rank"] == 1


def test_empty_or_non_text_source_returns_empty_metadata() -> None:
    empty = extract_design_metadata(None).to_dict()
    assert empty["loops"] == []
    assert empty["arrays"] == []
    assert empty["parse_status"] == "empty"


def test_source_architecture_evidence_detects_connected_helper_stages() -> None:
    source = """
void load(int *in, int tmp[64]) {
  for (int i = 0; i < 64; ++i) tmp[i] = in[i];
}
void compute(int tmp[64], int out[64]) {
  for (int i = 0; i < 64; ++i) out[i] = tmp[i] + 1;
}
void top(int *in, int *out) {
  int tmp[64];
  load(in, tmp);
  compute(tmp, out);
}
"""

    evidence = source_architecture_evidence(source, top_function="top")

    assert len(evidence) == 1
    assert evidence[0]["kind"] == "source_connected_task_pipeline"
    assert evidence[0]["stage_calls"] == ["load", "compute"]
    assert evidence[0]["connectors"] == ["tmp"]
    assert evidence[0]["connector_kinds"] == {"tmp": "local_array"}
    assert evidence[0]["candidate_families"] == [
        "TASK_PIPELINE",
        "SOURCE_RESTRUCTURE",
    ]


def test_source_architecture_evidence_detects_stream_connectors() -> None:
    source = """
#include <hls_stream.h>
void produce(int *in, hls::stream<int> &s) { s.write(*in); }
void consume(hls::stream<int> &s, int *out) { *out = s.read(); }
void top(int *in, int *out) {
  hls::stream<int> channel;
  produce(in, channel);
  consume(channel, out);
}
"""

    evidence = source_architecture_evidence(source, top_function="top")

    assert evidence[0]["connectors"] == ["channel"]
    assert evidence[0]["connector_kinds"] == {"channel": "stream"}


def test_source_architecture_evidence_requires_connection_and_missing_dataflow() -> None:
    disconnected = """
void a(int *x) { *x += 1; }
void b(int *y) { *y += 1; }
void top(int *x, int *y) { a(x); b(y); }
"""
    already_dataflow = """
void a(int x[4], int t[4]) { t[0] = x[0]; }
void b(int t[4], int y[4]) { y[0] = t[0]; }
void top(int x[4], int y[4]) {
  int t[4];
#pragma HLS DATAFLOW
  a(x, t); b(t, y);
}
"""

    assert source_architecture_evidence(
        disconnected, top_function="top"
    ) == []
    assert source_architecture_evidence(
        already_dataflow, top_function="top"
    ) == []


def test_reduction_parallelism_uses_only_named_source_factor_candidates() -> None:
    source = """
float top(float a[SIZE], float b[SIZE]) {
  float sum = 0;
REDUCE:
  for (int i = 0; i < SIZE; ++i) {
    sum += a[i] * b[i];
  }
  return sum;
}
"""
    header = """
const int SIZE = 1024;
#define DATA_WIDTH 16
#define PAR_FACTOR 32
"""

    evidence = source_reduction_parallelism_evidence(
        source,
        top_function="top",
        constant_context=header,
    )

    assert len(evidence) == 1
    assert evidence[0]["kind"] == "source_affine_reduction_parallelism"
    assert evidence[0]["loop"] == "REDUCE"
    assert evidence[0]["accumulator"] == "sum"
    assert evidence[0]["input_arrays"] == ["a", "b"]
    assert evidence[0]["factor_candidates"] == [
        {"name": "PAR_FACTOR", "value": 32}
    ]
    assert evidence[0]["composite_family"] == "REDUCTION_PARALLELISM"


def test_reduction_parallelism_does_not_invent_an_unlisted_factor() -> None:
    source = """
float top(float a[64]) {
  float sum = 0;
  for (int i = 0; i < 64; ++i) sum += a[i];
  return sum;
}
"""

    assert source_reduction_parallelism_evidence(
        source,
        top_function="top",
        constant_context="const int SIZE = 64;",
    ) == []


def test_source_evidence_respects_inferred_hierarchy_and_affine_banking() -> None:
    source = """
void top(int *in1, int *in2, int *out) {
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
    inferred = [
        {
            "kind": "pipeline",
            "target": "top/middle",
            "function": "top",
            "scope": "middle",
        },
        {
            "kind": "loop_flatten",
            "target": "top/outer",
            "function": "top",
            "scope": "outer",
        },
    ]

    metadata = extract_design_metadata(
        source,
        inferred_directives=inferred,
        constant_context="#define MAX_DIM 16\n",
    )
    loops = {item["label"]: item for item in metadata.loops}
    evidence = {
        item["array"]: item
        for item in source_supported_banking_evidence(metadata)
    }

    assert loops["inner"]["trip_count"] == 16
    assert loops["inner"]["auto_parallelism"]["pipeline_ancestors"] == [
        "middle"
    ]
    assert loops["inner"]["auto_parallelism"]["hierarchy_sensitive"] is True
    assert loops["outer"]["auto_parallelism"]["flatten"] is True
    assert set(evidence) == {"A", "B"}
    assert evidence["A"] == {
        "kind": "source_affine_parallel_reads",
        "array": "A",
        "loop": "inner",
        "dimension": 1,
        "index_expression": "i*MAX_DIM+k",
        "lane_stride": 1,
        "array_extent": 256,
        "concurrent_lanes": 16,
        "factor_limit": 16,
        "banking_option_space": {
            "pragma_classes": ["ARRAY_PARTITION", "ARRAY_RESHAPE"],
            "partition_types": ["cyclic"],
            "factor_min": 2,
            "factor_max": 16,
            "dimension": 1,
            "selection_rule": (
                "Select a factor/type only when evaluate_source_banking_trial "
                "proves more than one distinct bank for the affine access map; "
                "compare every selected point by measured Q_HW."
            ),
        },
        "reshape_eligible": True,
        "banking_model": {
            "cyclic": "bank=index mod factor",
            "block": "bank=floor(index/ceil(array_extent/factor))",
        },
        "co_read_arrays": ["A", "B"],
        "reason": (
            "local array A is read with affine lane stride 1 in "
            "auto-parallel compute loop inner"
        ),
    }
    assert evidence["B"]["dimension"] == 1
    assert evidence["B"]["lane_stride"] == 16
    assert evidence["B"]["array_extent"] == 256
    assert evidence["B"]["factor_limit"] == 16
    assert evidence["B"]["reshape_eligible"] is False
    assert evidence["B"]["banking_option_space"] == {
        "pragma_classes": ["ARRAY_PARTITION"],
        "partition_types": ["cyclic", "block"],
        "factor_min": 2,
        "factor_max": 16,
        "dimension": 1,
        "selection_rule": (
            "Select a factor/type only when evaluate_source_banking_trial "
            "proves more than one distinct bank for the affine access map; "
            "compare every selected point by measured Q_HW."
        ),
    }
    assert all(item["array"] not in {"in1", "in2"} for item in evidence.values())


def test_affine_reads_without_proven_concurrent_lanes_do_not_enable_banking() -> None:
    source = """
void top(int *out) {
  int A[16];
  int B[256];
inner:
  for (int k = 0; k < 16; ++k) {
    out[0] += A[k] * B[k * 16];
  }
}
"""

    metadata = extract_design_metadata(source)

    assert source_supported_banking_evidence(metadata) == []


def test_one_local_array_is_enough_when_concurrent_lanes_are_proven() -> None:
    source = """
void top(int *out) {
  int A[32];
outer:
  for (int i = 0; i < 2; ++i) {
inner:
    for (int k = 0; k < 32; ++k) {
      out[i] += A[k];
    }
  }
}
"""
    metadata = extract_design_metadata(
        source,
        inferred_directives=[
            {
                "kind": "pipeline",
                "target": "top/outer",
                "scope": "outer",
            }
        ],
    )

    evidence = source_supported_banking_evidence(metadata)

    assert [item["array"] for item in evidence] == ["A"]
    assert evidence[0]["concurrent_lanes"] == 32
    assert evidence[0]["factor_limit"] == 32


def test_bank_mapping_replaces_fixed_factor_sixteen_rules() -> None:
    contiguous = {
        "array_extent": 1024,
        "concurrent_lanes": 32,
        "lane_stride": 1,
        "factor_limit": 32,
        "reshape_eligible": True,
    }
    strided = {
        "array_extent": 1024,
        "concurrent_lanes": 32,
        "lane_stride": 32,
        "factor_limit": 32,
        "reshape_eligible": False,
    }

    cyclic_32 = evaluate_source_banking_trial(
        contiguous,
        pragma_class="ARRAY_PARTITION",
        partition_type="cyclic",
        factor=32,
    )
    block_32 = evaluate_source_banking_trial(
        strided,
        pragma_class="ARRAY_PARTITION",
        partition_type="block",
        factor=32,
    )
    conflicting_cyclic = evaluate_source_banking_trial(
        strided,
        pragma_class="ARRAY_PARTITION",
        partition_type="cyclic",
        factor=32,
    )
    reshape = evaluate_source_banking_trial(
        contiguous,
        pragma_class="ARRAY_RESHAPE",
        partition_type="cyclic",
        factor=4,
    )

    assert cyclic_32["supported"] is True
    assert cyclic_32["distinct_banks"] == 32
    assert block_32["supported"] is True
    assert block_32["distinct_banks"] == 32
    assert conflicting_cyclic["supported"] is False
    assert conflicting_cyclic["distinct_banks"] == 1
    assert reshape["supported"] is True
