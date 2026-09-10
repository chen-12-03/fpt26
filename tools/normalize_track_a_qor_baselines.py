#!/usr/bin/env python3
"""Replace synthetic Track-A QoR degradation with the acquired valid baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


OLD_DERIVATION = 'fault_derivation = "opaque_sequential_warmup:lcg_iterations=131072"'
NEW_DERIVATION = (
    'fault_derivation = "upstream_valid_baseline:no_artificial_degradation"'
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str, path: Path) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one {old!r}, found {count}")
    return text.replace(old, new)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, required=True)
    args = parser.parse_args()

    changed: list[dict[str, str]] = []
    for task_dir in sorted(args.task_root.glob("qor_optimization__*/")):
        task_toml = task_dir / "task.toml"
        spec = tomllib.loads(task_toml.read_text(encoding="utf-8"))
        kernel = task_dir / str(spec["kernel_file"])
        reference = task_dir / "reference" / str(spec["kernel_file"])
        old_hash = sha256(kernel)
        kernel.write_bytes(reference.read_bytes())

        text = task_toml.read_text(encoding="utf-8")
        text = replace_once(
            text,
            'initial_condition = "Track-A v2 qor_optimization; baseline=valid_unoptimized"',
            'initial_condition = "Track-A v2 qor_optimization; baseline=valid_baseline"',
            task_toml,
        )
        text = replace_once(
            text,
            'expected_baseline_state = "valid_unoptimized"',
            'expected_baseline_state = "valid_baseline"',
            task_toml,
        )
        text = replace_once(text, OLD_DERIVATION, NEW_DERIVATION, task_toml)
        task_toml.write_text(text, encoding="utf-8")

        description = task_dir / "description.md"
        desc = description.read_text(encoding="utf-8")
        desc = replace_once(
            desc,
            "Expected initial state: `valid_unoptimized`.",
            "Expected initial state: `valid_baseline`.",
            description,
        )
        description.write_text(desc, encoding="utf-8")
        changed.append(
            {
                "task_id": str(spec["task_id"]),
                "old_starter_sha256": old_hash,
                "new_starter_sha256": sha256(kernel),
                "reference_sha256": sha256(reference),
            }
        )

    if len(changed) != 25:
        raise RuntimeError(f"expected 25 QoR tasks, changed {len(changed)}")
    if any(item["new_starter_sha256"] != item["reference_sha256"] for item in changed):
        raise RuntimeError("at least one normalized starter differs from its anchor")

    manifest_path = args.task_root / "candidate_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed_by_id = {item["task_id"]: item for item in changed}
    manifest_count = 0
    for item in manifest["tasks"]:
        if item["task_id"] not in changed_by_id:
            continue
        item["expected_baseline_state"] = "valid_baseline"
        item["fault_derivation"] = "upstream_valid_baseline:no_artificial_degradation"
        item["starter_sha256"] = changed_by_id[item["task_id"]]["new_starter_sha256"]
        manifest_count += 1
    if manifest_count != 25:
        raise RuntimeError(f"manifest contains {manifest_count} QoR tasks, expected 25")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    output = {
        "schema_version": 1,
        "purpose": "track_a_qor_baseline_normalization",
        "task_count": len(changed),
        "policy": "acquired_valid_source_without_synthetic_degradation",
        "tasks": changed,
    }
    report = args.task_root / "qor_baseline_normalization.json"
    report.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
