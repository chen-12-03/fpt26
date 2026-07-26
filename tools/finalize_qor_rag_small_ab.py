#!/usr/bin/env python3
"""Finalize a QoR-RAG 1-3 task small-sample A/B report.

This script does not run Vitis, call an LLM, or update the execution freeze.
It only aggregates already-produced split-role raw roots and labels the output
as small-sample measured evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from agent.qor_rag_ab import compare_runs


DEFAULT_PLAN = Path(
    "fpt26-agent-v3/scoring/reports/phase2f_qor_rag_small_ab_plan_20260725.json"
)
DEFAULT_TASK_LIST = Path(
    "fpt26-agent-v3/evals/qor_rag_small_ab_priority_tasks_latest.txt"
)
DEFAULT_OUTPUT = Path(
    "fpt26-agent-v3/scoring/reports/"
    "phase2f_qor_rag_small_ab_measured_20260725.json"
)


def build_measured_report(
    plan: Mapping[str, Any],
    *,
    plan_path: Path,
    baseline_roots: Sequence[Path],
    candidate_roots: Sequence[Path],
    task_list: Path,
) -> dict[str, Any]:
    selected_task_ids = _selected_task_ids(plan)
    if not 1 <= len(selected_task_ids) <= 3:
        raise ValueError("small A/B measured report must stay in the 1-3 task range")
    _validate_plan_guardrails(plan)

    listed_task_ids = _load_task_ids(task_list)
    if listed_task_ids != selected_task_ids:
        raise ValueError(
            "task list does not match selected plan tasks: "
            f"{listed_task_ids!r} != {selected_task_ids!r}"
        )
    _require_existing_roots("baseline", baseline_roots)
    _require_existing_roots("candidate", candidate_roots)

    raw = compare_runs(baseline_roots, candidate_roots, task_list)
    baseline = raw["baseline"]
    candidate = raw["candidate"]
    report_errors = bool(
        baseline.get("report_error_counts")
        or candidate.get("report_error_counts")
    )
    missing = bool(baseline.get("missing") or candidate.get("missing"))
    status = "measured" if not report_errors and not missing else "audit_incomplete"

    return {
        "schema_version": 1,
        "purpose": "phase2f_generalized_qor_rag_small_sample_ab_measured",
        "status": status,
        "evidence_level": (
            "small_sample_measured"
            if status == "measured"
            else "small_sample_audit_incomplete"
        ),
        "source_plan": str(plan_path),
        "run_label": plan.get("run_label"),
        "task_list": str(task_list),
        "task_count": len(selected_task_ids),
        "tasks": selected_task_ids,
        "guardrails": {
            "full199_allowed": False,
            "execution_freeze_update_allowed": False,
            "max_real_api_vitis_tasks": 3,
        },
        "formal_ab_acceptance": {
            "applicable": False,
            "reason": (
                "small-sample evidence has fewer than the 12 tasks required "
                "by the formal QoR-RAG A/B gate"
            ),
            "raw_compare_passed": raw["passed"],
            "raw_gates": raw["gates"],
        },
        "small_sample_summary": _small_sample_summary(raw),
        "raw_compare": raw,
        "completion_boundary": {
            "may_claim_qor_repair": (
                status == "measured"
                and candidate.get("success_rate") == 1.0
                and _positive_or_zero(
                    raw["comparison"].get("q_hw_geomean_relative_change")
                )
            ),
            "may_update_execution_freeze_json": False,
        },
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
    max_tasks = policy.get("max_real_api_vitis_tasks")
    if max_tasks != 3:
        raise ValueError("plan must cap real API/Vitis tasks at 3")


def _load_task_ids(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _require_existing_roots(label: str, roots: Sequence[Path]) -> None:
    if not roots:
        raise ValueError(f"at least one {label} root is required")
    missing = [str(root) for root in roots if not root.exists()]
    if missing:
        raise FileNotFoundError(
            f"{label} root does not exist; run the small A/B lane first: "
            + ", ".join(missing)
        )


def _small_sample_summary(raw: Mapping[str, Any]) -> dict[str, Any]:
    baseline = raw["baseline"]
    candidate = raw["candidate"]
    comparison = raw["comparison"]
    return {
        "baseline_success_rate": baseline.get("success_rate"),
        "candidate_success_rate": candidate.get("success_rate"),
        "baseline_mean_tokens_per_task": baseline.get("mean_tokens_per_task"),
        "candidate_mean_tokens_per_task": candidate.get("mean_tokens_per_task"),
        "baseline_mean_prompt_tokens_per_task": baseline.get(
            "mean_prompt_tokens_per_task"
        ),
        "candidate_mean_prompt_tokens_per_task": candidate.get(
            "mean_prompt_tokens_per_task"
        ),
        "baseline_mean_completion_tokens_per_task": baseline.get(
            "mean_completion_tokens_per_task"
        ),
        "candidate_mean_completion_tokens_per_task": candidate.get(
            "mean_completion_tokens_per_task"
        ),
        "baseline_mean_requests_per_task": baseline.get("mean_requests_per_task"),
        "candidate_mean_requests_per_task": candidate.get("mean_requests_per_task"),
        "baseline_q_hw_geomean": baseline.get("q_hw_geomean"),
        "candidate_q_hw_geomean": candidate.get("q_hw_geomean"),
        "baseline_acceleration_geomean": baseline.get("acceleration_geomean"),
        "candidate_acceleration_geomean": candidate.get("acceleration_geomean"),
        "q_hw_relative_change": comparison.get("q_hw_geomean_relative_change"),
        "acceleration_relative_change": comparison.get(
            "acceleration_geomean_relative_change"
        ),
        "mean_tokens_relative_change": comparison.get(
            "mean_tokens_relative_change"
        ),
        "mean_requests_relative_change": comparison.get(
            "mean_requests_relative_change_monitor_only"
        ),
        "baseline_failure_reason_counts": baseline.get("failure_reason_counts"),
        "candidate_failure_reason_counts": candidate.get("failure_reason_counts"),
        "baseline_report_error_counts": baseline.get("report_error_counts"),
        "candidate_report_error_counts": candidate.get("report_error_counts"),
    }


def _positive_or_zero(value: Any) -> bool:
    return isinstance(value, (int, float)) and value >= 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--baseline-root", action="append", type=Path, required=True)
    parser.add_argument("--candidate-root", action="append", type=Path, required=True)
    parser.add_argument("--task-list", type=Path, default=DEFAULT_TASK_LIST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    report = build_measured_report(
        plan,
        plan_path=args.plan,
        baseline_roots=args.baseline_root,
        candidate_roots=args.candidate_root,
        task_list=args.task_list,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "measured" else 2


if __name__ == "__main__":
    sys.exit(main())
