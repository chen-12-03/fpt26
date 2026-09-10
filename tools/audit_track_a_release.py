#!/usr/bin/env python3
"""Audit a frozen Track-A public/evaluator release and agent input loading."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

from agent.task_io import load_public_task
from llm4hls.task import load_task


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    public_root = args.release_root / "public_agent"
    evaluator_root = args.release_root / "evaluator_private"
    mapping = json.loads(
        (evaluator_root / "EVALUATOR_MAPPING.json").read_text(encoding="utf-8")
    )["tasks"]
    mapping_by_public = {item["public_task_id"]: item for item in mapping}
    public_specs = sorted(public_root.glob("*/task.toml"))
    evaluator_specs = sorted(evaluator_root.glob("*/task.toml"))
    violations: list[str] = []
    records = []
    for spec_path in public_specs:
        public_id = spec_path.parent.name
        evaluator_dir = evaluator_root / public_id
        if public_id not in mapping_by_public:
            violations.append(f"mapping_missing:{public_id}")
            continue
        public_task, preflight = load_public_task(spec_path.parent)
        evaluator_task = load_task(evaluator_dir)
        spec = tomllib.loads(spec_path.read_text(encoding="utf-8"))
        if public_task.reference_code is not None:
            violations.append(f"public_reference_loaded:{public_id}")
        if public_task.hidden_tb_code or public_task.hidden_tb_name:
            violations.append(f"public_hidden_loaded:{public_id}")
        if evaluator_task.reference_code is None:
            violations.append(f"evaluator_reference_missing:{public_id}")
        if not evaluator_task.hidden_tb_code:
            violations.append(f"evaluator_hidden_missing:{public_id}")
        if preflight.forbidden_artifact_accesses != 0:
            violations.append(f"forbidden_access:{public_id}")
        compared = [spec["kernel_file"], spec["public_tb"], *spec.get("header_files", [])]
        mismatched = [
            name
            for name in compared
            if sha256(spec_path.parent / name) != sha256(evaluator_dir / name)
        ]
        if mismatched:
            violations.append(f"public_evaluator_mismatch:{public_id}:{','.join(mismatched)}")
        records.append(
            {
                "task_id": public_id,
                "public_files_read": list(preflight.public_files_read),
                "forbidden_artifact_accesses": preflight.forbidden_artifact_accesses,
                "reference_absent_from_public_task": public_task.reference_code is None,
                "hidden_absent_from_public_task": not (
                    public_task.hidden_tb_code or public_task.hidden_tb_name
                ),
                "evaluator_reference_present": evaluator_task.reference_code is not None,
                "evaluator_hidden_present": bool(evaluator_task.hidden_tb_code),
                "public_evaluator_input_hashes_match": not mismatched,
            }
        )
    for path in public_root.rglob("*"):
        relative = path.relative_to(public_root)
        if any(part.lower() in {"hidden", "reference"} for part in relative.parts):
            violations.append(f"forbidden_public_path:{relative.as_posix()}")
        if path.name.endswith(":Zone.Identifier"):
            violations.append(f"zone_identifier:{relative.as_posix()}")
    if len(public_specs) != 150:
        violations.append(f"public_task_count:{len(public_specs)}")
    if len(evaluator_specs) != 150:
        violations.append(f"evaluator_task_count:{len(evaluator_specs)}")
    if len(mapping) != 150 or len(mapping_by_public) != 150:
        violations.append("mapping_not_bijective")

    payload = {
        "schema_version": 1,
        "purpose": "track_a_release_and_agent_input_audit",
        "release_root": str(args.release_root),
        "public_task_count": len(public_specs),
        "evaluator_task_count": len(evaluator_specs),
        "mapping_count": len(mapping),
        "agent_preflight_pass_count": sum(
            item["forbidden_artifact_accesses"] == 0
            and item["reference_absent_from_public_task"]
            and item["hidden_absent_from_public_task"]
            and item["public_evaluator_input_hashes_match"]
            for item in records
        ),
        "evaluator_complete_count": sum(
            item["evaluator_reference_present"] and item["evaluator_hidden_present"]
            for item in records
        ),
        "observed_vitis_versions": sorted(
            {
                load_public_task(path.parent)[1].observed_vitis_version
                for path in public_specs[:1]
            }
        ),
        "passed": not violations and len(records) == 150,
        "violations": sorted(set(violations)),
        "tasks": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {key: value for key, value in payload.items() if key != "tasks"},
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
