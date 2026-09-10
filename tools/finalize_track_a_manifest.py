#!/usr/bin/env python3
"""Bind the final Track-A corpus manifest to all current release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence(path: Path) -> dict:
    return {"path": str(path), "sha256": sha256(path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--static-audit", type=Path, required=True)
    parser.add_argument("--pair-summary", type=Path, required=True)
    parser.add_argument("--source-provenance", type=Path, required=True)
    parser.add_argument("--semantic-fault-summary", type=Path, required=True)
    parser.add_argument("--hardware-matrix", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--release-audit", type=Path, required=True)
    args = parser.parse_args()

    static = json.loads(args.static_audit.read_text(encoding="utf-8"))
    pairs = json.loads(args.pair_summary.read_text(encoding="utf-8"))
    provenance = json.loads(args.source_provenance.read_text(encoding="utf-8"))
    faults = json.loads(args.semantic_fault_summary.read_text(encoding="utf-8"))
    hardware = json.loads(args.hardware_matrix.read_text(encoding="utf-8"))
    release = json.loads(args.release_manifest.read_text(encoding="utf-8"))
    release_audit = json.loads(args.release_audit.read_text(encoding="utf-8"))
    required = {
        "static": static.get("static_prerequisite_pass") is True,
        "pairs": pairs.get("task_count") == 150 and pairs.get("passed_count") == 150,
        "provenance": provenance.get("task_count") == 150
        and provenance.get("passed_count") == 150,
        "semantic_faults": faults.get("task_count") == 50
        and faults.get("all_public_and_hidden_detect_mutant") is True,
        "hardware": hardware.get("fully_accepted") is True
        and hardware.get("stale_evidence_count") == 0,
        "release_freeze": release.get("public_private_separation_pass") is True,
        "release_agent_inputs": release_audit.get("passed") is True
        and release_audit.get("agent_preflight_pass_count") == 150,
    }
    if not all(required.values()):
        raise RuntimeError(f"cannot finalize; failed gates: {required}")

    manifest_path = args.task_root / "candidate_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    difficulty = Counter()
    fault_operators: dict[str, Counter[str]] = {}
    task_by_id = {item["task_id"]: item for item in manifest["tasks"]}
    for toml_path in sorted(args.task_root.glob("*/task.toml")):
        spec = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        category = str(spec["track_a_category"])
        operator = str(spec["fault_derivation"]).split(":", 1)[0]
        difficulty[str(spec["difficulty"])] += 1
        fault_operators.setdefault(category, Counter())[operator] += 1
        item = task_by_id[str(spec["task_id"])]
        item["expected_baseline_state"] = spec["expected_baseline_state"]
        item["fault_derivation"] = spec["fault_derivation"]
        item["starter_sha256"] = sha256(toml_path.parent / str(spec["kernel_file"]))
        item["hidden_testbench_status"] = "static_and_dynamic_pair_validated"

    manifest["status"] = "release_frozen_all_required_gates_pass"
    manifest["remaining_gates"] = []
    manifest["static_validation"] = {
        "ok": True,
        "task_count": 150,
        "category_counts": hardware["corpus"]["category_counts"],
        "difficulty_counts": dict(sorted(difficulty.items())),
        "unique_kernel_family_count": hardware["corpus"]["unique_kernel_family_count"],
        "weak_public_testbench_count": static["weak_public_count"],
        "weak_hidden_testbench_count": static["weak_hidden_count"],
        "public_clone_count": static["public_clone_count"],
        "unreachable_public_oracle_count": static["unreachable_public_oracle_count"],
        "unreachable_hidden_oracle_count": static["unreachable_hidden_oracle_count"],
        "independence_class_counts": static["independence_class_counts"],
    }
    manifest["fault_operator_counts"] = {
        category: dict(sorted(counts.items()))
        for category, counts in sorted(fault_operators.items())
    }
    manifest["release_evidence"] = {
        "required_gates": required,
        "static_testbench_audit": evidence(args.static_audit),
        "dynamic_pair_validation": evidence(args.pair_summary),
        "source_provenance": evidence(args.source_provenance),
        "semantic_fault_selection": evidence(args.semantic_fault_summary),
        # Avoid a digest cycle: the hardware matrix hashes this finalized
        # candidate manifest.  The manifest therefore records the matrix path
        # and direction of binding, then aggregation is rerun once afterward.
        "hardware_acceptance": {
            "path": str(args.hardware_matrix),
            "binding": "hardware_matrix_hashes_this_finalized_manifest",
        },
        "release_freeze": evidence(args.release_manifest),
        "agent_input_isolation": evidence(args.release_audit),
        "public_tree_sha256": release["public_tree_sha256"],
        "evaluator_tree_sha256": release["evaluator_tree_sha256"],
    }
    manifest["declared_limitations"] = [
        "Compile- and synthesis-repair starters use controlled injected fault operators rather than mined human bug-fix commits.",
        "The mutation-strength result is a stratified diagnostic and must not be described as a corpus-wide mutation score.",
        "Open-source kernel code may occur in model pretraining; blind public IDs remove direct source locators but cannot eliminate code-level contamination.",
        "The reference anchor establishes correctness and the official-score denominator; it is not asserted to be globally QoR-optimal.",
        "Third-party redistribution requires preserving complete upstream license texts and notices and a separate compatibility review.",
    ]
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "required_gates": required,
                "difficulty_counts": dict(sorted(difficulty.items())),
                "fault_operator_counts": manifest["fault_operator_counts"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
