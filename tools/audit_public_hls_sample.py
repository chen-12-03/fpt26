#!/usr/bin/env python3
"""Recompute split-role audit details for a public-only HLS sample run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scoring.run_p0_real_api_shard import (
    validate_evaluator,
    validate_submission,
)


def _load(path_text: str | None) -> dict[str, Any] | None:
    if not path_text:
        return None
    path = Path(path_text)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def audit(run_root: Path) -> dict[str, Any]:
    summary = json.loads(
        (run_root / "shard_summary.json").read_text(encoding="utf-8")
    )
    records: list[dict[str, Any]] = []
    outcomes: dict[str, int] = {}
    tokens = {
        "request_count": 0,
        "total_tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "failed_request_count": 0,
        "unreported_response_count": 0,
    }

    for record in summary["records"]:
        task_dir = Path(record["task_dir"])
        submission = _load(record["submission"]["report"])
        evaluator = _load(record["evaluator"]["report"])
        expected_grading_source = (
            "hidden" if (task_dir / "hidden").is_dir() else "public_fallback"
        )
        errors: list[str] = []
        if submission is None:
            errors.append("submission_report_missing")
        else:
            errors.extend(validate_submission(submission, record["task_id"]))
        if evaluator is None:
            if submission is not None and submission.get("status") == "completed":
                errors.append("evaluator_report_missing")
        else:
            errors.extend(
                validate_evaluator(
                    evaluator,
                    record["task_id"],
                    official_task=bool(record["official_task"]),
                    expected_grading_source=expected_grading_source,
                )
            )

        usage = ((submission or {}).get("llm") or {}).get("token_usage") or {}
        for key in tokens:
            value = usage.get(key, 0)
            if isinstance(value, int) and not isinstance(value, bool):
                tokens[key] += value

        outcome = str(record["outcome"])
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        gates = (submission or {}).get("gates") or {}
        evaluator_trace = (
            ((evaluator or {}).get("execution_trace") or {}).get(
                "grading_results"
            )
            or []
        )
        records.append(
            {
                "task_id": record["task_id"],
                "outcome": outcome,
                "expected_grading_source": expected_grading_source,
                "recomputed_audit_ok": not errors,
                "recomputed_audit_errors": sorted(set(errors)),
                "submission_status": (submission or {}).get("status"),
                "submission_stop_reason": (submission or {}).get(
                    "stop_reason"
                ),
                "submission_api_requests": usage.get("request_count"),
                "submission_total_tokens": usage.get("total_tokens"),
                "submission_credits_spent": (
                    ((submission or {}).get("budget") or {}).get("spent")
                ),
                "submission_frequency_mhz": (
                    (gates.get("frequency_100mhz") or {}).get(
                        "frequency_mhz"
                    )
                ),
                "evaluator_status": (evaluator or {}).get("status"),
                "evaluator_stop_reason": (evaluator or {}).get("stop_reason"),
                "evaluator_grading": (evaluator or {}).get("grading"),
                "evaluator_score": (
                    ((evaluator or {}).get("scoring") or {}).get("score")
                ),
                "evaluator_grading_results": [
                    {
                        key: item.get(key)
                        for key in ("stage", "ok", "reason", "error")
                    }
                    for item in evaluator_trace
                ],
            }
        )

    return {
        "schema_version": 1,
        "run_root": str(run_root),
        "source_shard_summary": str(run_root / "shard_summary.json"),
        "selected_task_count": summary["selected_task_count"],
        "recorded_task_count": summary["completed_record_count"],
        "outcome_counts": dict(sorted(outcomes.items())),
        "execution_source_stable_during_run": summary["execution_source"][
            "stable"
        ],
        "recomputed_audit_error_task_count": sum(
            not record["recomputed_audit_ok"] for record in records
        ),
        "model_and_api": tokens,
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    report = audit(args.run_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"public sample audit: tasks={report['recorded_task_count']} "
        f"outcomes={report['outcome_counts']} "
        f"audit_errors={report['recomputed_audit_error_task_count']} "
        f"api_requests={report['model_and_api']['request_count']} "
        f"tokens={report['model_and_api']['total_tokens']} "
        f"output={args.output}"
    )
    for record in report["records"]:
        if (
            record["outcome"] != "completed"
            or not record["recomputed_audit_ok"]
        ):
            print(
                f"{record['task_id']}: outcome={record['outcome']} "
                f"audit_ok={record['recomputed_audit_ok']} "
                f"submission={record['submission_status']}/"
                f"{record['submission_stop_reason']} "
                f"evaluator={record['evaluator_status']}/"
                f"{record['evaluator_stop_reason']} "
                f"errors={record['recomputed_audit_errors']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
