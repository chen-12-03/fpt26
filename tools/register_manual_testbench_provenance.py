#!/usr/bin/env python3
"""Register provenance for the manually authored Track-A test pairs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


RECORDS = {
    "compile_repair__18__amd_accel__performance_axi_burst_performance_src_test_kernel_maxi_512bit_6": (
        "separate_read_and_write_mode_vectors_at_non_degenerate_length",
        "explicit_memory_and_performance_counter_oracle",
    ),
    "compile_repair__24__amd_intro__interface_aggregation_disaggregation_auto_disaggregation_of_struct": (
        "distinct_affine_stream_and_array_fields",
        "independent_closed_form_struct_sum",
    ),
    "compile_repair__25__c2hlsc__des": (
        "fips_vector_public_and_all_zero_vector_hidden",
        "independent_published_des_known_answer_vectors",
    ),
    "qor_optimization__23__amd_accel__host_xrt_multiple_cus_asymmetrical_xrt_src_vadd": (
        "different_lengths_and_nonlinear_operand_vectors",
        "independent_elementwise_addition_oracle",
    ),
    "qor_optimization__25__amd_perf__security_adler32": (
        "affine_public_bytes_and_lcg_hidden_bytes_at_different_lengths",
        "independent_software_adler32_oracle",
    ),
    "synthesis_repair__19__rosetta__spam_filter__dotProduct": (
        "three_structured_public_vectors_and_four_seeded_sparse_hidden_vectors",
        "independent_exact_fixed_point_dot_product_oracle_with_input_immutability_checks",
    ),
    "synthesis_repair__21__rosetta__spam_filter__computeGradient": (
        "three_structured_public_vectors_and_four_seeded_scaled_hidden_vectors",
        "independent_per_element_fixed_point_gradient_oracle_with_input_immutability_checks",
    ),
    "synthesis_repair__20__gnnbuilder__compute_neighbor_tables": (
        "distinct_graph_sizes_and_deterministic_edge_lists",
        "independent_degree_offset_and_neighbor_table_oracle",
    ),
    "synthesis_repair__24__gnnbuilder__gather_node_neighbors": (
        "distinct_node_degree_offset_and_neighbor_values",
        "independent_elementwise_gather_oracle",
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--pair-evidence-root", type=Path, required=True)
    args = parser.parse_args()
    written = []
    for task_id, (derivation, oracle) in RECORDS.items():
        task_dir = args.task_root / task_id
        spec = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
        evidence = args.pair_evidence_root / "tasks" / task_id / "pair_validation.json"
        validation = json.loads(evidence.read_text(encoding="utf-8"))
        if validation.get("passed") is not True:
            raise RuntimeError(f"{task_id}: full pair validation did not pass")
        public_tb = task_dir / str(spec["public_tb"])
        hidden_tb = task_dir / "hidden" / str(spec["hidden_tb"])
        payload = {
            "schema_version": 1,
            "task_id": task_id,
            "public_input_derivation": derivation.split("_and_")[0],
            "hidden_input_derivation": derivation,
            "oracle_strategy": oracle,
            "public_testbench_preserved": False,
            "self_contained_testbench": True,
            "validation_evidence": str(evidence),
            "public_tb_sha256": sha256(public_tb),
            "hidden_tb_sha256": sha256(hidden_tb),
            "public_golden_sha256": {},
            "hidden_golden_sha256": {},
            "hidden_fixture_sha256": {},
            "limitations": [
                "Early-return rejection is a minimum sanity mutation, not a complete mutation score."
            ],
        }
        destination = task_dir / "hidden" / "testbench_provenance.json"
        destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        written.append(task_id)
    print(json.dumps({"written_count": len(written), "task_ids": written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
