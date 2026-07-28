#!/usr/bin/env python3
"""Wait for Track-A shard summaries to finish, then write final reports."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def _main_completed_count(run_root: Path) -> tuple[int, int, dict[str, int]]:
    done = 0
    expected = 0
    outcomes: dict[str, int] = {}
    for path in sorted(run_root.glob("shard_*/shard_summary.json")):
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        done += int(summary.get("completed_record_count") or 0)
        expected += int(summary.get("selected_task_count") or 0)
        for key, value in (summary.get("outcome_counts") or {}).items():
            outcomes[str(key)] = outcomes.get(str(key), 0) + int(value)
    return done, expected, outcomes


def _summary_complete(path: Path) -> bool:
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return int(summary.get("completed_record_count") or 0) >= int(
        summary.get("selected_task_count") or 0
    )


def _run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--corpus-manifest", required=True, type=Path)
    parser.add_argument("--gate-matrix", required=True, type=Path)
    parser.add_argument("--expected-count", type=int, default=150)
    parser.add_argument("--poll-s", type=float, default=300.0)
    parser.add_argument(
        "--extra-shard-summary",
        action="append",
        type=Path,
        default=[],
        help="Additional retry shard summaries to include after they complete.",
    )
    parser.add_argument(
        "--extra-shard-glob",
        action="append",
        default=[],
        help="Run-root-relative glob for retry shard summaries to include.",
    )
    args = parser.parse_args()

    while True:
        done, expected, outcomes = _main_completed_count(args.run_root)
        extra_paths = list(args.extra_shard_summary)
        for pattern in args.extra_shard_glob:
            extra_paths.extend(sorted(args.run_root.glob(pattern)))
        extra_paths = sorted(set(extra_paths))
        extra_ready = [
            str(path)
            for path in extra_paths
            if path.is_file() and _summary_complete(path)
        ]
        print(
            f"wait-finalize: progress={done}/{args.expected_count} "
            f"selected={expected} outcomes={outcomes} "
            f"extra_ready={len(extra_ready)}/{len(extra_paths)}",
            flush=True,
        )
        if done >= args.expected_count and len(extra_ready) == len(extra_paths):
            break
        time.sleep(args.poll_s)

    shard_args: list[str] = []
    for path in sorted(args.run_root.glob("shard_*/shard_summary.json")):
        shard_args.extend(["--shard-summary", str(path)])
    extra_paths = list(args.extra_shard_summary)
    for pattern in args.extra_shard_glob:
        extra_paths.extend(sorted(args.run_root.glob(pattern)))
    for path in sorted(set(extra_paths)):
        shard_args.extend(["--shard-summary", str(path)])
    _run(
        [
            sys.executable,
            "tools/finalize_track_a_150.py",
            "--corpus-manifest",
            str(args.corpus_manifest),
            "--gate-matrix",
            str(args.gate_matrix),
            "--run-root",
            str(args.run_root),
            *shard_args,
        ]
    )
    _run(
        [
            sys.executable,
            "tools/write_track_a_final_summary.py",
            "--final-report",
            str(args.run_root / "final_report.json"),
            "--output",
            str(args.run_root / "FINAL_SUMMARY.md"),
        ]
    )
    print("wait-finalize: done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
