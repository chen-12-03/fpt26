#!/usr/bin/env python3
"""Promote only fully validated testbench-hardening staging artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _passed(record: dict) -> bool:
    return all(
        record.get(key) is True
        for key in (
            "reference_hidden_pass",
            "reference_public_pass",
            "early_return_rejected",
            "public_early_return_rejected",
            "public_hidden_byte_distinct",
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence_files = sorted(args.evidence_root.glob("*/hardening_evidence.json"))
    promoted = []
    skipped = []
    for evidence_file in evidence_files:
        record = json.loads(evidence_file.read_text(encoding="utf-8"))
        task_id = str(record["task_id"])
        if not _passed(record):
            skipped.append(task_id)
            continue
        source = args.staging_root / task_id
        destination = args.task_root / task_id
        source_spec = tomllib.loads((source / "task.toml").read_text(encoding="utf-8"))
        destination_spec = tomllib.loads(
            (destination / "task.toml").read_text(encoding="utf-8")
        )
        for key in ("task_id", "kernel_file", "public_tb", "hidden_tb", "top"):
            if source_spec.get(key) != destination_spec.get(key):
                raise RuntimeError(f"{task_id}: staging contract mismatch for {key}")

        public_tb = str(source_spec["public_tb"])
        hidden_tb = str(source_spec["hidden_tb"])
        shutil.copy2(source / public_tb, destination / public_tb)
        shutil.copy2(source / "hidden" / hidden_tb, destination / "hidden" / hidden_tb)
        public_goldens = sorted(source.glob("track_a_public_*.golden"))
        hidden_goldens = sorted((source / "hidden").glob("track_a_hidden_*.golden"))
        public_preserved = bool(record.get("public_testbench_preserved"))
        self_contained = bool(record.get("self_contained_testbench"))
        hidden_fixture_names = list(record.get("hidden_fixture_names") or [])
        if (not public_preserved and not public_goldens and not self_contained) or (
            not hidden_goldens and not hidden_fixture_names and not self_contained
        ):
            raise RuntimeError(f"{task_id}: missing staged golden fixtures")
        for path in public_goldens:
            shutil.copy2(path, destination / path.name)
        for path in hidden_goldens:
            shutil.copy2(path, destination / "hidden" / path.name)
        for name in hidden_fixture_names:
            fixture = source / "hidden" / name
            if not fixture.is_file():
                raise RuntimeError(f"{task_id}: missing staged hidden fixture {name}")
            shutil.copy2(fixture, destination / "hidden" / name)

        provenance = {
            "schema_version": 1,
            "task_id": task_id,
            "public_input_derivation": record["public_input_derivation"],
            "hidden_input_derivation": record["input_derivation"],
            "oracle_strategy": record["oracle_strategy"],
            "public_testbench_preserved": public_preserved,
            "self_contained_testbench": self_contained,
            "validation_evidence": str(evidence_file),
            "public_tb_sha256": _sha256(destination / public_tb),
            "hidden_tb_sha256": _sha256(destination / "hidden" / hidden_tb),
            "public_golden_sha256": {
                path.name: _sha256(destination / path.name) for path in public_goldens
            },
            "hidden_golden_sha256": {
                path.name: _sha256(destination / "hidden" / path.name)
                for path in hidden_goldens
            },
            "hidden_fixture_sha256": {
                name: _sha256(destination / "hidden" / name)
                for name in hidden_fixture_names
            },
            "limitations": [
                "Golden outputs were generated from the pinned reference implementation.",
                "Independent implementation agreement remains a stronger optional oracle gate.",
            ],
        }
        provenance_path = destination / "hidden" / "testbench_provenance.json"
        provenance_path.write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        promoted.append(
            {
                "task_id": task_id,
                "public_tb_sha256": provenance["public_tb_sha256"],
                "hidden_tb_sha256": provenance["hidden_tb_sha256"],
                "provenance": str(provenance_path),
            }
        )

    summary = {
        "schema_version": 1,
        "purpose": "track_a_validated_testbench_hardening_promotion",
        "promoted_count": len(promoted),
        "skipped_count": len(skipped),
        "promoted": promoted,
        "skipped_task_ids": skipped,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
