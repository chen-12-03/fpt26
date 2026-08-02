#!/usr/bin/env python3
"""Compact Vitis run trees while retaining their formal reports in place.

Only directories named synth_proj, csim_proj, or cosim_proj below explicitly
provided run roots are considered.  Inside those directories, files below a
formal ``report`` directory are retained; all other generated project files
are disposable Vitis intermediates.  Files outside those project directories
are never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


PROJECT_DIR_NAMES = {"synth_proj", "csim_proj", "cosim_proj"}
MANIFEST_NAME = "VITIS_COMPACTION_MANIFEST.json"


def allocated_bytes(path: Path) -> int:
    return path.lstat().st_blocks * 512


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_projects(run_root: Path) -> list[Path]:
    projects: list[Path] = []
    for current, dirs, _files in os.walk(run_root):
        current_path = Path(current)
        project_children = [name for name in dirs if name in PROJECT_DIR_NAMES]
        for name in project_children:
            projects.append(current_path / name)
            dirs.remove(name)
    return sorted(projects)


def is_formal_report(project_root: Path, path: Path) -> bool:
    relative_parts = path.relative_to(project_root).parts
    return "report" in relative_parts


def scan_project(project_root: Path) -> dict:
    retained: list[dict] = []
    delete_files = 0
    delete_allocated = 0
    before_files = 0
    before_allocated = 0
    deleted_suffixes: Counter[str] = Counter()

    for current, _dirs, files in os.walk(project_root):
        current_path = Path(current)
        for name in files:
            path = current_path / name
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            size_allocated = info.st_blocks * 512
            before_files += 1
            before_allocated += size_allocated
            if stat.S_ISREG(info.st_mode) and is_formal_report(project_root, path):
                retained.append(
                    {
                        "path": path,
                        "logical_bytes": info.st_size,
                        "allocated_bytes": size_allocated,
                    }
                )
            else:
                delete_files += 1
                delete_allocated += size_allocated
                deleted_suffixes[path.suffix or "<none>"] += 1

    return {
        "before_files": before_files,
        "before_allocated_bytes": before_allocated,
        "delete_files": delete_files,
        "delete_allocated_bytes": delete_allocated,
        "deleted_suffixes": deleted_suffixes,
        "retained": retained,
    }


def delete_non_reports(project_root: Path) -> None:
    for current, dirs, files in os.walk(project_root, topdown=False):
        current_path = Path(current)
        for name in files:
            path = current_path / name
            if not is_formal_report(project_root, path):
                path.unlink(missing_ok=True)
        for name in dirs:
            path = current_path / name
            try:
                path.rmdir()
            except OSError:
                pass
    try:
        project_root.rmdir()
    except OSError:
        pass


def compact_run(run_root: Path, apply: bool) -> dict:
    projects = discover_projects(run_root)
    totals = Counter()
    projects_by_type: Counter[str] = Counter()
    suffix_counts: Counter[str] = Counter()
    retained_records: list[dict] = []

    for project_root in projects:
        projects_by_type[project_root.name] += 1
        scan = scan_project(project_root)
        totals.update(
            {
                "before_files": scan["before_files"],
                "before_allocated_bytes": scan["before_allocated_bytes"],
                "deleted_files": scan["delete_files"],
                "deleted_allocated_bytes": scan["delete_allocated_bytes"],
                "retained_files": len(scan["retained"]),
                "retained_allocated_bytes": sum(
                    item["allocated_bytes"] for item in scan["retained"]
                ),
            }
        )
        suffix_counts.update(scan["deleted_suffixes"])

        for item in scan["retained"]:
            path = item.pop("path")
            retained_records.append(
                {
                    "path": str(path.relative_to(run_root)),
                    **item,
                    **({"sha256": sha256(path)} if apply else {}),
                }
            )

        if apply:
            delete_non_reports(project_root)

    result = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "applied" if apply else "dry-run",
        "run_root": str(run_root),
        "policy": {
            "project_directory_names": sorted(PROJECT_DIR_NAMES),
            "retained_inside_projects": "regular files below directories named report",
            "deleted_inside_projects": "all other generated files and empty directories",
            "outside_project_directories": "untouched",
        },
        "summary": {
            "project_directories": len(projects),
            "projects_by_type": dict(sorted(projects_by_type.items())),
            **dict(totals),
            "deleted_suffix_counts": dict(suffix_counts.most_common()),
        },
        "retained_reports": retained_records,
    }

    if apply:
        manifest = run_root / MANIFEST_NAME
        temporary = manifest.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.chmod(temporary, 0o644)
        temporary.replace(manifest)

    return result


def validate_run_root(workspace: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = workspace / path
    path = path.resolve()
    allowed_root = (workspace / "runs").resolve()
    if path.parent == allowed_root or allowed_root in path.parents:
        if path.is_dir():
            return path
    raise ValueError(f"refusing run root outside {allowed_root}: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_roots", nargs="+")
    parser.add_argument(
        "--workspace", default="/workspace", help="workspace mounted in the container"
    )
    parser.add_argument(
        "--apply", action="store_true", help="perform deletion and write manifests"
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    results = [
        compact_run(validate_run_root(workspace, value), args.apply)
        for value in args.run_roots
    ]
    output = {
        "mode": "applied" if args.apply else "dry-run",
        "runs": [
            {
                "run_root": item["run_root"],
                "summary": item["summary"],
            }
            for item in results
        ],
        "total_deleted_allocated_bytes": sum(
            item["summary"]["deleted_allocated_bytes"] for item in results
        ),
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
