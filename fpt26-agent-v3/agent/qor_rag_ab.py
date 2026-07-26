#!/usr/bin/env python3
"""Compare fixed-task baseline and candidate runs for Phase 2A acceptance.

Evaluator reports are read only for offline A/B metrics.  This module never
creates knowledge entries; runtime case promotion is isolated in
``agent.qor_rag_curate`` and rejects evaluator paths.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class TaskRunPair:
    submission: Mapping[str, Any] | None
    evaluator: Mapping[str, Any] | None
    submission_path: Path | None = None
    evaluator_path: Path | None = None
    submission_error: str | None = None
    evaluator_error: str | None = None


def compare_runs(
    baseline_roots: Sequence[Path],
    candidate_roots: Sequence[Path],
    task_list: Path,
) -> dict[str, Any]:
    tasks = _load_task_ids(task_list)
    baseline = _discover_runs(baseline_roots, tasks)
    candidate = _discover_runs(candidate_roots, tasks)
    baseline_metrics = _aggregate(baseline, tasks)
    candidate_metrics = _aggregate(candidate, tasks)

    baseline_correct = {
        task_id
        for task_id, metrics in baseline_metrics["tasks"].items()
        if metrics["valid"] is True
    }
    preserved = {
        task_id
        for task_id in baseline_correct
        if candidate_metrics["tasks"][task_id]["valid"] is True
    }
    correctness_rate = (
        len(preserved) / len(baseline_correct)
        if baseline_correct
        else 0.0
    )
    q_hw_change = _relative_change(
        baseline_metrics["q_hw_geomean"],
        candidate_metrics["q_hw_geomean"],
    )
    acceleration_change = _relative_change(
        baseline_metrics["acceleration_geomean"],
        candidate_metrics["acceleration_geomean"],
    )
    token_change = _relative_change(
        baseline_metrics["mean_tokens_per_task"],
        candidate_metrics["mean_tokens_per_task"],
    )
    credit_change = _relative_change(
        baseline_metrics["mean_credits_per_task"],
        candidate_metrics["mean_credits_per_task"],
    )
    request_change = _relative_change(
        baseline_metrics["mean_requests_per_task"],
        candidate_metrics["mean_requests_per_task"],
    )
    success_rate_change = _relative_change(
        baseline_metrics["success_rate"],
        candidate_metrics["success_rate"],
    )
    waste_change = _relative_change(
        baseline_metrics["wasted_attempts"],
        candidate_metrics["wasted_attempts"],
    )
    waste_available = (
        baseline_metrics["optimization_metrics_complete"]
        and candidate_metrics["optimization_metrics_complete"]
    )

    gates = {
        "fixed_task_count_12_to_20": 12 <= len(tasks) <= 20,
        "all_reports_present": (
            not baseline_metrics["missing"]
            and not candidate_metrics["missing"]
        ),
        "correctness_preserved_100pct": correctness_rate == 1.0,
        "scorable_count_not_lower": (
            candidate_metrics["scorable_count"]
            >= baseline_metrics["scorable_count"]
        ),
        "q_hw_geomean_improves_1pct": (
            q_hw_change is not None and q_hw_change >= 0.01
        ),
        "acceleration_geomean_improves_5pct": (
            acceleration_change is not None
            and acceleration_change >= 0.05
        ),
        "wasted_attempts_reduce_20pct": (
            waste_available
            and (
                (
                    waste_change is not None
                    and waste_change <= -0.20
                )
                if baseline_metrics["wasted_attempts"] > 0
                else candidate_metrics["wasted_attempts"] == 0
            )
        ),
        "mean_tokens_increase_at_most_10pct": (
            token_change is not None and token_change <= 0.10
        ),
    }
    return {
        "schema_version": 2,
        "provenance": {
            "baseline_roots": [str(root) for root in baseline_roots],
            "candidate_roots": [str(root) for root in candidate_roots],
            "overlay_semantics": (
                "later roots replace earlier reports for the same task and role"
            ),
            "report_roles": ["submission", "evaluator"],
        },
        "task_list": str(task_list),
        "task_count": len(tasks),
        "tasks": tasks,
        "baseline": baseline_metrics,
        "candidate": candidate_metrics,
        "comparison": {
            "baseline_correct_count": len(baseline_correct),
            "correctness_preserved_count": len(preserved),
            "correctness_preservation_rate": round(correctness_rate, 6),
            "q_hw_geomean_relative_change": q_hw_change,
            "acceleration_geomean_relative_change": acceleration_change,
            "wasted_attempts_relative_change": waste_change,
            "mean_tokens_relative_change": token_change,
            "mean_requests_relative_change_monitor_only": request_change,
            "mean_credits_relative_change_monitor_only": credit_change,
            "success_rate_relative_change_monitor_only": success_rate_change,
        },
        "gates": gates,
        "passed": all(gates.values()),
    }


def _load_task_ids(path: Path) -> list[str]:
    tasks = []
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        task_id = line.strip()
        if not task_id or task_id.startswith("#"):
            continue
        if task_id in seen:
            raise ValueError(f"duplicate task id in fixed set: {task_id}")
        seen.add(task_id)
        tasks.append(task_id)
    return tasks


def _discover_runs(
    roots: Sequence[Path], tasks: Sequence[str]
) -> dict[str, TaskRunPair]:
    found: dict[str, dict[str, tuple[Mapping[str, Any], Path]]] = {
        task_id: {} for task_id in tasks
    }
    errors: dict[str, dict[str, tuple[str, Path]]] = {
        task_id: {} for task_id in tasks
    }
    wanted = set(tasks)
    for root in roots:
        found_in_root: set[tuple[str, str]] = set()
        for path in sorted(root.rglob("run_report.json")):
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                inferred = _infer_report_identity(path, wanted)
                if inferred is not None:
                    task_id, role = inferred
                    errors[task_id][role] = (
                        f"{type(exc).__name__}: {exc}",
                        path,
                    )
                continue
            if not isinstance(report, Mapping):
                continue
            task_id = str(report.get("task_id", ""))
            if task_id not in wanted:
                continue
            role = _report_role(path, report)
            if role not in {"submission", "evaluator"}:
                continue
            key = (task_id, role)
            if key in found_in_root:
                raise ValueError(
                    f"ambiguous {role} report for {task_id}; "
                    "use roots containing one final attempt per task"
                )
            found_in_root.add(key)
            # Later roots are explicit retry overlays and replace the same
            # task/role from an earlier full or sharded run.
            found[task_id][role] = (report, path)
    return {
        task_id: TaskRunPair(
            submission=(
                roles["submission"][0] if "submission" in roles else None
            ),
            evaluator=roles["evaluator"][0] if "evaluator" in roles else None,
            submission_path=(
                roles["submission"][1] if "submission" in roles else None
            ),
            evaluator_path=(
                roles["evaluator"][1] if "evaluator" in roles else None
            ),
            submission_error=(
                errors[task_id]["submission"][0]
                if "submission" in errors[task_id]
                and "submission" not in roles
                else None
            ),
            evaluator_error=(
                errors[task_id]["evaluator"][0]
                if "evaluator" in errors[task_id]
                and "evaluator" not in roles
                else None
            ),
        )
        for task_id, roles in found.items()
    }


def _report_role(path: Path, report: Mapping[str, Any]) -> str:
    parts = {part.lower() for part in path.parts}
    if "evaluator" in parts:
        return "evaluator"
    if "submission" in parts:
        return "submission"
    role = str(report.get("run_role", "") or "").lower()
    if role in {"submission", "evaluator"}:
        return role
    return "evaluator" if report.get("scoring") else "submission"


def _infer_report_identity(
    path: Path, wanted: set[str]
) -> tuple[str, str] | None:
    role = _report_role_from_path(path)
    if role is None:
        return None
    task_id = path.parent.name
    if task_id in wanted:
        return task_id, role
    parts = list(path.parts)
    try:
        role_index = [part.lower() for part in parts].index(role)
    except ValueError:
        return None
    if role_index + 1 < len(parts) and parts[role_index + 1] in wanted:
        return parts[role_index + 1], role
    return None


def _report_role_from_path(path: Path) -> str | None:
    parts = {part.lower() for part in path.parts}
    if "evaluator" in parts:
        return "evaluator"
    if "submission" in parts:
        return "submission"
    return None


def _aggregate(
    runs: Mapping[str, TaskRunPair], tasks: Sequence[str]
) -> dict[str, Any]:
    per_task: dict[str, dict[str, Any]] = {}
    q_hw_values: list[float] = []
    acceleration_values: list[float] = []
    tokens: list[float] = []
    prompt_tokens: list[float] = []
    completion_tokens: list[float] = []
    requests: list[float] = []
    credits: list[float] = []
    missing: list[str] = []
    scorable = 0
    success_count = 0
    failure_reason_counts: dict[str, int] = {}
    report_error_counts: dict[str, int] = {}
    wasted_attempts = 0
    optimization_complete = True

    for task_id in tasks:
        pair = runs[task_id]
        scoring = (
            pair.evaluator.get("scoring", {})
            if isinstance(pair.evaluator, Mapping)
            and isinstance(pair.evaluator.get("scoring"), Mapping)
            else {}
        )
        valid = scoring.get("valid")
        score = _number(scoring.get("score"))
        q_hw = _number(scoring.get("q_hw"))
        acceleration = _number(scoring.get("latency_ratio"))
        if valid is True and q_hw is not None and q_hw > 0:
            q_hw_values.append(q_hw)
            scorable += 1
        if valid is True and acceleration is not None and acceleration > 0:
            acceleration_values.append(acceleration)

        token_value = None
        prompt_token_value = None
        completion_token_value = None
        request_value = None
        credit_value = None
        waste_value = None
        if isinstance(pair.submission, Mapping):
            llm = pair.submission.get("llm", {})
            usage = (
                llm.get("token_usage", {})
                if isinstance(llm, Mapping)
                and isinstance(llm.get("token_usage"), Mapping)
                else {}
            )
            token_value = _number(usage.get("total_tokens"))
            prompt_token_value = _number(usage.get("prompt_tokens"))
            completion_token_value = _number(usage.get("completion_tokens"))
            request_value = _number(usage.get("request_count"))
            budget = pair.submission.get("budget", {})
            if isinstance(budget, Mapping):
                credit_value = _number(budget.get("spent"))
            optimization = pair.submission.get("optimization_metrics")
            if isinstance(optimization, Mapping):
                waste_value = _wasted_attempts(optimization)
                wasted_attempts += waste_value
            else:
                optimization_complete = False
        else:
            optimization_complete = False

        if token_value is not None:
            tokens.append(token_value)
        if prompt_token_value is not None:
            prompt_tokens.append(prompt_token_value)
        if completion_token_value is not None:
            completion_tokens.append(completion_token_value)
        if request_value is not None:
            requests.append(request_value)
        if credit_value is not None:
            credits.append(credit_value)
        if pair.submission is None or pair.evaluator is None:
            missing.append(task_id)
        task_success = (
            valid is True
            and pair.submission is not None
            and pair.evaluator is not None
            and pair.submission_error is None
            and pair.evaluator_error is None
        )
        if task_success:
            success_count += 1
            failure_reason = None
        else:
            failure_reason = _failure_reason(pair)
            failure_reason_counts[failure_reason] = (
                failure_reason_counts.get(failure_reason, 0) + 1
            )
        for error_key, error_value in (
            ("submission_error", pair.submission_error),
            ("evaluator_error", pair.evaluator_error),
        ):
            if error_value:
                report_error_counts[error_key] = (
                    report_error_counts.get(error_key, 0) + 1
                )
        per_task[task_id] = {
            "submission_status": _report_status(pair.submission),
            "evaluator_status": _report_status(pair.evaluator),
            "success": task_success,
            "failure_reason": failure_reason,
            "submission_report_error": pair.submission_error,
            "evaluator_report_error": pair.evaluator_error,
            "valid": valid,
            "score": score,
            "q_hw": q_hw,
            "acceleration": acceleration,
            "tokens": token_value,
            "prompt_tokens": prompt_token_value,
            "completion_tokens": completion_token_value,
            "requests": request_value,
            "credits": credit_value,
            "wasted_attempts": waste_value,
            "submission_report": (
                str(pair.submission_path) if pair.submission_path else None
            ),
            "evaluator_report": (
                str(pair.evaluator_path) if pair.evaluator_path else None
            ),
        }

    return {
        "task_count": len(tasks),
        "success_count": success_count,
        "success_rate": (
            round(success_count / len(tasks), 6) if tasks else None
        ),
        "failure_reason_counts": dict(sorted(failure_reason_counts.items())),
        "report_error_counts": dict(sorted(report_error_counts.items())),
        "scorable_count": scorable,
        "q_hw_geomean": _geomean(q_hw_values),
        "acceleration_geomean": _geomean(acceleration_values),
        "mean_tokens_per_task": (
            round(statistics.fmean(tokens), 6) if len(tokens) == len(tasks) else None
        ),
        "median_tokens_per_task": (
            round(statistics.median(tokens), 6)
            if len(tokens) == len(tasks)
            else None
        ),
        "mean_prompt_tokens_per_task": (
            round(statistics.fmean(prompt_tokens), 6)
            if len(prompt_tokens) == len(tasks)
            else None
        ),
        "mean_completion_tokens_per_task": (
            round(statistics.fmean(completion_tokens), 6)
            if len(completion_tokens) == len(tasks)
            else None
        ),
        "mean_requests_per_task": (
            round(statistics.fmean(requests), 6)
            if len(requests) == len(tasks)
            else None
        ),
        "mean_credits_per_task": (
            round(statistics.fmean(credits), 6)
            if len(credits) == len(tasks)
            else None
        ),
        "wasted_attempts": wasted_attempts,
        "optimization_metrics_complete": optimization_complete,
        "missing": sorted(set(missing)),
        "tasks": per_task,
    }


def _report_status(report: Mapping[str, Any] | None) -> str | None:
    if not isinstance(report, Mapping):
        return None
    status = report.get("status")
    return str(status) if status is not None else None


def _failure_reason(pair: TaskRunPair) -> str:
    if pair.submission is None:
        if pair.submission_error:
            return "submission_report_unreadable_or_invalid"
        return "missing_submission_report"
    if pair.evaluator is None:
        if pair.evaluator_error:
            return "evaluator_report_unreadable_or_invalid"
        return "missing_evaluator_report"
    for report in (pair.evaluator, pair.submission):
        if not isinstance(report, Mapping):
            continue
        reason = report.get("stop_reason") or report.get("failure_reason")
        if reason:
            return str(reason)
        status = report.get("status")
        if status and status != "completed":
            return str(status)
    scoring = (
        pair.evaluator.get("scoring", {})
        if isinstance(pair.evaluator, Mapping)
        and isinstance(pair.evaluator.get("scoring"), Mapping)
        else {}
    )
    if scoring.get("valid") is not True:
        return "invalid_scoring"
    return "unknown"


def _wasted_attempts(optimization: Mapping[str, Any]) -> int:
    count = 0
    for key in (
        "semantic_duplicate_skips",
        "semantic_current_best_skips",
        "cross_strategy_duplicate_skips",
        "strategy_contract_rejections",
        "ii_resource_intent_rejections",
    ):
        value = optimization.get(key, 0)
        if isinstance(value, int) and value > 0:
            count += value
    failures = optimization.get("optimization_failures", [])
    if isinstance(failures, list):
        for failure in failures:
            if isinstance(failure, Mapping):
                repetitions = failure.get("repetition_count", 1)
                count += repetitions if isinstance(repetitions, int) else 1
    return count


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _geomean(values: Sequence[float]) -> float | None:
    if not values or any(value <= 0 for value in values):
        return None
    return round(math.exp(statistics.fmean(math.log(value) for value in values)), 9)


def _relative_change(
    baseline: float | None, candidate: float | None
) -> float | None:
    if baseline is None or candidate is None or baseline == 0:
        return None
    return round(candidate / baseline - 1.0, 9)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", action="append", type=Path, required=True)
    parser.add_argument("--candidate-root", action="append", type=Path, required=True)
    parser.add_argument(
        "--task-list",
        type=Path,
        default=Path("fpt26-agent-v3/evals/qor_rag_fixed_correct_tasks.txt"),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = compare_runs(
        args.baseline_root, args.candidate_root, args.task_list
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
