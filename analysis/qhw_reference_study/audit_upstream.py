#!/usr/bin/env python3
"""Verify imported task provenance against a checked-out upstream commit."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))
    from tools.import_public_hls_tasks import (  # pylint: disable=import-outside-toplevel
        _candidate_hash,
        _git,
        _intro_candidates,
    )

    candidates = {c.task_id: c for c in _intro_candidates(args.upstream_root)}
    records = []
    for task_dir in sorted(args.task_root.glob("amd_intro__*/")):
        spec = tomllib.loads((task_dir / "task.toml").read_text())
        task_id = spec["task_id"]
        provenance = spec["provenance"]
        candidate = candidates.get(task_id)
        actual_hash = _candidate_hash(candidate) if candidate is not None else None
        records.append(
            {
                "task_id": task_id,
                "source_url": provenance["source_url"],
                "source_path": provenance["source_path"],
                "declared_commit": provenance["repo_commit"],
                "checked_out_commit": _git(args.upstream_root, "rev-parse", "HEAD"),
                "declared_source_sha256": provenance["source_sha256"],
                "recomputed_source_sha256": actual_hash,
                "candidate_discovered": candidate is not None,
                "commit_match": (
                    provenance["repo_commit"]
                    == _git(args.upstream_root, "rev-parse", "HEAD")
                ),
                "source_hash_match": actual_hash == provenance["source_sha256"],
            }
        )
    output = {
        "schema_version": 1,
        "purpose": "verify local task imports against GitHub checkout",
        "repository": "https://github.com/Xilinx/Vitis-HLS-Introductory-Examples",
        "checked_out_commit": _git(args.upstream_root, "rev-parse", "HEAD"),
        "task_count": len(records),
        "all_candidates_discovered": all(r["candidate_discovered"] for r in records),
        "all_commits_match": all(r["commit_match"] for r in records),
        "all_source_hashes_match": all(r["source_hash_match"] for r in records),
        "tasks": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in output.items() if k != "tasks"}, indent=2))
    return 0 if (
        output["all_candidates_discovered"]
        and output["all_commits_match"]
        and output["all_source_hashes_match"]
    ) else 4


if __name__ == "__main__":
    raise SystemExit(main())
