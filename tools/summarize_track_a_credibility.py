#!/usr/bin/env python3
"""Create one auditable credibility checkpoint for the Track-A corpus."""

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


def normalized_text_sha256(path: Path) -> str:
    """Match Task's universal-newline text loading used by pair validation."""
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--static-audit", type=Path, required=True)
    parser.add_argument("--pair-root", type=Path, required=True)
    parser.add_argument(
        "--mutation-root",
        type=Path,
        help="Optional root containing tasks/*/mutation_evidence.json.",
    )
    parser.add_argument(
        "--mutation-adjudication",
        type=Path,
        help="Optional verified survivor-adjudication JSON.",
    )
    parser.add_argument(
        "--hardware-matrix",
        type=Path,
        help="Optional hash-current full acceptance matrix.",
    )
    parser.add_argument(
        "--source-provenance",
        type=Path,
        help="Optional exact source-acquisition provenance audit.",
    )
    parser.add_argument(
        "--semantic-fault-summary",
        type=Path,
        help="Optional current semantic fault-selection summary.",
    )
    parser.add_argument(
        "--release-audit",
        type=Path,
        help="Optional frozen public/evaluator release isolation audit.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    static = json.loads(args.static_audit.read_text(encoding="utf-8"))
    manifest = json.loads((args.task_root / "candidate_manifest.json").read_text(encoding="utf-8"))
    task_dirs = sorted(path.parent for path in args.task_root.glob("*/task.toml"))
    categories: Counter[str] = Counter()
    difficulties: Counter[str] = Counter()
    family_ids: set[str] = set()
    missing_source_fields: list[str] = []
    placeholder_source_tasks: list[str] = []
    missing_tb_provenance: list[str] = []
    invalid_tb_provenance: list[dict[str, str]] = []
    oracle_strategies: Counter[str] = Counter()
    current_tb_hashes: dict[str, dict[str, str]] = {}

    for task_dir in task_dirs:
        spec = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
        task_id = str(spec["task_id"])
        current_tb_hashes[task_id] = {
            "public_tb_sha256": normalized_text_sha256(
                task_dir / str(spec["public_tb"])
            ),
            "hidden_tb_sha256": normalized_text_sha256(
                task_dir / "hidden" / str(spec["hidden_tb"])
            ),
        }
        categories[str(spec.get("track_a_category"))] += 1
        difficulties[str(spec.get("difficulty"))] += 1
        family_ids.add(str(spec.get("kernel_family_id")))
        required = ("source_url", "source_path", "repo_commit", "license", "source_sha256")
        if not all(spec.get(key) for key in required):
            missing_source_fields.append(task_id)
        if spec.get("repo_commit") == "LOCAL_SNAPSHOT_REQUIRES_UPSTREAM_MATCH" or spec.get("license") == "UPSTREAM_REVIEW_REQUIRED":
            placeholder_source_tasks.append(task_id)

        provenance_path = task_dir / "hidden" / "testbench_provenance.json"
        if not provenance_path.is_file():
            missing_tb_provenance.append(task_id)
            continue
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        oracle_strategies[str(provenance.get("oracle_strategy", "missing"))] += 1
        for key, path in (
            ("public_tb_sha256", task_dir / str(spec["public_tb"])),
            ("hidden_tb_sha256", task_dir / "hidden" / str(spec["hidden_tb"])),
        ):
            actual = sha256(path)
            expected = provenance.get(key)
            if actual != expected:
                invalid_tb_provenance.append(
                    {"task_id": task_id, "field": key, "expected": str(expected), "actual": actual}
                )
        for field, root in (
            ("public_golden_sha256", task_dir),
            ("hidden_golden_sha256", task_dir / "hidden"),
            ("hidden_fixture_sha256", task_dir / "hidden"),
        ):
            declared = provenance.get(field) or {}
            if not isinstance(declared, dict):
                invalid_tb_provenance.append(
                    {
                        "task_id": task_id,
                        "field": field,
                        "expected": "mapping",
                        "actual": type(declared).__name__,
                    }
                )
                continue
            for name, expected in declared.items():
                path = root / str(name)
                if not path.is_file():
                    invalid_tb_provenance.append(
                        {
                            "task_id": task_id,
                            "field": f"{field}.{name}",
                            "expected": str(expected),
                            "actual": "missing",
                        }
                    )
                    continue
                actual = sha256(path)
                if actual != expected:
                    invalid_tb_provenance.append(
                        {
                            "task_id": task_id,
                            "field": f"{field}.{name}",
                            "expected": str(expected),
                            "actual": actual,
                        }
                    )
        evidence = provenance.get("validation_evidence")
        evidence_paths = evidence if isinstance(evidence, list) else [evidence]
        for index, value in enumerate(evidence_paths):
            if not isinstance(value, str) or not Path(value).is_file():
                invalid_tb_provenance.append(
                    {
                        "task_id": task_id,
                        "field": f"validation_evidence[{index}]",
                        "expected": "existing file",
                        "actual": str(value),
                    }
                )

    pair_records = sorted((args.pair_root / "tasks").glob("*/pair_validation.json"))
    pair_passed = 0
    pair_failed: list[str] = []
    pair_gate_failures: Counter[str] = Counter()
    stale_pair_evidence: list[dict[str, str]] = []
    for path in pair_records:
        record = json.loads(path.read_text(encoding="utf-8"))
        task_id = str(record.get("task_id", path.parent.name))
        if record.get("passed") is True:
            pair_passed += 1
        else:
            pair_failed.append(task_id)
        for field, current in current_tb_hashes.get(task_id, {}).items():
            recorded = str(record.get(field))
            if recorded != current:
                stale_pair_evidence.append(
                    {
                        "task_id": task_id,
                        "field": field,
                        "recorded": recorded,
                        "current": current,
                    }
                )
        for gate, passed in (record.get("gates") or {}).items():
            if passed is not True:
                pair_gate_failures[gate] += 1

    testbench_gate = bool(
        static.get("static_prerequisite_pass")
        and len(pair_records) == len(task_dirs)
        and pair_passed == len(task_dirs)
        and not stale_pair_evidence
        and not missing_tb_provenance
        and not invalid_tb_provenance
    )
    source_audit = None
    exact_source_gate = False
    if args.source_provenance is not None:
        source_audit = json.loads(args.source_provenance.read_text(encoding="utf-8"))
        exact_source_gate = bool(
            source_audit.get("passed") is True
            and source_audit.get("task_count") == len(task_dirs)
            and source_audit.get("passed_count") == len(task_dirs)
        )
    source_gate = bool(
        not missing_source_fields
        and not placeholder_source_tasks
        and exact_source_gate
    )
    semantic_fault_audit = None
    semantic_fault_gate = False
    if args.semantic_fault_summary is not None:
        semantic_fault_audit = json.loads(
            args.semantic_fault_summary.read_text(encoding="utf-8")
        )
        semantic_fault_gate = bool(
            semantic_fault_audit.get("task_count") == 50
            and semantic_fault_audit.get("all_public_and_hidden_detect_mutant")
            is True
        )
    release_audit = None
    release_gate = False
    if args.release_audit is not None:
        release_audit = json.loads(args.release_audit.read_text(encoding="utf-8"))
        release_gate = bool(
            release_audit.get("passed") is True
            and release_audit.get("public_task_count") == len(task_dirs)
            and release_audit.get("evaluator_task_count") == len(task_dirs)
            and release_audit.get("agent_preflight_pass_count") == len(task_dirs)
            and not release_audit.get("violations")
        )
    hardware_summary = None
    hardware_gate = False
    isolation_gate = False
    if args.hardware_matrix is not None:
        hardware = json.loads(args.hardware_matrix.read_text(encoding="utf-8"))
        isolation = hardware.get("submission_isolation") or {}
        hardware_gate = bool(
            hardware.get("current_technically_accepted_count") == len(task_dirs)
            and hardware.get("stale_evidence_count") == 0
            and (hardware.get("corpus") or {}).get("category_counts_ok") is True
            and (hardware.get("corpus") or {}).get(
                "cross_category_kernel_overlap_count"
            )
            == 0
        )
        isolation_gate = bool(
            isolation.get("task_count") == len(task_dirs)
            and isolation.get("forbidden_artifact_access_count") == 0
            and isolation.get("all_u55c") is True
        )
        hardware_summary = {
            "passed": hardware_gate,
            "evidence": str(args.hardware_matrix),
            "current_technically_accepted_count": hardware.get(
                "current_technically_accepted_count"
            ),
            "current_technically_accepted_by_category": hardware.get(
                "current_technically_accepted_by_category"
            ),
            "current_evidence_count": hardware.get("current_evidence_count"),
            "stale_evidence_count": hardware.get("stale_evidence_count"),
            "submission_isolation": isolation,
            "submission_isolation_passed": isolation_gate,
            "fully_accepted_count_including_provenance": hardware.get(
                "accepted_count"
            ),
        }
    mutation_adjudication = None
    mutation_adjudication_complete = False
    if args.mutation_adjudication is not None:
        mutation_adjudication = json.loads(
            args.mutation_adjudication.read_text(encoding="utf-8")
        )
        adjudication_counts = mutation_adjudication.get("adjudication_counts") or {}
        mutation_adjudication_complete = bool(
            mutation_adjudication.get("initial_effective_survivor_count")
            == sum(int(value) for value in adjudication_counts.values())
            and int(adjudication_counts.get("genuine_gap_hardened_and_verified", 0)) > 0
        )
    mutation_summary = None
    mutation_gate = False
    if args.mutation_root is not None:
        mutation_records = sorted(
            args.mutation_root.glob("tasks/*/mutation_evidence.json")
        )
        mutation_categories: Counter[str] = Counter()
        reference_passed = 0
        baseline_expected = 0
        interface_preserving = 0
        directly_rejected = 0
        differentially_rejected = 0
        effective_survivors = 0
        survivor_tasks: list[str] = []
        for path in mutation_records:
            record = json.loads(path.read_text(encoding="utf-8"))
            mutation_categories[str(record.get("category"))] += 1
            reference_passed += int(record.get("reference_hidden_pass") is True)
            baseline_expected += int(
                record.get("baseline_hidden_matches_expected_csim_state") is True
            )
            interface_preserving += int(
                record.get("interface_preserving_mutant_count", 0)
            )
            directly_rejected += int(record.get("rejected_by_hidden_csim_count", 0))
            differentially_rejected += int(
                record.get("differentially_rejected_survivor_count", 0)
            )
            task_survivors = int(
                record.get("effective_survivor_count_with_differential_oracle", 0)
            )
            effective_survivors += task_survivors
            if task_survivors:
                survivor_tasks.append(str(record.get("task_id", path.parent.name)))
        effective_rejected = directly_rejected + differentially_rejected
        mutation_gate = bool(
            mutation_records
            and reference_passed == len(mutation_records)
            and baseline_expected == len(mutation_records)
            and interface_preserving > 0
        )
        mutation_summary = {
            "evidence_root": str(args.mutation_root),
            "evidence_valid": mutation_gate,
            "task_count": len(mutation_records),
            "category_counts": dict(sorted(mutation_categories.items())),
            "reference_hidden_pass_count": reference_passed,
            "baseline_hidden_expected_count": baseline_expected,
            "interface_preserving_mutant_count": interface_preserving,
            "directly_rejected_mutant_count": directly_rejected,
            "differentially_rejected_survivor_count": differentially_rejected,
            "effective_rejected_mutant_count": effective_rejected,
            "effective_survivor_count": effective_survivors,
            "effective_detection_rate": (
                effective_rejected / interface_preserving
                if interface_preserving
                else None
            ),
            "effective_survivor_task_ids": survivor_tasks,
            "interpretation": (
                "Diagnostic stratified mutation probe; equivalent mutants must be "
                "separated from genuine oracle gaps before reporting a mutation score."
            ),
        }
    payload = {
        "schema_version": 1,
        "purpose": "track_a_150_v2_credibility_checkpoint",
        "task_count": len(task_dirs),
        "category_counts": dict(sorted(categories.items())),
        "difficulty_counts": dict(sorted(difficulties.items())),
        "unique_kernel_family_count": len(family_ids),
        "testbench_credibility": {
            "passed": testbench_gate,
            "static_audit": str(args.static_audit),
            "static_prerequisite_pass": bool(static.get("static_prerequisite_pass")),
            "independence_class_counts": static.get("independence_class_counts"),
            "public_clone_count": static.get("public_clone_count"),
            "weak_public_count": static.get("weak_public_count"),
            "weak_hidden_count": static.get("weak_hidden_count"),
            "pair_evidence_root": str(args.pair_root),
            "pair_record_count": len(pair_records),
            "pair_passed_count": pair_passed,
            "pair_failed_task_ids": pair_failed,
            "pair_gate_failure_counts": dict(sorted(pair_gate_failures.items())),
            "stale_pair_evidence": stale_pair_evidence,
            "testbench_provenance_count": len(task_dirs) - len(missing_tb_provenance),
            "missing_testbench_provenance_task_ids": missing_tb_provenance,
            "invalid_testbench_provenance": invalid_tb_provenance,
            "oracle_strategy_counts": dict(sorted(oracle_strategies.items())),
            "stratified_mutation_probe": mutation_summary,
            "mutation_survivor_adjudication": (
                {
                    "evidence": str(args.mutation_adjudication),
                    "complete": mutation_adjudication_complete,
                    "adjudication_counts": mutation_adjudication.get(
                        "adjudication_counts"
                    ),
                    "post_hardening_conservative": mutation_adjudication.get(
                        "post_hardening_conservative"
                    ),
                    "post_hardening_defined_non_equivalent": mutation_adjudication.get(
                        "post_hardening_defined_non_equivalent"
                    ),
                    "reporting_caveat": mutation_adjudication.get(
                        "reporting_caveat"
                    ),
                }
                if mutation_adjudication is not None
                else None
            ),
        },
        "source_provenance": {
            "passed": source_gate,
            "exact_acquisition_audit": str(args.source_provenance)
            if args.source_provenance is not None
            else None,
            "exact_acquisition_audit_passed": exact_source_gate,
            "manifest_status_counts": manifest.get("provenance_status_counts"),
            "missing_source_field_task_ids": missing_source_fields,
            "placeholder_source_task_count": len(placeholder_source_tasks),
            "placeholder_source_task_ids": placeholder_source_tasks,
        },
        "semantic_fault_credibility": {
            "passed": semantic_fault_gate,
            "evidence": str(args.semantic_fault_summary)
            if args.semantic_fault_summary is not None
            else None,
            "task_count": semantic_fault_audit.get("task_count")
            if semantic_fault_audit is not None
            else 0,
            "selected_variant_counts": semantic_fault_audit.get(
                "selected_variant_counts"
            )
            if semantic_fault_audit is not None
            else {},
            "criterion": "interface preserved; public and hidden both reject at runtime",
        },
        "release_isolation": {
            "passed": release_gate,
            "evidence": str(args.release_audit)
            if args.release_audit is not None
            else None,
            "public_task_count": release_audit.get("public_task_count")
            if release_audit is not None
            else 0,
            "agent_preflight_pass_count": release_audit.get(
                "agent_preflight_pass_count"
            )
            if release_audit is not None
            else 0,
            "violations": release_audit.get("violations")
            if release_audit is not None
            else [],
        },
        "hardware_acceptance": hardware_summary,
        "remaining_required_gates": [
            *(
                []
                if source_gate
                else ["resolve every source acquisition and third-party license"]
            ),
            *(
                []
                if semantic_fault_gate
                else ["validate semantic fault selection against public and hidden tests"]
            ),
            *(
                []
                if hardware_gate
                else [
                    "rerun full baseline/reference synthesis and required structural CoSim acceptance after corpus freeze"
                ]
            ),
            *(
                []
                if isolation_gate and release_gate
                else [
                    "verify evaluator-only hidden asset isolation in the released packaging path"
                ]
            ),
        ],
        "recommended_followups": [
            "Run a new release-current stratified multi-operator mutation probe; report it as diagnostic coverage, not a corpus-wide score.",
            "Mine human compile/synthesis bug-fix commits to complement the controlled injected-fault categories.",
            "Complete a formal third-party license compatibility review before external redistribution.",
        ],
        "technical_corpus_ready": (
            testbench_gate
            and semantic_fault_gate
            and hardware_gate
            and isolation_gate
            and release_gate
        ),
        "overall_corpus_ready": (
            testbench_gate
            and source_gate
            and semantic_fault_gate
            and hardware_gate
            and isolation_gate
            and release_gate
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if testbench_gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
