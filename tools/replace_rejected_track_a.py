#!/usr/bin/env python3
"""Replace rejected Track-A candidates with same-category validated families."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from build_track_a_150 import (
    _copy_hidden_assets,
    _copy_public_assets,
    _description,
    _ensure_contract_header,
    _load_sources,
    _task_toml,
    refresh_candidate_manifest,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace(
    *,
    task_root: Path,
    source_root: Path,
    evidence_root: Path,
    quarantine_root: Path,
) -> dict[str, Any]:
    sources = {item["task_dir"].name: item for item in _load_sources(source_root)}
    accepted_by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rejected: list[dict[str, Any]] = []
    for evidence in sorted((evidence_root / "tasks").glob("*/evidence.json")):
        record = json.loads(evidence.read_text(encoding="utf-8"))
        if record.get("accepted") is True:
            donor_task_dir = Path(record["task_dir"])
            spec = tomllib.loads(
                (donor_task_dir / "task.toml").read_text(encoding="utf-8")
            )
            accepted_by_category[str(record["category"])].append(
                {"spec": spec, "task_dir": donor_task_dir}
            )
        else:
            rejected.append({"record": record, "evidence": evidence})
    if not rejected:
        return {"replaced_count": 0, "replacements": []}

    quarantine_root.mkdir(parents=True, exist_ok=True)
    evidence_archive = evidence_root / "rejected_candidate_evidence"
    evidence_archive.mkdir(parents=True, exist_ok=True)
    replacements = []
    donor_offsets: dict[str, int] = defaultdict(int)
    for item in rejected:
        record = item["record"]
        category = str(record["category"])
        donors = accepted_by_category.get(category) or []
        if not donors:
            raise RuntimeError(f"no accepted donor family for category: {category}")
        donor = donors[donor_offsets[category] % len(donors)]
        donor_offsets[category] += 1
        donor_spec = donor["spec"]
        donor_task_dir = donor["task_dir"]
        source = dict(sources[str(donor_spec["source_task_id"])])
        # Clone the already gate-proven public/private artifacts instead of
        # guessing a new QoR mutation.  The family remains inside its original
        # category, and every rejected candidate plus its evidence is archived.
        source["task_dir"] = donor_task_dir
        source["spec"] = donor_spec
        source["reference"] = (
            donor_task_dir / "reference" / str(donor_spec["kernel_file"])
        ).read_text(encoding="utf-8")
        task_dir = Path(record["task_dir"])
        task_id = str(record["task_id"])
        archive = quarantine_root / task_id
        if archive.exists():
            raise RuntimeError(f"quarantine target already exists: {archive}")
        shutil.move(str(task_dir), str(archive))
        archived_evidence = evidence_archive / f"{task_id}.json"
        shutil.copy2(item["evidence"], archived_evidence)

        (task_dir / "hidden").mkdir(parents=True)
        (task_dir / "reference").mkdir()
        _copy_public_assets(source, task_dir)
        hidden_tb = _copy_hidden_assets(source, task_dir / "hidden")
        source = _ensure_contract_header(source, task_dir)
        source_spec = source["spec"]
        mutation = str(donor_spec["fault_derivation"])
        kernel_name = str(source_spec["kernel_file"])
        (task_dir / kernel_name).write_text(
            (donor_task_dir / kernel_name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (task_dir / "reference" / kernel_name).write_text(
            source["reference"], encoding="utf-8"
        )
        expected = str(
            tomllib.loads((archive / "task.toml").read_text(encoding="utf-8"))[
                "expected_baseline_state"
            ]
        )
        task_type = str(
            tomllib.loads((archive / "task.toml").read_text(encoding="utf-8"))[
                "task_type"
            ]
        )
        (task_dir / "description.md").write_text(
            _description(category, source, mutation, expected), encoding="utf-8"
        )
        (task_dir / "task.toml").write_text(
            _task_toml(
                task_id=task_id,
                category=category,
                task_type=task_type,
                expected=expected,
                requires_cosim=bool(donor_spec.get("requires_cosim", False)),
                source=source,
                hidden_tb=hidden_tb,
                mutation=mutation,
            ),
            encoding="utf-8",
        )
        replacements.append(
            {
                "task_id": task_id,
                "category": category,
                "rejected_source_task_id": tomllib.loads(
                    (archive / "task.toml").read_text(encoding="utf-8")
                )["source_task_id"],
                "replacement_source_task_id": donor_spec["source_task_id"],
                "replacement_kernel_family_id": donor_spec["kernel_family_id"],
                "validated_donor_task_id": donor_spec["task_id"],
                "rejected_evidence": str(archived_evidence),
                "rejected_evidence_sha256": _sha256(archived_evidence),
                "quarantined_task": str(archive),
            }
        )

    refresh_candidate_manifest(task_root)
    audit = {
        "schema_version": 1,
        "purpose": "track_a_candidate_replacement_audit",
        "replaced_count": len(replacements),
        "replacement_policy": (
            "only rejected candidates; donor baseline and reference already "
            "accepted; donor kernel family remains inside the same category"
        ),
        "replacements": replacements,
    }
    audit_path = evidence_root / "candidate_replacement_audit.json"
    audit_path.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, default=Path("tasks/track_a_150"))
    parser.add_argument("--source-root", type=Path, default=Path("tasks/generated"))
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--quarantine-root", type=Path, required=True)
    args = parser.parse_args()
    audit = replace(
        task_root=args.task_root,
        source_root=args.source_root,
        evidence_root=args.evidence_root,
        quarantine_root=args.quarantine_root,
    )
    print(
        f"replaced={audit['replaced_count']} "
        f"audit={args.evidence_root / 'candidate_replacement_audit.json'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
