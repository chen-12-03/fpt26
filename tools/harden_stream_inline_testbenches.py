#!/usr/bin/env python3
"""Stage and dynamically validate self-contained hidden stream testbenches.

This is intentionally a small, audited set of source-to-source rewrites for
AMD introductory examples whose inputs are injected with stream ``write``
calls.  Each rewrite changes the DUT input and updates an explicit software
oracle in the hidden bench.  Nothing is promoted by this script.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from agent.testbench import normalize_task_testbench_data
from build_track_a_150 import _inject_early_return
from harden_track_a_testbench_transcripts import _run
from llm4hls.task import load_task


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _replace(source: str, old: str, new: str, *, count: int | None = None) -> str:
    found = source.count(old)
    expected = found if count is None else count
    if found != expected or found == 0:
        raise RuntimeError(
            f"rewrite precondition failed for {old!r}: found {found}, expected {expected}"
        )
    return source.replace(old, new)


def _compile03(source: str) -> str:
    return _replace(
        source,
        "i+j",
        "(3 * static_cast<int>(i) + 2 * static_cast<int>(j) + 17)",
        count=3,
    )


def _compile16(source: str) -> str:
    source = _replace(source, "tmp.data = {i, i};", "tmp.data = {2 * i + 7, 3 * i + 11};", count=1)
    source = _replace(source, "tmp_c.data.real(i + 5);", "tmp_c.data.real(2 * i + 12);", count=1)
    return _replace(source, "tmp_c.data.imag(i + 1);", "tmp_c.data.imag(3 * i + 12);", count=1)


def _compile23(source: str, *, hidden: bool) -> str:
    expression = "i * 17 + 3" if hidden else "i"
    source = _replace(source, "dataStream_t.data = i;", f"dataStream_t.data = {expression};", count=1)
    return _replace(
        source,
        "    example(inStream_t, out_t);\n    return err;",
        "    example(inStream_t, out_t);\n"
        "    for (int i = 0; i < 1024; ++i) {\n"
        f"        if (out_t[i] != ap_uint<64>({expression})) ++err;\n"
        "    }\n"
        "    if (err) return 1;\n"
        "    return 0;",
        count=1,
    )


def _functional12(source: str) -> str:
    return _replace(source, "tmp1.user = j;", "tmp1.user = 3 * j + 7;", count=1)


def _functional25(source: str) -> str:
    source = _replace(source, ".write(i);", ".write(3 * i + 7);", count=4)
    return _replace(source, "2 * i", "4 * i + 7", count=8)


def _qor05(source: str) -> str:
    source = _replace(source, "in << i;", "in << 7 * i - 11;", count=1)
    return _replace(source, "var != p", "var != 7 * p - 11", count=1)


def _struct06(source: str) -> str:
    source = _replace(source, "in1.write(i);", "in1.write(2 * i + 3);", count=1)
    source = _replace(source, "in2.write(i);", "in2.write(5 * i - 7);", count=1)
    return _replace(source, "golden[i] = 2*i;", "golden[i] = 7 * i - 4;", count=1)


def _struct20(source: str) -> str:
    source = _replace(source, "s_in[j].write(i);", "s_in[j].write(3 * i + 5);", count=1)
    source = _replace(source, "s_out[j].read() != i + 2", "s_out[j].read() != 3 * i + 7", count=1)
    return _replace(
        source,
        "    return 0;",
        "    if (ret != M * 185) return 1;\n\n    return 0;",
        count=1,
    )


def _struct21(source: str) -> str:
    return _replace(source, "tmp1.data = j;", "tmp1.data = 4 * j + 9;", count=1)


def _struct23(source: str) -> str:
    source = _replace(
        source,
        "    for (int i = 0; i < N; i++)\n        in.write(i);",
        "    int expected1 = 0, expected2 = 0;\n"
        "    for (int i = 0; i < N; i++) {\n"
        "        int value = i + 2;\n"
        "        in.write(value);\n"
        "        if (value % 2) expected1 += value + 1;\n"
        "        else expected2 += value + 2;\n"
        "    }",
        count=1,
    )
    return _replace(
        source,
        "    if ((sum1 != 30) && (sum2 != 30))",
        "    if (sum1 != expected1 || sum2 != expected2)",
        count=1,
    )


def _struct24_25(source: str) -> str:
    source = _replace(source, "        n.write(i);", "        n.write(3 * i + 5);", count=1)
    source = _replace(source, "        in.write(i);", "        in.write(2 * i - 7);", count=1)
    return _replace(source, "golden += 2*i;", "golden += 5 * i - 2;", count=1)


def _synth01(source: str) -> str:
    source = _replace(source, ".write(i);", ".write(3 * i + 1);", count=4)
    return _replace(source, "sum != 480", "sum != 1504", count=1)


def _synth02(source: str) -> str:
    return _replace(source, "a.write(j);", "a.write((j + 1) % 4);", count=1)


def _synth07(source: str) -> str:
    source = _replace(source, "test.write(i);", "test.write(3 * i + 7);", count=1)
    source = _replace(
        source,
        "            FILE << (int)outp << endl;",
        "            FILE << (int)outp << endl;\n"
        "            if ((int)outp != ((45 * i + 130) & 0xff)) retval = 1;",
        count=1,
    )
    start = source.index("    // Compare the results file with the golden results")
    end = source.index("    // Return 0 if the test passed", start)
    replacement = (
        "    // The hidden oracle is the independent closed-form composition:\n"
        "    // (3*x + 25) + 2*(6*x) = 15*x + 25.\n"
        "    if (retval) cout << \"Test failed  !!!\" << endl;\n"
        "    else cout << \"Test passed !\" << endl;\n\n"
    )
    return source[:start] + replacement + source[end:]


def _codegen10(source: str, *, hidden: bool) -> str:
    if hidden:
        source = _replace(source, "int main() {", "int main() {\n    srand(73);", count=1)
    return _replace(source, "    return 0;", "    return fail ? 1 : 0;", count=1)


def _compile05(source: str) -> str:
    return _replace(source, "a[i] = i;", "a[i] = 7 * i - 13;", count=1)


def _compile10_13(source: str) -> str:
    source = _replace(source, "in[i] = i;", "in[i] = 5 * i - 23;", count=1)
    source = _replace(source, "a[i] = i;", "a[i] = 5 * i - 23;", count=1)
    return _replace(source, "out[i] != a[i]", "out[j * size + i] != a[i]", count=1)


def _matmul_seed(source: str) -> str:
    return _replace(source, "dist(0, 10)", "dist(-7, 13)", count=1)


def _pointer07(source: str) -> str:
    include = source[source.index("#include <stdlib.h>"):source.index("int main()")]
    return include + r'''int main() {
  const din_t positions[] = {7, 0, 5, 2, 6, 1, 4, 3};
  const sel_t selectors[] = {true, false, false, true, true, false, true, false};
  for (int i = 0; i < 8; ++i) {
    const int pos = positions[i];
    const int expected = selectors[i] ? pos + 1 : 8 - pos;
    if (pointer_multi(selectors[i], positions[i]) != expected) return 1;
  }
  return 0;
}
'''


def _add128(source: str) -> str:
    prefix = source[:source.index("int main()")]
    return prefix + r'''int main() {
    const bits64 inputs[][4] = {
        {0xFEDCBA9876543210ULL, 0x0123456789ABCDEFULL,
         0x123456789ABCDEF0ULL, 0x0FEDCBA987654321ULL},
        {0x8000000000000000ULL, 0x7FFFFFFFFFFFFFFFULL,
         0x8000000000000000ULL, 0x0000000000000001ULL},
        {0xDEADBEEF01234567ULL, 0xCAFEBABE76543210ULL,
         0x13579BDF2468ACE0ULL, 0x1020304050607080ULL},
    };
    for (unsigned i = 0; i < sizeof(inputs) / sizeof(inputs[0]); ++i) {
        bits64 z0 = 0, z1 = 0;
        add128(inputs[i][0], inputs[i][1], inputs[i][2], inputs[i][3], &z0, &z1);
        unsigned __int128 a = (static_cast<unsigned __int128>(inputs[i][0]) << 64) | inputs[i][1];
        unsigned __int128 b = (static_cast<unsigned __int128>(inputs[i][2]) << 64) | inputs[i][3];
        unsigned __int128 expected = a + b;
        if (z0 != static_cast<bits64>(expected >> 64) ||
            z1 != static_cast<bits64>(expected)) return 1;
    }
    return 0;
}
'''


def _srand173(source: str) -> str:
    old = "{\n  printf(\"----------------------------------------------------------------------------\\n\");"
    new = "{\n  srand(173);\n  printf(\"----------------------------------------------------------------------------\\n\");"
    return _replace(source, old, new, count=1)


def _qor01(source: str) -> str:
    source = _replace(source, "Atest[i] = i;", "Atest[i] = 2 * i + 3;", count=1)
    source = _replace(source, "strm << i;", "strm << 5 * i - 4;", count=1)
    start = source.index("    // Compare the results file with the golden results")
    end = source.index("    // Return 0 if the test passes", start)
    check = (
        "    // Independent sum: sum((2i+3)+i+(5i-4)), i in [0,SZ).\n"
        "    retval = (total == 216) ? 0 : 1;\n\n"
    )
    return source[:start] + check + source[end:]


def _qor02(source: str) -> str:
    source = _replace(source, "shift.data = i+j;", "shift.data = 3 * (i + j) + 7;", count=1)
    return _replace(source, "temp != i", "temp != 3 * i + 7", count=1)


def _struct04(source: str) -> str:
    source = _replace(source, "A[i] = i;", "A[i] = 7 * i - 9;", count=1)
    return _replace(source, "B[i] = i + 100;", "B[i] = 7 * i + 91;", count=1)


def _struct07_08(source: str) -> str:
    source = _replace(source, "int j = 5;", "int j = 2;", count=1)
    return _replace(source, "int golden = 36;", "int golden = 45;", count=1)


def _struct09(source: str) -> str:
    source = _replace(source, "in[i] = i;", "in[i] = 7 * i - 9;", count=1)
    return _replace(source, "res[i] != i + 100", "res[i] != 7 * i + 91", count=1)


def _struct10(source: str) -> str:
    source = _replace(source, "cpp_template(i, &total_dut);", "cpp_template(2 * i + 3, &total_dut);", count=1)
    return _replace(source, "825 != total_dut", "2475 != total_dut", count=1)


def _struct12(source: str) -> str:
    source = _replace(source, "arr[i].foo = i;", "arr[i].foo = 2 * i + 3;", count=1)
    source = _replace(source, "arr[i].bar = i;", "arr[i].bar = 5 * i - 7;", count=1)
    return _replace(source, "ret != 90", "ret != 275", count=1)


def _struct18(source: str) -> str:
    for old, new in (
        ("i * 4;", "2 * (i * 4) + 3;"),
        ("i * 4 + 1;", "2 * (i * 4 + 1) + 3;"),
        ("i * 4 + 2;", "2 * (i * 4 + 2) + 3;"),
        ("i * 4 + 3;", "2 * (i * 4 + 3) + 3;"),
    ):
        source = _replace(source, old, new, count=1)
    return _replace(source, "ret != 780", "ret != 1680", count=1)


def _struct19(source: str) -> str:
    source = _replace(
        source,
        "    for (unsigned i = 0; i < N; i++)\n        arr[i].c = arr[i].i = i;",
        "    for (unsigned i = 0; i < N; i++) {\n"
        "        arr[i].c = 3 * i + 1;\n"
        "        arr[i].i = 5 * i + 7;\n"
        "    }",
        count=1,
    )
    return _replace(source, "out[i].c != i || out[i].i != i", "out[i].c != 3 * i + 1 || out[i].i != 5 * i + 7", count=1)


def _struct22(source: str) -> str:
    source = _replace(source, "tmp1.data = i;", "tmp1.data = 3 * i + 1;", count=1)
    source = _replace(source, "mem[i] = i;", "mem[i] = 5 * i - 7;", count=1)
    source = _replace(source, "tmp2.data != i*2", "tmp2.data != 8 * i - 6", count=1)
    return _replace(source, '"i *2 =" << i*2', '"expected =" << 8 * i - 6', count=1)


def _synth03(source: str) -> str:
    source = _replace(source, "in.write(i);", "in.write(3 * i - 5);", count=1)
    return _replace(source, "val != i * 23 * 11", "val != (3 * i - 5) * 23 * 11", count=1)


def _synth14(source: str) -> str:
    source = _replace(source, "A[i] = N / 4 - i;", "A[i] = 3 * i - 2 * N;", count=1)
    source = _replace(source, "B[i] = N - 1 - i;", "B[i] = 5 * i + 7;", count=1)
    return _synth14_public(source)


def _synth14_public(source: str) -> str:
    return _replace(
        source,
        "    // Return 0 if the test passed\n    return 0;",
        "    if (errval > 0) return 1;\n    return 0;",
        count=1,
    )


Transform = Callable[[str], str]

TRANSFORMS: dict[str, tuple[Transform, str]] = {
    "code_generation__10__pp4fpga__block_mm": (lambda s: _codegen10(s, hidden=True), "seeded_random_matrices_with_software_matmul_oracle"),
    "compile_repair__03__amd_intro__task_level_parallelism_control_driven_patterns_using_stream_as_sync": (_compile03, "two_dimensional_affine_stream_vector"),
    "compile_repair__05__amd_intro__task_level_parallelism_data_driven_mixed_control_and_data_driven": (_compile05, "signed_affine_array_with_elementwise_oracle"),
    "compile_repair__10__amd_intro__interface_memory_manual_burst_manual_burst_example_manual_burst_inference_success": (_compile10_13, "affine_burst_vector_with_all_replicas_checked"),
    "compile_repair__13__amd_intro__interface_memory_manual_burst_manual_burst_example_auto_burst_inference_failure": (_compile10_13, "affine_burst_vector_with_all_replicas_checked"),
    "compile_repair__16__amd_intro__interface_streaming_using_axi_stream_with_struct": (_compile16, "distinct_complex_stream_components"),
    "compile_repair__17__amd_intro__array_array_partition_complete": (_matmul_seed, "expanded_signed_rng_range_with_software_matmul_oracle"),
    "compile_repair__23__amd_intro__interface_streaming_axi_stream_to_master": (lambda s: _compile23(s, hidden=True), "affine_packet_payload_with_full_memory_oracle"),
    "functional_repair__07__amd_intro__modeling_pointers_multiple_pointers": (_pointer07, "permuted_pointer_indices_and_selectors_with_closed_form_oracle"),
    "functional_repair__12__amd_intro__interface_streaming_axi_stream_custom_side_channel_data_2": (_functional12, "affine_side_channel_user_values"),
    "functional_repair__19__chstone__df_add128": (_add128, "new_128_bit_edge_vectors_with_independent_uint128_oracle"),
    "functional_repair__23__amd_intro__modeling_using_array_stencil_2d": (_srand173, "fixed_distinct_rng_seed_with_software_filter_oracle"),
    "functional_repair__25__amd_intro__task_level_parallelism_data_driven_unique_task_regions": (_functional25, "affine_four_stream_vectors_with_counter_oracle"),
    "qor_optimization__01__amd_intro__pipelining_loops_using_free_running_pipeline": (_qor01, "asymmetric_array_and_stream_vectors_with_sum_oracle"),
    "qor_optimization__02__amd_intro__interface_memory_aliasing_axi_master_ports": (_qor02, "affine_packed_axi_values_with_elementwise_oracle"),
    "qor_optimization__05__amd_intro__modeling_free_running_kernel_remerge_ii4to1": (_qor05, "signed_affine_identity_stream_vector"),
    "structural_cosim_repair__04__amd_intro__interface_memory_using_axi_master": (_struct04, "signed_affine_memory_vector_with_software_oracle"),
    "structural_cosim_repair__06__amd_intro__task_level_parallelism_data_driven_using_directio_none_in_tasks": (_struct06, "asymmetric_dual_stream_vectors"),
    "structural_cosim_repair__07__amd_intro__misc_initialization_and_reset_static_array_of_struct_with_array_ram": (_struct07_08, "alternate_static_array_index_with_closed_form_oracle"),
    "structural_cosim_repair__08__amd_intro__misc_initialization_and_reset_static_array_ram": (_struct07_08, "alternate_static_array_index_with_closed_form_oracle"),
    "structural_cosim_repair__09__amd_intro__interface_memory_max_widen_port_width": (_struct09, "signed_affine_memory_vector_with_elementwise_oracle"),
    "structural_cosim_repair__10__amd_intro__modeling_cpp_templates_for_multiple_instances": (_struct10, "affine_call_sequence_with_static_accumulator_oracle"),
    "structural_cosim_repair__12__amd_intro__interface_aggregation_disaggregation_aggregation_of_m_axi_ports": (_struct12, "asymmetric_struct_fields_with_sum_oracle"),
    "structural_cosim_repair__16__amd_intro__array_array_partition_block_cyclic": (_matmul_seed, "expanded_signed_rng_range_with_software_matmul_oracle"),
    "structural_cosim_repair__18__amd_intro__interface_aggregation_disaggregation_aggregation_of_struct": (_struct18, "affine_struct_field_vector_with_sum_oracle"),
    "structural_cosim_repair__19__amd_intro__interface_aggregation_disaggregation_disaggregation_of_axis_port": (_struct19, "asymmetric_struct_fields_with_elementwise_oracle"),
    "structural_cosim_repair__20__amd_intro__interface_streaming_using_array_of_streams": (_struct20, "affine_stream_array_vectors_with_sum_oracle"),
    "structural_cosim_repair__21__amd_intro__interface_streaming_using_axi_stream_with_side_channel_data": (_struct21, "affine_axi_payload_values"),
    "structural_cosim_repair__22__amd_intro__task_level_parallelism_control_driven_directio_ap_hs": (_struct22, "asymmetric_packet_and_memory_vectors"),
    "structural_cosim_repair__23__amd_intro__task_level_parallelism_data_driven_simple_data_driven": (_struct23, "shifted_parity_vector_with_separate_sum_oracles"),
    "structural_cosim_repair__24__amd_intro__task_level_parallelism_data_driven_using_axilite_with_directio": (_struct24_25, "asymmetric_data_and_directio_vectors"),
    "structural_cosim_repair__25__amd_intro__task_level_parallelism_data_driven_using_directio_hs_in_tasks": (_struct24_25, "asymmetric_data_and_directio_vectors"),
    "synthesis_repair__01__amd_intro__task_level_parallelism_control_driven_channels_merge_split_merge_round_robin": (_synth01, "affine_four_channel_merge_vectors"),
    "synthesis_repair__02__amd_intro__task_level_parallelism_control_driven_channels_merge_split_split_round_robin": (_synth02, "rotated_round_robin_input_sequence"),
    "synthesis_repair__03__amd_intro__task_level_parallelism_data_driven_using_maxi_in_tasks": (_synth03, "signed_affine_stream_vector_with_closed_form_oracle"),
    "synthesis_repair__07__amd_intro__task_level_parallelism_control_driven_channels_using_stream_of_blocks": (_synth07, "affine_block_stream_with_closed_form_oracle"),
    "synthesis_repair__14__amd_intro__interface_memory_manual_burst_manual_burst_with_conditionals": (_synth14, "asymmetric_array_vectors_with_software_oracle"),
}


PUBLIC_TRANSFORMS: dict[str, Transform] = {
    "code_generation__10__pp4fpga__block_mm": lambda s: _codegen10(s, hidden=False),
    "compile_repair__23__amd_intro__interface_streaming_axi_stream_to_master": lambda s: _compile23(s, hidden=False),
    "synthesis_repair__14__amd_intro__interface_memory_manual_burst_manual_burst_with_conditionals": _synth14_public,
}


def harden_one(source_dir: Path, staging_root: Path, evidence_root: Path) -> dict[str, Any]:
    started = time.monotonic()
    staged = staging_root / source_dir.name
    checkpoint = evidence_root / source_dir.name / "hardening_evidence.json"
    if checkpoint.is_file() and staged.is_dir():
        return json.loads(checkpoint.read_text(encoding="utf-8"))
    if staged.exists():
        shutil.rmtree(staged)
    shutil.copytree(source_dir, staged)
    task = load_task(staged)
    transform, derivation = TRANSFORMS[task.id]
    hidden_path = staged / "hidden" / task.hidden_tb_name
    hidden_path.write_text(transform(task.public_tb_code), encoding="utf-8")
    public_preserved = task.id not in PUBLIC_TRANSFORMS
    if not public_preserved:
        (staged / task.public_tb_name).write_text(
            PUBLIC_TRANSFORMS[task.id](task.public_tb_code), encoding="utf-8"
        )

    task = load_task(staged)
    normalize_task_testbench_data(task, include_hidden=True)
    reference_hidden, _ = _run(task, task.reference_code, evidence_root / task.id / "reference_hidden", evidence_root.resolve(), use_hidden=True)
    reference_public, _ = _run(task, task.reference_code, evidence_root / task.id / "reference_public", evidence_root.resolve(), use_hidden=False)
    mutant, mutation = _inject_early_return(task.reference_code, task.top, 307)
    mutant_hidden, _ = _run(task, mutant, evidence_root / task.id / "early_return_hidden", evidence_root.resolve(), use_hidden=True)
    mutant_public, _ = _run(task, mutant, evidence_root / task.id / "early_return_public", evidence_root.resolve(), use_hidden=False)
    record = {
        "schema_version": 1,
        "purpose": "track_a_self_contained_stream_hidden_hardening",
        "task_id": task.id,
        "input_derivation": derivation,
        "public_input_derivation": "preserved_existing_public_testbench" if public_preserved else "public_oracle_completed_without_changing_public_vector",
        "oracle_strategy": "independent_explicit_software_or_closed_form_oracle",
        "self_contained_testbench": True,
        "public_testbench_preserved": public_preserved,
        "reference_hidden_pass": reference_hidden,
        "reference_public_pass": reference_public,
        "early_return_mutation": mutation,
        "early_return_rejected": not mutant_hidden,
        "public_early_return_rejected": not mutant_public,
        "public_hidden_byte_distinct": (staged / task.public_tb_name).read_bytes() != hidden_path.read_bytes(),
        "staged_task": str(staged),
        "elapsed_s": round(time.monotonic() - started, 3),
    }
    _atomic_json(checkpoint, record)
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--audit-json", type=Path)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    task_ids = list(args.task_id)
    if args.audit_json:
        audit = json.loads(args.audit_json.read_text(encoding="utf-8"))
        task_ids.extend(audit.get("public_clone_task_ids") or [])
    task_ids = sorted(set(task_ids) if task_ids else TRANSFORMS)
    unknown = sorted(set(task_ids).difference(TRANSFORMS))
    if unknown:
        raise SystemExit("no audited transform for: " + ", ".join(unknown))
    selected = [task_id for index, task_id in enumerate(task_ids) if index % args.shard_count == args.shard_index]
    records, failures = [], []
    for task_id in selected:
        try:
            records.append(harden_one(args.task_root / task_id, args.staging_root, args.evidence_root))
        except Exception as exc:
            failures.append({"task_id": task_id, "error": f"{type(exc).__name__}: {exc}"})
    keys = ("reference_hidden_pass", "reference_public_pass", "early_return_rejected", "public_early_return_rejected", "public_hidden_byte_distinct")
    summary = {
        "schema_version": 1,
        "purpose": "track_a_self_contained_stream_hidden_hardening_summary",
        "selected_task_count": len(selected),
        "task_count": len(records),
        "failure_count": len(failures),
        "passed_count": sum(all(record[key] for key in keys) for record in records),
        "failures": failures,
        "tasks": records,
    }
    _atomic_json(args.evidence_root / f"hardening_summary_shard_{args.shard_index:02d}.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not failures and summary["passed_count"] == len(selected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
