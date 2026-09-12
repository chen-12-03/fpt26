#!/usr/bin/env python3
"""Freeze physically separated public-agent and evaluator Track-A bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


CATEGORY_CODES = {
    "code_generation": "cg",
    "compile_repair": "cr",
    "synthesis_repair": "sr",
    "functional_repair": "fr",
    "structural_cosim_repair": "xr",
    "qor_optimization": "qo",
}
PUBLIC_KEYS = (
    "task_type",
    "difficulty",
    "top",
    "kernel_file",
    "header_files",
    "public_tb",
    "budget",
    "requires_cosim",
    "initial_condition",
)
FORBIDDEN_PUBLIC_KEYS = {
    "hidden_tb",
    "expected_baseline_state",
    "fault_derivation",
    "kernel_family_id",
    "source_task_id",
    "source_url",
    "source_path",
    "repo_commit",
    "license",
    "source_sha256",
    "upstream_project_url",
    "upstream_revision",
    "license_evidence_url",
    "acquisition_normalization",
    "acquisition_snapshot_sha256",
    "internal_task_id",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    raise TypeError(f"unsupported TOML value: {type(value)}")


def public_toml(spec: dict[str, Any], public_id: str) -> str:
    lines = [f"task_id = {toml_value(public_id)}"]
    for key in PUBLIC_KEYS:
        if key in spec:
            lines.append(f"{key} = {toml_value(spec[key])}")
    target = dict(spec.get("target") or {})
    lines.extend(["", "[target]"])
    for key in ("part", "clock_ns", "minimum_frequency_mhz"):
        if key in target:
            lines.append(f"{key} = {toml_value(target[key])}")
    return "\n".join(lines) + "\n"


def evaluator_toml(text: str, internal_id: str, public_id: str) -> str:
    old = f'task_id = {json.dumps(internal_id)}'
    new = (
        f'task_id = {json.dumps(public_id)}\n'
        f'internal_task_id = {json.dumps(internal_id)}'
    )
    if text.count(old) != 1:
        raise RuntimeError(f"{internal_id}: task_id declaration is not canonical")
    return text.replace(old, new, 1)


def code_generation_specification(description: str, internal_id: str) -> str:
    """Return the public, provenance-free kernel contract for a generation task."""

    marker = "## Kernel specification"
    if marker not in description:
        raise RuntimeError(f"{internal_id}: missing {marker!r} in description.md")
    kernel_spec = description.split(marker, 1)[1].strip()

    # A future imported task may append provenance after the useful contract.
    # Never expose that private source locator merely because the current CG set
    # happens not to contain one.
    kernel_spec = kernel_spec.split("\nProvenance:", 1)[0].strip()
    lowered = kernel_spec.lower()
    forbidden_fragments = (
        "github.com/",
        "http://",
        "https://",
        "source sha-256",
        "repo_commit",
        "source_url",
        internal_id.lower(),
    )
    leaked = [item for item in forbidden_fragments if item and item in lowered]
    if leaked:
        raise RuntimeError(
            f"{internal_id}: source locator in kernel specification: {leaked}"
        )
    if len(kernel_spec) < 400:
        raise RuntimeError(
            f"{internal_id}: kernel specification is too short ({len(kernel_spec)} chars)"
        )
    return kernel_spec


def public_description(
    spec: dict[str, Any], public_id: str, source_description: str
) -> str:
    category = str(spec["track_a_category"])
    instruction = {
        "code_generation": "Implement the missing HLS kernel.",
        "compile_repair": "Repair the compilation failure.",
        "synthesis_repair": "Repair the HLS synthesis failure while preserving behavior.",
        "functional_repair": "Repair the functional defect.",
        "structural_cosim_repair": "Repair the C/RTL CoSim mismatch.",
        "qor_optimization": "Improve hardware QoR while preserving exact behavior.",
    }[category]
    text = (
        f"# {public_id}\n\n"
        f"{instruction}\n\n"
        f"Edit only `{spec['kernel_file']}`. Preserve the top-level function "
        f"`{spec['top']}`, its signature, headers, file names, data types, and "
        "testbench contract. The target is Alveo U55C under Vitis 2025.2 with "
        "a minimum frequency of 100 MHz.\n"
    )
    if category == "code_generation":
        kernel_spec = code_generation_specification(
            source_description, str(spec["task_id"])
        )
        text += f"\n## Kernel specification\n\n{kernel_spec}\n"
    return text


def tree_manifest(root: Path, excluded: set[str] | None = None) -> dict[str, Any]:
    excluded = excluded or set()
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        records.append(
            {"path": relative, "size": path.stat().st_size, "sha256": sha256(path)}
        )
    digest = hashlib.sha256()
    for item in records:
        digest.update(item["path"].encode())
        digest.update(b"\0")
        digest.update(item["sha256"].encode())
        digest.update(b"\n")
    return {"file_count": len(records), "tree_sha256": digest.hexdigest(), "files": records}


def ensure_clean_output(path: Path) -> None:
    if path.exists():
        raise RuntimeError(f"refusing to overwrite existing release: {path}")
    path.mkdir(parents=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    ensure_clean_output(args.output_root)
    public_root = args.output_root / "public_agent"
    evaluator_root = args.output_root / "evaluator_private"
    public_root.mkdir()
    evaluator_root.mkdir()

    task_dirs = sorted(path.parent for path in args.task_root.glob("*/task.toml"))
    if len(task_dirs) != 150:
        raise RuntimeError(f"expected 150 tasks, found {len(task_dirs)}")
    per_category: Counter[str] = Counter()
    mapping = []
    for task_dir in task_dirs:
        spec = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
        category = str(spec["track_a_category"])
        per_category[category] += 1
        public_id = f"ta2_{CATEGORY_CODES[category]}_{per_category[category]:03d}"
        internal_id = str(spec["task_id"])
        public_task = public_root / public_id
        evaluator_task = evaluator_root / public_id
        public_task.mkdir()
        shutil.copytree(task_dir, evaluator_task)

        # Rewrite evaluator identity but preserve all evaluator-only metadata.
        evaluator_toml_path = evaluator_task / "task.toml"
        evaluator_toml_path.write_text(
            evaluator_toml(
                evaluator_toml_path.read_text(encoding="utf-8"), internal_id, public_id
            ),
            encoding="utf-8",
        )

        # Public files are root-level regular files only.  Hidden/reference and
        # internal task metadata are never copied into this tree.
        for source in sorted(task_dir.iterdir()):
            if source.is_symlink():
                raise RuntimeError(f"symlink not allowed: {source}")
            if not source.is_file() or source.name in {"task.toml", "description.md"}:
                continue
            shutil.copy2(source, public_task / source.name)
        (public_task / "task.toml").write_text(
            public_toml(spec, public_id), encoding="utf-8"
        )
        source_description = (task_dir / "description.md").read_text(encoding="utf-8")
        (public_task / "description.md").write_text(
            public_description(spec, public_id, source_description), encoding="utf-8"
        )
        mapping.append(
            {
                "public_task_id": public_id,
                "internal_task_id": internal_id,
                "category": category,
                "difficulty": int(spec["difficulty"]),
                "source_task_id": spec["source_task_id"],
                "source_url": spec["source_url"],
                "source_path": spec["source_path"],
                "repo_commit": spec["repo_commit"],
                "license": spec["license"],
                "source_sha256": spec["source_sha256"],
                "fault_derivation": spec["fault_derivation"],
            }
        )

    notice = args.task_root / "THIRD_PARTY_NOTICES.md"
    shutil.copy2(notice, public_root / notice.name)
    shutil.copy2(notice, evaluator_root / notice.name)
    public_index = {
        "schema_version": 1,
        "purpose": "track_a_public_agent_corpus",
        "task_count": 150,
        "category_counts": dict(sorted(per_category.items())),
        "id_policy": "blind_ids_no_upstream_path_or_revision",
        "description_policy": (
            "full_provenance_free_contract_for_code_generation; "
            "blind_category_instruction_for_repair_and_optimization"
        ),
        "contains_hidden_or_reference": False,
        "tasks": [
            {
                "task_id": item["public_task_id"],
                "category": item["category"],
                "difficulty": item["difficulty"],
            }
            for item in mapping
        ],
    }
    json_dump(public_root / "PUBLIC_CORPUS_MANIFEST.json", public_index)
    private_index = {
        "schema_version": 1,
        "purpose": "track_a_evaluator_mapping_and_provenance",
        "task_count": 150,
        "tasks": mapping,
    }
    json_dump(evaluator_root / "EVALUATOR_MAPPING.json", private_index)

    # Release audit: exactly 150 public task specs, no evaluator path segments,
    # no provenance/fault keys in public specs, and no exact source URL in task
    # descriptions or task TOML files.
    violations = []
    for path in sorted(public_root.rglob("*")):
        relative = path.relative_to(public_root)
        if any(part.lower() in {"hidden", "reference"} for part in relative.parts):
            violations.append(f"forbidden_path:{relative.as_posix()}")
    for path in sorted(public_root.glob("*/task.toml")):
        spec = tomllib.loads(path.read_text(encoding="utf-8"))
        leaked = sorted(FORBIDDEN_PUBLIC_KEYS & set(spec))
        if leaked:
            violations.append(f"forbidden_keys:{path.parent.name}:{','.join(leaked)}")
        description = (path.parent / "description.md").read_text(encoding="utf-8")
        if "github.com/" in description or "Provenance:" in description:
            violations.append(f"source_locator_in_description:{path.parent.name}")
        if path.parent.name.startswith("ta2_cg_"):
            if "## Kernel specification" not in description:
                violations.append(
                    f"missing_kernel_specification:{path.parent.name}"
                )
            elif len(description.split("## Kernel specification", 1)[1].strip()) < 400:
                violations.append(f"short_kernel_specification:{path.parent.name}")
    if len(list(public_root.glob("*/task.toml"))) != 150:
        violations.append("public_task_count_not_150")

    public_files = tree_manifest(public_root, {"FILE_MANIFEST.json"})
    evaluator_files = tree_manifest(evaluator_root, {"FILE_MANIFEST.json"})
    json_dump(public_root / "FILE_MANIFEST.json", public_files)
    json_dump(evaluator_root / "FILE_MANIFEST.json", evaluator_files)
    release = {
        "schema_version": 1,
        "purpose": "track_a_corpus_release_freeze",
        "task_count": 150,
        "category_counts": dict(sorted(per_category.items())),
        "public_tree_sha256": public_files["tree_sha256"],
        "evaluator_tree_sha256": evaluator_files["tree_sha256"],
        "public_file_count": public_files["file_count"],
        "evaluator_file_count": evaluator_files["file_count"],
        "public_private_separation_pass": not violations,
        "violations": violations,
        "id_mapping_location": "evaluator_private/EVALUATOR_MAPPING.json",
    }
    json_dump(args.output_root / "RELEASE_MANIFEST.json", release)
    print(json.dumps(release, indent=2, sort_keys=True))
    return 0 if not violations else 2


if __name__ == "__main__":
    raise SystemExit(main())
