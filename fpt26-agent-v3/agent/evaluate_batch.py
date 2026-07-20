#!/usr/bin/env python3
"""Batch evaluator — gates every task on valid SubmissionEvidence.

Usage::

    python -m agent.evaluate_batch --runs-root runs/p0_run --tasks-root tasks/official

For each task directory under ``--tasks-root``, the script:
1. Looks for ``submission_evidence.json`` under the corresponding run output
2. Validates schema, status (must be "completed"), task_id, and kernel SHA-256
3. Skips tasks with missing, damaged, or failed evidence
4. Launches ``evaluate_final_kernel()`` only for tasks with valid evidence
5. Writes a batch summary JSON

No evaluator is started for any task whose submission evidence is missing,
corrupted, has a mismatched digest, or whose status is not "completed".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Batch evaluator — gates every task on SubmissionEvidence"
    )
    p.add_argument("--runs-root", required=True, type=Path,
                   help="Root containing per-task run outputs")
    p.add_argument("--tasks-root", required=True, type=Path,
                   help="Root containing task directories (official/ or generated/)")
    p.add_argument("--scoring-profile", default="balanced",
                   choices=("balanced", "extreme_speed", "extreme_speed_capped"))
    p.add_argument("--output", type=Path, default=None,
                   help="Write batch summary JSON here")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args(argv)


def _load_evidence(evidence_path: Path) -> dict[str, Any] | None:
    """Load and lightly validate a submission_evidence.json.

    Returns the parsed dict, or None if the file is missing or unreadable.
    """
    if not evidence_path.is_file():
        return None
    try:
        data = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _evidence_ok(evidence: dict[str, Any], kernel_path: Path) -> tuple[bool, str]:
    """Validate submission evidence against the final kernel on disk.

    Returns (ok, reason).
    """
    import hashlib

    schema = evidence.get("schema_version")
    if not isinstance(schema, int) or schema < 1:
        return False, "missing or invalid schema_version"

    status = evidence.get("status")
    if status != "completed":
        return False, f"submission status is {status!r}, not 'completed'"

    task_id = evidence.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        return False, "missing task_id"

    expected_sha = evidence.get("kernel_sha256")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        return False, "missing or invalid kernel_sha256"

    if not kernel_path.is_file():
        return False, f"final kernel not found: {kernel_path}"

    actual_sha = hashlib.sha256(kernel_path.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        return False, (
            f"digest mismatch: evidence={expected_sha[:16]}… "
            f"actual={actual_sha[:16]}…"
        )

    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    runs_root = args.runs_root.resolve()
    tasks_root = args.tasks_root.resolve()

    if not runs_root.is_dir():
        print(f"error: runs-root not found: {runs_root}", file=sys.stderr)
        return 2
    if not tasks_root.is_dir():
        print(f"error: tasks-root not found: {tasks_root}", file=sys.stderr)
        return 2

    # Discover tasks (look for task.toml in subdirectories)
    task_dirs = sorted(
        d for d in tasks_root.iterdir()
        if d.is_dir() and (d / "task.toml").is_file()
    )
    if not task_dirs:
        print(f"No task directories found under {tasks_root}", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    evaluated = 0
    skipped = 0
    failed = 0

    for task_dir in task_dirs:
        task_id = task_dir.name
        run_dir = runs_root / task_id
        evidence_path = run_dir / "submission_evidence.json"
        kernel_path = run_dir / f"final_{task_id}.cpp"

        # Also try the agent's final kernel naming convention
        if not kernel_path.is_file():
            # Look for any final_*.cpp
            candidates = sorted(run_dir.glob("final_*.cpp"))
            if candidates:
                kernel_path = candidates[0]

        evidence = _load_evidence(evidence_path)

        entry: dict[str, Any] = {
            "task_id": task_id,
            "evidence_path": str(evidence_path),
            "kernel_path": str(kernel_path),
            "evidence_found": evidence is not None,
        }

        if evidence is None:
            entry["action"] = "SKIPPED"
            entry["reason"] = "submission_evidence.json missing or unreadable"
            skipped += 1
            if not args.quiet:
                print(f"SKIP  {task_id}: no submission evidence")
            results.append(entry)
            continue

        ok, reason = _evidence_ok(evidence, kernel_path)
        entry["evidence_valid"] = ok
        entry["evidence_status"] = evidence.get("status")
        entry["evidence_reason"] = reason

        if not ok:
            entry["action"] = "SKIPPED"
            entry["reason"] = reason
            skipped += 1
            if not args.quiet:
                print(f"SKIP  {task_id}: {reason}")
            results.append(entry)
            continue

        # ── Evidence valid — launch evaluator ──────────────────────────
        if not args.quiet:
            print(f"EVAL  {task_id}: evidence valid, launching evaluator...")

        try:
            from agent.evaluator import evaluate_final_kernel
            from agent.reporting import write_run_report

            score_state = evaluate_final_kernel(
                task_dir=task_dir,
                kernel_path=kernel_path,
                output_root=str(runs_root),
                scoring_profile=args.scoring_profile,
                verbose=not args.quiet,
            )
            write_run_report(score_state)

            entry["action"] = "EVALUATED"
            entry["evaluator_status"] = score_state.status
            sc = getattr(score_state, "scorecard", None)
            if sc is not None:
                entry["score"] = getattr(sc, "score", None)
                entry["score_max"] = getattr(sc, "score_max", None)
                entry["valid"] = getattr(sc, "valid", False)
            evaluated += 1
            if not args.quiet:
                score_str = f"score={entry.get('score')}" if entry.get('score') is not None else "no score"
                print(f"  -> {score_state.status} {score_str}")
        except Exception as exc:
            entry["action"] = "FAILED"
            entry["reason"] = f"{type(exc).__name__}: {exc}"
            failed += 1
            if not args.quiet:
                print(f"FAIL  {task_id}: {exc}")

        results.append(entry)

    # ── Summary ────────────────────────────────────────────────────────
    summary = {
        "total_tasks": len(task_dirs),
        "evaluated": evaluated,
        "skipped": skipped,
        "failed": failed,
        "runs_root": str(runs_root),
        "tasks_root": str(tasks_root),
        "scoring_profile": args.scoring_profile,
        "results": results,
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"\nBatch summary written to {args.output}")

    print(f"\n=== Batch complete: {evaluated} evaluated, "
          f"{skipped} skipped, {failed} failed "
          f"(of {len(task_dirs)} total) ===")

    return 0 if failed == 0 else 4


if __name__ == "__main__":
    sys.exit(main())
