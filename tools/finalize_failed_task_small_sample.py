#!/usr/bin/env python3
"""Finalize a failed-task 1-3 task small-sample report.

This script does not run Vitis, call an LLM, or update the execution freeze.
It audits an already-produced split-role run root and wraps the result as
small-sample measured evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.audit_public_hls_sample import audit


DEFAULT_PLAN = Path(
    "fpt26-agent-v3/scoring/reports/"
    "phase2f_failed_task_small_sample_plan_20260725.json"
)
DEFAULT_OUTPUT = Path(
    "fpt26-agent-v3/scoring/reports/"
    "phase2f_failed_task_small_sample_measured_20260725.json"
)


def build_measured_report(
    plan: Mapping[str, Any],
    *,
    plan_path: Path,
    run_root: Path,
) -> dict[str, Any]:
    selected_task_ids = _selected_task_ids(plan)
    if not 1 <= len(selected_task_ids) <= 3:
        raise ValueError("failed-task measured report must stay in the 1-3 task range")
    _validate_plan_guardrails(plan)
    if not run_root.exists():
        raise FileNotFoundError(
            f"run root does not exist; run the failed-task sample first: {run_root}"
        )

    raw = audit(run_root)
    record_ids = [
        record.get("task_id")
        for record in raw.get("records", [])
        if isinstance(record, Mapping)
    ]
    if Counter(record_ids) != Counter(selected_task_ids):
        raise ValueError(
            "run root task set does not match selected plan tasks: "
            f"{record_ids!r} != {selected_task_ids!r}"
        )
    raw = _order_raw_records(raw, selected_task_ids)
    audit_errors = raw.get("recomputed_audit_error_task_count", 0)
    status = "measured" if audit_errors == 0 else "audit_incomplete"

    return {
        "schema_version": 1,
        "purpose": "phase2f_failed_task_success_rate_small_sample_measured",
        "status": status,
        "evidence_level": (
            "small_sample_measured"
            if status == "measured"
            else "small_sample_audit_incomplete"
        ),
        "source_plan": str(plan_path),
        "run_root": str(run_root),
        "task_count": len(selected_task_ids),
        "tasks": selected_task_ids,
        "guardrails": {
            "full199_allowed": False,
            "execution_freeze_update_allowed": False,
            "max_real_api_vitis_tasks": 3,
        },
        "acceptance_boundary": {
            "is_full199_acceptance": False,
            "may_update_execution_freeze_json": False,
            "may_claim_global_success_rate_repair": False,
            "reason": (
                "1-3 task measured recheck is representative evidence only; "
                "global success-rate repair requires later fresh acceptance"
            ),
        },
        "small_sample_summary": _small_sample_summary(raw),
        "raw_audit": raw,
    }


def _selected_task_ids(plan: Mapping[str, Any]) -> list[str]:
    tasks = plan.get("selected_tasks")
    if not isinstance(tasks, list):
        raise ValueError("plan missing selected_tasks")
    selected = []
    for item in tasks:
        if not isinstance(item, Mapping):
            raise ValueError("selected_tasks must contain objects")
        task_id = item.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("selected task missing task_id")
        selected.append(task_id)
    return selected


def _validate_plan_guardrails(plan: Mapping[str, Any]) -> None:
    policy = plan.get("sample_policy")
    if not isinstance(policy, Mapping):
        raise ValueError("plan missing sample_policy")
    if policy.get("full199_allowed") is not False:
        raise ValueError("plan must explicitly disallow full199")
    if policy.get("execution_freeze_update_allowed") is not False:
        raise ValueError("plan must explicitly disallow execution-freeze updates")
    if policy.get("max_real_api_vitis_tasks") != 3:
        raise ValueError("plan must cap real API/Vitis tasks at 3")


def _order_raw_records(
    raw: Mapping[str, Any], selected_task_ids: Sequence[str]
) -> dict[str, Any]:
    """Return audit payload with records ordered by the explicit plan."""

    records = [
        record for record in raw.get("records", []) if isinstance(record, Mapping)
    ]
    by_task_id = {str(record.get("task_id")): dict(record) for record in records}
    ordered = [by_task_id[task_id] for task_id in selected_task_ids]
    result = dict(raw)
    result["records"] = ordered
    return result


def _small_sample_summary(raw: Mapping[str, Any]) -> dict[str, Any]:
    selected = _num(raw.get("selected_task_count"))
    outcomes = _mapping(raw.get("outcome_counts"))
    completed = _num(outcomes.get("completed")) or 0.0
    tokens = _mapping(raw.get("model_and_api"))
    failure_reason_counts: dict[str, int] = {}
    scores: list[float] = []
    for record in raw.get("records", []):
        if not isinstance(record, Mapping):
            continue
        _append_number(scores, record.get("evaluator_score"))
        if record.get("outcome") == "completed":
            continue
        reason = (
            record.get("submission_stop_reason")
            or record.get("evaluator_stop_reason")
            or record.get("outcome")
            or "unknown"
        )
        failure_reason_counts[str(reason)] = failure_reason_counts.get(
            str(reason), 0
        ) + 1
    return {
        "task_count": selected,
        "completed": completed,
        "failed": selected - completed if selected is not None else None,
        "success_rate": _ratio(completed, selected),
        "outcome_counts": outcomes,
        "failure_reason_counts": dict(sorted(failure_reason_counts.items())),
        "recomputed_audit_error_task_count": raw.get(
            "recomputed_audit_error_task_count"
        ),
        "total_requests": tokens.get("request_count"),
        "total_tokens": tokens.get("total_tokens"),
        "prompt_tokens": tokens.get("prompt_tokens"),
        "completion_tokens": tokens.get("completion_tokens"),
        "mean_requests_per_task": _ratio(_num(tokens.get("request_count")), selected),
        "mean_tokens_per_task": _ratio(_num(tokens.get("total_tokens")), selected),
        "mean_score_completed_tasks": _mean(scores),
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _append_number(values: list[float], value: Any) -> None:
    numeric = _num(value)
    if numeric is not None:
        values.append(numeric)


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator, 6)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    report = build_measured_report(
        plan,
        plan_path=args.plan,
        run_root=args.run_root,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "measured" else 2


if __name__ == "__main__":
    sys.exit(main())
