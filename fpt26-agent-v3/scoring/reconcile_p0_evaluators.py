"""Run missing evaluators for fresh P0 shard records with readable finals."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scoring.run_p0_real_api_shard import (
    _load_report,
    _run,
    _sha256,
    _write_summary,
    build_evaluator_command,
    classify_outcome,
    validate_evaluator,
    validate_submission,
)


def reconcile(root: Path, timeout_s: float) -> dict[str, Any]:
    summary_path = root / "shard_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    reconciled = 0

    for record in summary.get("records") or []:
        submission_record = record.get("submission") or {}
        evaluator_record = record.get("evaluator") or {}
        evaluator_path = Path(evaluator_record.get("report") or "")
        if evaluator_path.is_file():
            continue
        final_path = Path(submission_record.get("final_kernel") or "")
        submission_path = Path(submission_record.get("report") or "")
        evidence_text = submission_record.get("submission_evidence")
        submission_evidence = (
            Path(evidence_text)
            if evidence_text
            else submission_path.with_name("submission_evidence.json")
        )
        task_dir = Path(record.get("task_dir") or "")
        if (
            not final_path.is_file()
            or not submission_path.is_file()
            or not submission_evidence.is_file()
            or not task_dir.is_dir()
        ):
            continue

        attempt_root = Path(record["attempt_root"])
        evaluator_root = attempt_root / "evaluator"
        evaluator_log = attempt_root / "evaluator.log"
        task_id = record["task_id"]
        command = build_evaluator_command(
            task_dir=task_dir,
            final_kernel=final_path,
            submission_evidence=submission_evidence,
            output_root=evaluator_root,
        )
        return_code, launcher_error, elapsed = _run(
            command, evaluator_log, timeout_s
        )
        evaluator_path = evaluator_root / task_id / "run_report.json"
        evaluator: dict[str, Any] | None = None
        errors: list[str] = []
        try:
            evaluator = _load_report(evaluator_path)
            expected_grading_source = (
                "hidden"
                if (task_dir / "hidden").is_dir()
                else "public_fallback"
            )
            errors = validate_evaluator(
                evaluator,
                task_id,
                official_task=bool(record.get("official_task")),
                expected_grading_source=expected_grading_source,
            )
        except Exception as exc:
            errors = [str(exc)]

        submission = _load_report(submission_path)
        errors = validate_submission(submission, task_id) + errors
        record["audit_errors"] = sorted(set(errors))
        if launcher_error:
            record["launcher_error"] = launcher_error
        record["evaluator"] = {
            "command": command,
            "return_code": return_code,
            "elapsed_s": elapsed,
            "log": str(evaluator_log),
            "report": str(evaluator_path),
            "report_sha256": (
                _sha256(evaluator_path)
                if evaluator_path.is_file()
                else None
            ),
            "status": (evaluator or {}).get("status"),
            "stop_reason": (evaluator or {}).get("stop_reason"),
            "grading_source": (
                (evaluator or {}).get("grading") or {}
            ).get("source"),
            "score": (
                (evaluator or {}).get("scoring") or {}
            ).get("score"),
        }
        record["outcome"] = classify_outcome(
            submission,
            evaluator,
            str(record.get("launcher_error") or ""),
        )
        reconciled += 1
        print(
            f"reconciled evaluator task={task_id} rc={return_code} "
            f"status={(evaluator or {}).get('status')} errors={errors}",
            flush=True,
        )

    outcomes: dict[str, int] = {}
    for record in summary.get("records") or []:
        outcome = record["outcome"]
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    summary["outcome_counts"] = dict(sorted(outcomes.items()))
    summary["audit_error_record_count"] = sum(
        bool(record.get("audit_errors"))
        for record in summary.get("records") or []
    )
    summary["reconciled_evaluator_count"] = (
        int(summary.get("reconciled_evaluator_count") or 0) + reconciled
    )
    _write_summary(summary_path, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", action="append", required=True, type=Path)
    parser.add_argument("--task-timeout-s", type=float, default=7200.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    total = 0
    for root in args.run_root:
        before = json.loads(
            (root / "shard_summary.json").read_text(encoding="utf-8")
        ).get("reconciled_evaluator_count", 0)
        result = reconcile(root.resolve(), args.task_timeout_s)
        total += result.get("reconciled_evaluator_count", 0) - before
    print(f"reconciled missing evaluators: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
