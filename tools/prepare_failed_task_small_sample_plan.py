#!/usr/bin/env python3
"""Prepare a non-executed small-sample plan for failed-task recovery.

The output is an execution plan only. It does not launch Vitis, call an LLM,
or update the execution freeze.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_TRIAGE_REPORT = Path(
    "fpt26-agent-v3/scoring/reports/phase2f_offline_agent_triage_20260725.json"
)
DEFAULT_OUTPUT = Path(
    "fpt26-agent-v3/scoring/reports/"
    "phase2f_failed_task_small_sample_plan_20260725.json"
)
DEFAULT_TASK_LIST_OUTPUT = Path(
    "fpt26-agent-v3/evals/failed_task_small_sample_priority_tasks_latest.txt"
)


def build_plan(
    triage_report: Mapping[str, Any],
    *,
    triage_report_path: Path,
    task_list_output: Path,
    max_tasks: int = 3,
) -> dict[str, Any]:
    if max_tasks < 1 or max_tasks > 3:
        raise ValueError("max_tasks must stay in the user-approved 1-3 range")

    objective = _mapping(triage_report.get("phase2f_objective_status"))
    failed = _mapping(objective.get("failed_task_success_rate_offline"))
    suggested = failed.get("suggested_failure_small_sample_tasks")
    if not isinstance(suggested, list) or not suggested:
        raise ValueError("triage report missing suggested failure small samples")
    selected_ids = [
        task_id for task_id in suggested if isinstance(task_id, str) and task_id
    ][:max_tasks]
    if not selected_ids:
        raise ValueError("no valid failure task IDs selected")

    records = _remaining_failure_records(triage_report)
    selected = [
        _task_plan_record(task_id, records.get(task_id))
        for task_id in selected_ids
    ]
    task_flags = " ".join(f"--task-id {task_id}" for task_id in selected_ids)
    task_list_text = "\n".join(selected_ids) + "\n"
    run_root = "runs/phase2f_failed_task_small_sample_current_20260725"
    measured_report = (
        "fpt26-agent-v3/scoring/reports/"
        "phase2f_failed_task_small_sample_measured_20260725.json"
    )
    raw_audit_report = (
        "fpt26-agent-v3/scoring/reports/"
        "phase2f_failed_task_small_sample_raw_audit_20260725.json"
    )
    plan_report = (
        "fpt26-agent-v3/scoring/reports/"
        "phase2f_failed_task_small_sample_plan_20260725.json"
    )

    return {
        "schema_version": 1,
        "purpose": "phase2f_failed_task_success_rate_small_sample_plan",
        "status": "not_executed",
        "evidence_level": "execution_plan_only",
        "source_triage_report": str(triage_report_path),
        "task_list_output": str(task_list_output),
        "task_list_text": task_list_text,
        "selected_task_count": len(selected),
        "selected_tasks": selected,
        "offline_context": {
            "post_quarantine_success_rate": failed.get(
                "post_quarantine_success_rate"
            ),
            "remaining_failure_count": failed.get("remaining_failure_count"),
            "measured_success_rate_repair_proven": failed.get(
                "measured_success_rate_repair_proven"
            ),
        },
        "sample_policy": {
            "max_real_api_vitis_tasks": 3,
            "planned_task_count": len(selected),
            "full199_allowed": False,
            "execution_freeze_update_allowed": False,
            "measured_report_required": True,
        },
        "guardrails": [
            "Do not run full199 for this plan.",
            "Do not update fpt26-agent-v3/execution-freeze.json from this plan.",
            "Run at most 1-3 real API/Vitis tasks.",
            "Write measured output under fpt26-agent-v3/scoring/reports/.",
            "Label measured output as small-sample evidence, not acceptance.",
        ],
        "run": {
            "description": (
                "Current agent recheck for representative remaining failures "
                "after offline triage/quarantine."
            ),
            "env": {"PYTHONPATH": "fpt26-agent-v3:."},
            "output_root": run_root,
            "command": (
                "PYTHONPATH=fpt26-agent-v3:. "
                "python3 -m scoring.run_p0_real_api_shard "
                "--task-root tasks "
                f"--output-root {run_root} "
                "--shard-index 0 --shard-count 1 "
                f"{task_flags}"
            ),
        },
        "audit": {
            "output_report": measured_report,
            "command": (
                "PYTHONPATH=fpt26-agent-v3:. "
                "python3 tools/finalize_failed_task_small_sample.py "
                f"--plan {plan_report} "
                f"--run-root {run_root} "
                f"--output {measured_report}"
            ),
            "raw_audit_output_report": raw_audit_report,
            "raw_audit_command": (
                "PYTHONPATH=fpt26-agent-v3:. "
                "python3 tools/audit_public_hls_sample.py "
                f"--run-root {run_root} "
                f"--output {raw_audit_report}"
            ),
        },
        "required_measured_fields": [
            "task_id",
            "outcome",
            "submission status and stop_reason",
            "evaluator status and stop_reason",
            "score, frequency, interface/frequency/resource gate evidence",
            "request_count, prompt_tokens, completion_tokens, total_tokens",
            "credits_spent",
            "recomputed audit errors",
        ],
        "promotion_policy": {
            "may_claim_success_rate_repair": (
                "only after measured small sample improves or explains the "
                "representative failures and a later fresh acceptance confirms it"
            ),
            "may_update_execution_freeze_json": (
                "false for small samples; requires explicit fresh full199 "
                "acceptance"
            ),
        },
    }


def _remaining_failure_records(
    triage_report: Mapping[str, Any]
) -> dict[str, Mapping[str, Any]]:
    post = _mapping(triage_report.get("post_quarantine_failures"))
    records = post.get("remaining_failures")
    if not isinstance(records, list):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        task_id = record.get("task_id")
        if isinstance(task_id, str):
            result[task_id] = record
    return result


def _task_plan_record(
    task_id: str, record: Mapping[str, Any] | None
) -> dict[str, Any]:
    record = record or {}
    gate = _mapping(record.get("gate_evidence"))
    submission = _mapping(gate.get("submission"))
    final_hw = _mapping(gate.get("final_hardware"))
    token_usage = _mapping(submission.get("token_usage"))
    return {
        "task_id": task_id,
        "family": record.get("family"),
        "prior_failure_reason": record.get("reason"),
        "triage_class": record.get("triage_class"),
        "prior_submission_status": submission.get("status"),
        "prior_submission_stop_reason": submission.get("stop_reason"),
        "prior_token_usage": {
            key: token_usage.get(key)
            for key in (
                "request_count",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
            )
        },
        "prior_frequency_mhz": _get(
            submission, "frequency_100mhz", "frequency_mhz"
        ),
        "prior_interface_ok": _get(submission, "interface", "ok"),
        "prior_final_hardware": {
            "stage": final_hw.get("stage"),
            "clock_period_ns": final_hw.get("clock_period_ns"),
            "frequency_mhz": final_hw.get("frequency_mhz"),
            "latency_worst": final_hw.get("latency_worst"),
            "interval_max": final_hw.get("interval_max"),
        },
        "required_evidence": (
            "fresh split-role real API/Vitis recheck for this representative "
            "failure task, followed by measured audit report"
        ),
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _get(mapping: Mapping[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--triage-report", type=Path, default=DEFAULT_TRIAGE_REPORT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--task-list-output", type=Path, default=DEFAULT_TASK_LIST_OUTPUT
    )
    parser.add_argument("--max-tasks", type=int, default=3)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    triage = json.loads(args.triage_report.read_text(encoding="utf-8"))
    plan = build_plan(
        triage,
        triage_report_path=args.triage_report,
        task_list_output=args.task_list_output,
        max_tasks=args.max_tasks,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.task_list_output.parent.mkdir(parents=True, exist_ok=True)
    args.task_list_output.write_text(plan["task_list_text"], encoding="utf-8")
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
