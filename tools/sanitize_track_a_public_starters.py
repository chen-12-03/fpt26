#!/usr/bin/env python3
"""Remove benchmark-specific markers from public Track-A starter kernels."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

from build_track_a_150 import _code_generation_stub


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, required=True)
    args = parser.parse_args()
    records = []
    for toml_path in sorted(args.task_root.glob("*/task.toml")):
        task_dir = toml_path.parent
        spec = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        category = str(spec["track_a_category"])
        kernel = task_dir / str(spec["kernel_file"])
        before = sha256(kernel)
        text = kernel.read_text(encoding="utf-8")
        action = None
        if category == "code_generation":
            reference = (task_dir / "reference" / str(spec["kernel_file"])).read_text(
                encoding="utf-8"
            )
            text = _code_generation_stub(reference, str(spec["top"]))
            action = "unresolved_implementation_placeholder"
            toml_text = toml_path.read_text(encoding="utf-8")
            toml_text, count = re.subn(
                r'^fault_derivation = ".*"$',
                'fault_derivation = "unresolved_implementation_placeholder"',
                toml_text,
                count=1,
                flags=re.M,
            )
            if count != 1:
                raise RuntimeError(f"{toml_path}: fault_derivation not found")
            toml_path.write_text(toml_text, encoding="utf-8")
        elif category == "synthesis_repair":
            old = "TRACK_A_UNSUPPORTED_SYNTHESIS_TYPE track_a_synth_probe;"
            new = "undefined_synthesis_type synthesis_probe;"
            if old in text:
                if text.count(old) != 1:
                    raise RuntimeError(f"{kernel}: expected one synthesis marker")
                text = text.replace(old, new)
                action = "removed_benchmark_specific_synthesis_identifiers"
                toml_text = toml_path.read_text(encoding="utf-8")
                toml_text = toml_text.replace(
                    'fault_derivation = "synthesis_only_unknown_type"',
                    'fault_derivation = "synthesis_only_undefined_local_type"',
                )
                toml_path.write_text(toml_text, encoding="utf-8")
            elif new not in text:
                raise RuntimeError(f"{kernel}: synthesis fault marker missing")
        else:
            text, count = re.subn(
                r"^[ \t]*// TRACK_A_INTENTIONAL_EARLY_RETURN_VARIANT_\d+[ \t]*\n",
                "",
                text,
                flags=re.M,
            )
            if count:
                action = "removed_public_fault_hint_comment"
        if action is None:
            continue
        kernel.write_text(text, encoding="utf-8")
        records.append(
            {
                "task_id": spec["task_id"],
                "action": action,
                "old_starter_sha256": before,
                "new_starter_sha256": sha256(kernel),
            }
        )

    manifest_path = args.task_root / "candidate_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_id = {item["task_id"]: item for item in records}
    for item in manifest["tasks"]:
        record = by_id.get(item["task_id"])
        if record:
            item["starter_sha256"] = record["new_starter_sha256"]
            if item["category"] == "code_generation":
                item["fault_derivation"] = "unresolved_implementation_placeholder"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    report = {
        "schema_version": 1,
        "purpose": "track_a_public_starter_sanitization",
        "changed_count": len(records),
        "records": records,
    }
    output = args.task_root / "public_starter_sanitization.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
