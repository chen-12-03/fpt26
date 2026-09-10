#!/usr/bin/env python3
"""Adjudicate the stratified Track-A mutation survivors with explicit evidence.

This script intentionally keeps the initial raw mutation rate separate from an
adjudicated rate.  Equivalent and undefined-behaviour mutants are never counted
as hidden-test kills, and every genuine gap marked as hardened must be rejected
by a later mutation-evidence record for the same task and operator.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ADJUDICATIONS: dict[tuple[str, str], tuple[str, str]] = {
    (
        "compile_repair__01__c2hlsc__add_round_key",
        "loop_bound",
    ): (
        "genuine_gap_hardened",
        "The extra i=4 iteration writes four bytes beyond the 4x4 state; the hardened hidden test places and checks boundary canaries.",
    ),
    (
        "compile_repair__13__amd_intro__interface_memory_manual_burst_manual_burst_example_auto_burst_inference_failure",
        "loop_bound",
    ): (
        "equivalent_for_functional_contract",
        "The extra input-copy iteration writes buf[size], but all output loops read only buf[0:size]; it cannot change a specified output element.",
    ),
    (
        "compile_repair__19__machsuite__spmv_crs",
        "literal",
    ): (
        "equivalent_for_exercised_domain",
        "The mutation changes Si's initialization from 0 to 1; every exercised row is nonempty and overwrites Si before it is accumulated.",
    ),
    (
        "compile_repair__25__c2hlsc__des",
        "comparison",
    ): (
        "genuine_gap_hardened",
        "Reversing encryption/decryption subkey order was masked by an all-zero key whose round subkeys are identical; nonuniform encrypt/decrypt KATs now reject it.",
    ),
    (
        "compile_repair__25__c2hlsc__des",
        "loop_bound",
    ): (
        "undefined_behaviour_mutant",
        "The i<=28 mutation reads key_perm_c[28] past a 28-element local table. Its value is outside the C++ contract and remained non-observable across three independent KAT keys.",
    ),
    (
        "functional_repair__07__amd_intro__modeling_pointers_multiple_pointers",
        "literal",
    ): (
        "equivalent_declaration_change",
        "Changing a local array extent from 8 to 9 does not change its initialized values or any accessed index.",
    ),
    (
        "qor_optimization__07__amd_accel__sys_opt_kernel_swap_src_krnl_vmul",
        "loop_bound",
    ): (
        "equivalent_zero_work_iteration",
        "The added outer iteration computes size=0 (or a negative size for the sampled short length), so every inner read/write loop executes zero times.",
    ),
    (
        "qor_optimization__19__polybench__lu",
        "literal",
    ): (
        "equivalent_zero_work_iteration",
        "Starting the outer loop at i=1 skips i=0, whose j<i loop has no iterations.",
    ),
    (
        "qor_optimization__25__amd_perf__security_adler32",
        "loop_bound",
    ): (
        "equivalent_guarded_iteration",
        "The added i=256 iteration is guarded by i<length; the hidden length is 251, so the body is unchanged.",
    ),
    (
        "structural_cosim_repair__01__amd_intro__interface_memory_burst_rw",
        "loop_bound",
    ): (
        "equivalent_zero_work_iteration",
        "At i=size the boundary calculation sets chunk_size=0, so the added burst iteration performs no reads or writes.",
    ),
    (
        "structural_cosim_repair__07__amd_intro__misc_initialization_and_reset_static_array_of_struct_with_array_ram",
        "literal",
    ): (
        "equivalent_unreachable_state",
        "The changed initializer is ts[1].A[0], but ts[i%2].A[i] can select ts[1] only for odd i; this element is unreachable for every valid index.",
    ),
    (
        "structural_cosim_repair__19__amd_intro__interface_aggregation_disaggregation_disaggregation_of_axis_port",
        "loop_bound",
    ): (
        "genuine_gap_hardened",
        "The added i=N iteration writes out[N]; the hardened test allocates one extra element and verifies an output boundary canary.",
    ),
}


def mutation_by_variant(record: dict[str, Any], variant: str) -> dict[str, Any]:
    matches = [item for item in record["mutations"] if item.get("variant") == variant]
    if len(matches) != 1:
        raise RuntimeError(
            f"{record.get('task_id')}: expected one {variant} mutation, found {len(matches)}"
        )
    return matches[0]


def effective_survivors(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in record["mutations"]
        if item.get("interface_preserved") is True
        and item.get("outcome") == "survived"
        and item.get("differential_outcome") != "rejected_by_reference_observation"
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial-root", type=Path, required=True)
    parser.add_argument("--hardening-root", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    initial_records: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted(args.initial_root.glob("tasks/*/mutation_evidence.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        initial_records[str(record["task_id"])] = (path, record)

    hardening_records: dict[str, tuple[Path, dict[str, Any]]] = {}
    for root in args.hardening_root:
        for path in sorted(root.glob("tasks/*/mutation_evidence.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            hardening_records[str(record["task_id"])] = (path, record)

    observed: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []
    for task_id, (path, record) in sorted(initial_records.items()):
        for mutation in effective_survivors(record):
            variant = str(mutation["variant"])
            key = (task_id, variant)
            observed.add(key)
            if key not in ADJUDICATIONS:
                raise RuntimeError(f"unadjudicated effective survivor: {key}")
            classification, rationale = ADJUDICATIONS[key]
            row: dict[str, Any] = {
                "task_id": task_id,
                "category": record["category"],
                "variant": variant,
                "derivation": mutation.get("derivation"),
                "classification": classification,
                "rationale": rationale,
                "initial_evidence": str(path),
            }
            if classification == "genuine_gap_hardened":
                if task_id not in hardening_records:
                    raise RuntimeError(f"missing hardening evidence for {task_id}")
                hardening_path, hardening_record = hardening_records[task_id]
                rerun = mutation_by_variant(hardening_record, variant)
                if rerun.get("outcome") != "rejected_by_hidden_csim":
                    raise RuntimeError(f"{key}: hardened mutant was not rejected")
                row["hardening_verified"] = True
                row["hardening_evidence"] = str(hardening_path)
            rows.append(row)

    missing = set(ADJUDICATIONS) - observed
    if missing:
        raise RuntimeError(f"adjudications not present in evidence: {sorted(missing)}")

    total = sum(
        record["interface_preserving_mutant_count"]
        for _, record in initial_records.values()
    )
    initial_direct = sum(
        record["rejected_by_hidden_csim_count"]
        for _, record in initial_records.values()
    )
    initial_differential = sum(
        record["differentially_rejected_survivor_count"]
        for _, record in initial_records.values()
    )
    equivalent = sum(row["classification"].startswith("equivalent_") for row in rows)
    undefined = sum(row["classification"] == "undefined_behaviour_mutant" for row in rows)
    hardened = sum(row["classification"] == "genuine_gap_hardened" for row in rows)
    initial_effective_kills = initial_direct + initial_differential
    post_hardening_kills = initial_effective_kills + hardened
    conservative_denominator = total - equivalent
    defined_denominator = conservative_denominator - undefined
    payload = {
        "schema_version": 1,
        "purpose": "track_a_stratified_mutation_survivor_adjudication",
        "initial_evidence_root": str(args.initial_root),
        "hardening_evidence_roots": [str(path) for path in args.hardening_root],
        "sampled_task_count": len(initial_records),
        "interface_preserving_mutant_count": total,
        "initial_effective_kill_count": initial_effective_kills,
        "initial_raw_effective_detection_rate": initial_effective_kills / total,
        "initial_effective_survivor_count": len(rows),
        "adjudication_counts": {
            "equivalent": equivalent,
            "undefined_behaviour": undefined,
            "genuine_gap_hardened_and_verified": hardened,
        },
        "post_hardening_conservative": {
            "definition": "Excludes equivalent mutants but retains the undefined-behaviour survivor in the denominator.",
            "kill_count": post_hardening_kills,
            "denominator": conservative_denominator,
            "detection_rate": post_hardening_kills / conservative_denominator,
        },
        "post_hardening_defined_non_equivalent": {
            "definition": "Excludes both equivalent mutants and the out-of-contract undefined-behaviour mutant.",
            "kill_count": post_hardening_kills,
            "denominator": defined_denominator,
            "detection_rate": post_hardening_kills / defined_denominator,
        },
        "reporting_caveat": "This is a deterministic diagnostic score on 30 stratified tasks and four operators, not a corpus-wide mutation score.",
        "survivor_adjudications": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
