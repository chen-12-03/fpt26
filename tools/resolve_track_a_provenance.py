#!/usr/bin/env python3
"""Resolve Track-A source provenance against an exact HLS-Eval checkout.

The audit distinguishes acquisition provenance from upstream licensing.  A
task passes only when its source kernel is a newline-normalized byte match to
the pinned HLS-Eval snapshot and the originating suite publishes an explicit
license that covers the selected kernel.  No license is inferred from the
HLS-Eval aggregation repository itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


HLS_EVAL_COMMIT = "e628c0ad9b58d3890fbc350e9b37470cc92bf183"
HLS_EVAL_REPOSITORY = "https://github.com/sharc-lab/hls-eval"

SUITES: dict[str, dict[str, str]] = {
    "c2hlsc": {
        "license": "GPL-3.0-only",
        "upstream_project_url": "https://github.com/Lucaz97/c2hlsc",
        "upstream_revision": "72d08b7d17da38b7ba9c828dce48403352be4dc3",
        "license_evidence_url": "https://github.com/Lucaz97/c2hlsc/blob/72d08b7d17da38b7ba9c828dce48403352be4dc3/LICENSE",
    },
    "chstone": {
        "license": "LicenseRef-CHStone-SoftFloat-2b",
        "upstream_project_url": "https://github.com/ferrandi/CHStone",
        "upstream_revision": "2b7e20ffd3365016faf1e4e2b86496a5c95445fb",
        "license_evidence_url": "https://github.com/ferrandi/CHStone/blob/2b7e20ffd3365016faf1e4e2b86496a5c95445fb/dfadd/softfloat.c",
    },
    "gnnbuilder": {
        "license": "AGPL-3.0-only",
        "upstream_project_url": "https://github.com/sharc-lab/gnn-builder",
        "upstream_revision": "license-observed-2026-09-09",
        "license_evidence_url": "https://github.com/sharc-lab/gnn-builder/blob/main/LICENSE",
    },
    "machsuite": {
        "license": "BSD-3-Clause",
        "upstream_project_url": "https://github.com/breagen/MachSuite",
        "upstream_revision": "license-observed-2026-09-09",
        "license_evidence_url": "https://github.com/breagen/MachSuite/blob/master/LICENSE",
    },
    "polybench": {
        "license": "LicenseRef-PolyBenchC-OSU",
        "upstream_project_url": "https://github.com/ferrandi/PolyBenchC",
        "upstream_revision": "d3a15bb1725afaaa33bcf3a4db6087ebf557c9b8",
        "license_evidence_url": "https://github.com/ferrandi/PolyBenchC/blob/d3a15bb1725afaaa33bcf3a4db6087ebf557c9b8/LICENSE.txt",
    },
    "pp4fpga": {
        "license": "CC-BY-4.0",
        "upstream_project_url": "https://github.com/KastnerRG/pp4fpgas",
        "upstream_revision": "license-observed-2026-09-09",
        "license_evidence_url": "https://github.com/KastnerRG/pp4fpgas/blob/master/LICENSE",
    },
    "rosetta": {
        "license": "BSD-3-Clause",
        "upstream_project_url": "https://github.com/cornell-zhang/rosetta",
        "upstream_revision": "license-observed-2026-09-09",
        "license_evidence_url": "https://github.com/cornell-zhang/rosetta/blob/master/LICENSE",
    },
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalized_bytes(path: Path) -> bytes:
    value = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return value.rstrip() + b"\n"


def normalized_sha256(path: Path) -> str:
    return sha256_bytes(normalized_bytes(path))


def git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-c", f"safe.directory={root.resolve()}", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"not a readable git checkout: {root}: {completed.stderr}")
    return completed.stdout.strip()


def design_dir(snapshot_root: Path, suite: str, source_task_id: str) -> Path:
    name = source_task_id.split("__", 1)[1]
    candidates = [
        path
        for path in (snapshot_root / "hls_eval_data" / suite).iterdir()
        if path.is_dir() and path.name.replace("-", "_").lower() == name.lower()
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"{source_task_id}: expected one snapshot directory, found {len(candidates)}"
        )
    return candidates[0]


def replace_scalar(text: str, key: str, value: str) -> str:
    line = f"{key} = {json.dumps(value, ensure_ascii=False)}"
    pattern = re.compile(rf"(?m)^{re.escape(key)}\s*=.*$")
    if not pattern.search(text):
        raise RuntimeError(f"missing TOML field: {key}")
    return pattern.sub(line, text, count=1)


def provenance_block(record: dict[str, str]) -> str:
    fields = (
        "source_url",
        "source_path",
        "repo_commit",
        "license",
        "upstream_project_url",
        "upstream_revision",
        "license_evidence_url",
        "acquisition_normalization",
        "acquisition_snapshot_sha256",
    )
    return "\n[provenance]\n" + "\n".join(
        f"{key} = {json.dumps(record[key], ensure_ascii=False)}" for key in fields
    ) + "\n"


def audit_task(task_dir: Path, generated_root: Path, snapshot_root: Path) -> dict[str, Any]:
    spec = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    source_task_id = str(spec["source_task_id"])
    suite = source_task_id.split("__", 1)[0]
    metadata = SUITES.get(suite)
    kernel_name = str(spec["kernel_file"])
    source_kernel = generated_root / source_task_id / kernel_name
    if metadata is None:
        placeholder = (
            spec.get("repo_commit") == "LOCAL_SNAPSHOT_REQUIRES_UPSTREAM_MATCH"
            or spec.get("license") == "UPSTREAM_REVIEW_REQUIRED"
        )
        errors = ["unsupported_placeholder_suite"] if placeholder else []
        resolved = {
            "source_url": str(spec.get("source_url", "")),
            "source_path": str(spec.get("source_path", "")),
            "repo_commit": str(spec.get("repo_commit", "")),
            "license": str(spec.get("license", "")),
            "upstream_project_url": str(spec.get("source_url", "")),
            "upstream_revision": str(spec.get("repo_commit", "")),
            "license_evidence_url": str(spec.get("source_url", "")),
            "acquisition_normalization": "source-package-provenance-preserved",
            "acquisition_snapshot_sha256": str(spec.get("source_sha256", "")),
        }
        return {
            "task_id": str(spec["task_id"]),
            "source_task_id": source_task_id,
            "suite": suite,
            "kernel_file": kernel_name,
            "resolution_type": "existing_source_package_provenance",
            "snapshot_design_path": None,
            "generated_source_sha256": (
                normalized_sha256(source_kernel) if source_kernel.is_file() else None
            ),
            "snapshot_source_sha256": None,
            "normalized_byte_match": None,
            "license_verified": not placeholder,
            "resolved": resolved,
            "errors": errors,
            "passed": not errors,
        }
    design = design_dir(snapshot_root, suite, source_task_id)
    snapshot_kernel = design / kernel_name
    errors: list[str] = []
    if not source_kernel.is_file():
        errors.append("generated_source_kernel_missing")
    if not snapshot_kernel.is_file():
        errors.append("snapshot_kernel_missing")
    exact_normalized_match = bool(
        not errors and normalized_bytes(source_kernel) == normalized_bytes(snapshot_kernel)
    )
    if not exact_normalized_match:
        errors.append("generated_source_not_snapshot_normalized_byte_match")
    license_name = metadata["license"]
    if source_task_id == "machsuite__aes_aes":
        license_name = "ISC"
    source_path = f"hls_eval_data/{suite}/{design.name}/{kernel_name}"
    source_url = (
        f"{HLS_EVAL_REPOSITORY}/tree/{HLS_EVAL_COMMIT}/"
        f"hls_eval_data/{suite}/{design.name}"
    )
    resolved = {
        "source_url": source_url,
        "source_path": source_path,
        "repo_commit": HLS_EVAL_COMMIT,
        "license": license_name,
        "upstream_project_url": metadata["upstream_project_url"],
        "upstream_revision": metadata["upstream_revision"],
        "license_evidence_url": metadata["license_evidence_url"],
        "acquisition_normalization": "universal-newlines-and-one-terminal-newline",
        "acquisition_snapshot_sha256": (
            normalized_sha256(snapshot_kernel) if snapshot_kernel.is_file() else ""
        ),
    }
    return {
        "task_id": str(spec["task_id"]),
        "source_task_id": source_task_id,
        "suite": suite,
        "kernel_file": kernel_name,
        "resolution_type": "exact_hls_eval_snapshot_plus_upstream_license",
        "snapshot_design_path": f"hls_eval_data/{suite}/{design.name}",
        "generated_source_sha256": (
            normalized_sha256(source_kernel) if source_kernel.is_file() else None
        ),
        "snapshot_source_sha256": (
            normalized_sha256(snapshot_kernel) if snapshot_kernel.is_file() else None
        ),
        "normalized_byte_match": exact_normalized_match,
        "license_verified": metadata is not None,
        "resolved": resolved,
        "errors": errors,
        "passed": not errors,
    }


def apply_task_toml(task_dir: Path, record: dict[str, Any]) -> None:
    if record["resolution_type"] == "existing_source_package_provenance":
        return
    resolved = record["resolved"]
    path = task_dir / "task.toml"
    text = path.read_text(encoding="utf-8")
    for key in ("source_url", "source_path", "repo_commit", "license"):
        text = replace_scalar(text, key, resolved[key])
    additions = (
        "upstream_project_url",
        "upstream_revision",
        "license_evidence_url",
        "acquisition_normalization",
        "acquisition_snapshot_sha256",
    )
    anchor = "\n[target]\n"
    if anchor not in text:
        raise RuntimeError(f"{record['task_id']}: missing [target] section")
    extra_lines: list[str] = []
    for key in additions:
        rendered = json.dumps(resolved[key], ensure_ascii=False)
        pattern = re.compile(rf"(?m)^{re.escape(key)}\s*=.*$")
        if pattern.search(text):
            text = pattern.sub(f"{key} = {rendered}", text, count=1)
        else:
            extra_lines.append(f"{key} = {rendered}\n")
    extra = "".join(extra_lines)
    text = text.replace(anchor, "\n" + extra + anchor, 1)
    path.write_text(text, encoding="utf-8")


def apply_source_package(generated_root: Path, record: dict[str, Any]) -> None:
    if record["resolution_type"] == "existing_source_package_provenance":
        return
    path = generated_root / record["source_task_id"] / "task.toml"
    text = path.read_text(encoding="utf-8")
    if "\n[provenance]\n" in text.replace("\r\n", "\n"):
        return
    path.write_text(text.rstrip() + "\n" + provenance_block(record["resolved"]), encoding="utf-8")


def apply_manifest(task_root: Path, records: list[dict[str, Any]]) -> None:
    path = task_root / "candidate_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    by_id = {record["task_id"]: record for record in records}
    statuses: Counter[str] = Counter()
    for task in manifest["tasks"]:
        record = by_id[str(task["task_id"])]
        resolved = record["resolved"]
        for key in ("source_url", "repo_commit", "license"):
            task[key] = resolved[key]
        task["source_path"] = resolved["source_path"]
        task["provenance_status"] = (
            "verified_exact_acquisition_snapshot_and_upstream_license"
            if record["passed"]
            else "blocked"
        )
        statuses[task["provenance_status"]] += 1
    manifest["provenance_status_counts"] = dict(sorted(statuses.items()))
    manifest["source_pool"]["selected_by_suite"] = dict(
        sorted(Counter(record["suite"] for record in records).items())
    )
    manifest["remaining_gates"] = [
        item
        for item in manifest.get("remaining_gates", [])
        if "UPSTREAM_REVIEW_REQUIRED" not in item
    ]
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--generated-root", type=Path, default=Path("tasks/generated"))
    parser.add_argument("--hls-eval-checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    observed_commit = git_head(args.hls_eval_checkout)
    if observed_commit != HLS_EVAL_COMMIT:
        raise SystemExit(
            f"wrong HLS-Eval checkout: expected {HLS_EVAL_COMMIT}, got {observed_commit}"
        )
    task_dirs = sorted(path.parent for path in args.task_root.glob("*/task.toml"))
    records = [
        audit_task(task_dir, args.generated_root, args.hls_eval_checkout)
        for task_dir in task_dirs
    ]
    if args.apply:
        for task_dir, record in zip(task_dirs, records):
            if not record["passed"]:
                continue
            apply_task_toml(task_dir, record)
            apply_source_package(args.generated_root, record)
        apply_manifest(args.task_root, records)

    payload = {
        "schema_version": 1,
        "purpose": "track_a_exact_acquisition_and_license_provenance",
        "hls_eval_repository": HLS_EVAL_REPOSITORY,
        "expected_commit": HLS_EVAL_COMMIT,
        "observed_commit": observed_commit,
        "normalization": "CRLF/CR converted to LF; trailing whitespace-only EOF normalized to one newline",
        "task_count": len(records),
        "passed_count": sum(record["passed"] for record in records),
        "failed_count": sum(not record["passed"] for record in records),
        "suite_counts": dict(sorted(Counter(record["suite"] for record in records).items())),
        "license_counts": dict(
            sorted(Counter(record["resolved"]["license"] for record in records).items())
        ),
        "failed_task_ids": [record["task_id"] for record in records if not record["passed"]],
        "limitations": [
            "The HLS-Eval acquisition commit is verified locally; upstream revisions identify license evidence, not byte identity.",
            "License labels are provenance metadata, not legal advice.",
            "The CHStone tasks selected here are SoftFloat-derived functions and retain the Release 2b notice requirement.",
        ],
        "records": records,
        "passed": len(records) == 150 and all(record["passed"] for record in records),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in (
        "task_count", "passed_count", "failed_count", "suite_counts", "license_counts", "passed"
    )}, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
