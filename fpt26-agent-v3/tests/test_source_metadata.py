from __future__ import annotations

import json

from agent.analysis.source_metadata import (
    bounded_metadata_payload,
    extract_design_metadata,
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
