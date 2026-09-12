#!/usr/bin/env python3
"""Summarize a Track-A v4 campaign and an optional retry pass.

The script is intentionally read-only.  Some run artifacts are owned by the
Docker user, so the reproducible invocation is normally:

    docker run --rm -v "$PWD:/workspace:ro" -w /workspace \
      fpt26-agent-v3:latest python3 tools/summarize_track_a_v4_campaign.py \
      --base-run runs/... [--retry-run runs/...]
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


CATEGORY_CODES = {
    "cg": "code_generation",
    "cr": "compile_repair",
    "fr": "functional_repair",
    "qo": "qor_optimization",
    "sr": "synthesis_repair",
    "xr": "structural_repair",
}


def load_records(run_root: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    summaries = sorted(run_root.glob("shard_*/shard_summary.json"))
    if not summaries:
        raise ValueError(f"no shard summaries under {run_root}")
    for summary in summaries:
        payload = json.loads(summary.read_text())
        for record in payload["records"]:
            task_id = record["task_id"]
            if task_id in records:
                raise ValueError(f"duplicate task record: {task_id}")
            records[task_id] = record
    return records


def category_of(task_id: str) -> str:
    code = task_id.split("_")[1]
    return CATEGORY_CODES[code]


def local_report_path(container_path: str) -> Path:
    prefix = "/workspace/"
    return Path(container_path[len(prefix) :] if container_path.startswith(prefix) else container_path)


def aggregate_api(records: list[dict[str, Any]]) -> dict[str, Any]:
    apis = [record.get("submission", {}).get("api", {}) for record in records]
    return {
        "record_count": len(records),
        "request_count": sum(int(api.get("request_count") or 0) for api in apis),
        "response_count": sum(int(api.get("response_count") or 0) for api in apis),
        "failed_request_count": sum(int(api.get("failed_request_count") or 0) for api in apis),
        "observed_prompt_tokens": sum(int(api.get("observed_prompt_tokens") or 0) for api in apis),
        "observed_completion_tokens": sum(int(api.get("observed_completion_tokens") or 0) for api in apis),
        "observed_total_tokens": sum(int(api.get("observed_total_tokens") or 0) for api in apis),
        "exact_known_total_tokens": sum(int(api.get("total_tokens") or 0) for api in apis),
        "complete_api_record_count": sum(api.get("complete") is True for api in apis),
        "credits_spent": sum(int(record.get("submission", {}).get("credits_spent") or 0) for record in records),
        "submission_tool_calls": sum(int(record.get("submission", {}).get("tool_calls") or 0) for record in records),
    }


def score_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def submission_proxy(record: dict[str, Any]) -> tuple[float, float, float] | None:
    submission = record.get("submission", {})
    report_name = submission.get("report")
    if record.get("outcome") != "completed" or not report_name:
        return None
    report = json.loads(local_report_path(report_name).read_text())
    q_hw = report.get("optimization_metrics", {}).get("best_q_hw")
    wall_time_s = report.get("evaluation", {}).get("wall_time_seconds")
    budget = submission.get("budget", {})
    cost_spent = submission.get("credits_spent")
    cost_limit = budget.get("total")
    if not all(isinstance(value, (int, float)) for value in (q_hw, wall_time_s, cost_spent, cost_limit)):
        return None
    cost_util = max(0.0, min(1.0, float(cost_spent) / max(float(cost_limit), 1.0)))
    time_util = max(0.0, min(1.0, float(wall_time_s) / 3600.0))
    efficiency = max(0.8, 1.0 - 0.10 * cost_util - 0.10 * time_util)
    return 100.0 * float(q_hw) * efficiency, float(q_hw), efficiency


def is_api_failure(record: dict[str, Any]) -> bool:
    if record.get("outcome") != "infrastructure_error":
        return False
    stop_reason = str(record.get("submission", {}).get("stop_reason") or "")
    return "LLMCallFailed" in stop_reason or "TimeoutError" in stop_reason


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-run", type=Path, required=True)
    parser.add_argument(
        "--retry-run",
        type=Path,
        action="append",
        default=[],
        help="Infrastructure-only retry run; repeat in chronological order.",
    )
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--public-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    base = load_records(args.base_run)
    retry_runs = list(args.retry_run)
    retries = [(path, load_records(path)) for path in retry_runs]
    public = json.loads(args.public_manifest.read_text())
    expected_ids = {task["task_id"] for task in public["tasks"]}
    if set(base) != expected_ids:
        raise ValueError("base run does not exactly cover the frozen public manifest")
    merged = dict(base)
    retry_records: list[dict[str, Any]] = []
    retry_recovered: list[str] = []
    for retry_path, retry in retries:
        if not set(retry).issubset(base):
            raise ValueError(f"retry run contains tasks absent from the base run: {retry_path}")
        illegal = sorted(
            task_id
            for task_id in retry
            if merged[task_id]["outcome"] != "infrastructure_error"
        )
        if illegal:
            raise ValueError(
                f"retry replaces a currently non-infrastructure record in {retry_path}: {illegal}"
            )
        merged.update(retry)
        retry_records.extend(retry.values())
        retry_recovered.extend(
            task_id for task_id, record in retry.items() if record["outcome"] == "completed"
        )
    selected = [merged[task_id] for task_id in sorted(merged)]
    all_attempts = [base[task_id] for task_id in sorted(base)] + retry_records
    completed = [record for record in selected if record["outcome"] == "completed"]
    api_failures = [record for record in selected if is_api_failure(record)]
    official_scores = [float(record["evaluator"]["score"]) for record in completed if isinstance(record.get("evaluator", {}).get("score"), (int, float))]

    categories: dict[str, dict[str, Any]] = {}
    for category in CATEGORY_CODES.values():
        records = [record for record in selected if category_of(record["task_id"]) == category]
        scores = [float(record["evaluator"]["score"]) for record in records if isinstance(record.get("evaluator", {}).get("score"), (int, float))]
        categories[category] = {
            "task_count": len(records),
            "outcomes": dict(Counter(record["outcome"] for record in records)),
            "reference_score": score_stats(scores),
            "validity_only_completed_count": sum(record["outcome"] == "completed" and record.get("evaluator", {}).get("score") is None for record in records),
        }

    qo_records = [record for record in selected if category_of(record["task_id"]) == "qor_optimization"]
    proxy_rows = [(record["task_id"], submission_proxy(record)) for record in qo_records]
    proxy_rows = [(task_id, values) for task_id, values in proxy_rows if values is not None]
    proxy_values = [values[0] for _, values in proxy_rows]
    q_hw_values = [values[1] for _, values in proxy_rows]
    qo_reference = [float(record["evaluator"]["score"]) for record in qo_records if isinstance(record.get("evaluator", {}).get("score"), (int, float))]

    unresolved = []
    for record in selected:
        if record["outcome"] == "completed":
            continue
        unresolved.append({
            "task_id": record["task_id"],
            "category": category_of(record["task_id"]),
            "outcome": record["outcome"],
            "launcher_error": record.get("launcher_error") or None,
            "submission_stop_reason": record.get("submission", {}).get("stop_reason") or None,
        })

    release = json.loads(args.release_manifest.read_text())
    result = {
        "schema_version": 1,
        "scope": {
            "model": completed[0]["submission"]["model"],
            "base_run": str(args.base_run),
            "retry_run": str(retry_runs[0]) if len(retry_runs) == 1 else None,
            "retry_runs": [str(path) for path in retry_runs],
            "merge_policy": (
                "retry records replace only the currently selected infrastructure-error record, in chronological retry order"
                if retry_runs
                else "base run only; no retry records merged"
            ),
            "base_record_count": len(base),
            "retry_record_count": len(retry_records),
            "merged_record_count": len(selected),
        },
        "frozen_release": {
            "path": str(args.release_manifest.parent),
            "task_count": release["task_count"],
            "public_tree_sha256": release["public_tree_sha256"],
            "evaluator_tree_sha256": release["evaluator_tree_sha256"],
            "public_private_separation_pass": release["public_private_separation_pass"],
        },
        "headline": {
            "outcomes": dict(Counter(record["outcome"] for record in selected)),
            "end_to_end_completion_rate": len(completed) / len(selected),
            "non_infrastructure_conditional_completion_rate": len(completed) / sum(record["outcome"] != "infrastructure_error" for record in selected),
            "api_clean_agent_completion": {
                "numerator": len(completed),
                "denominator": len(selected) - len(api_failures),
                "rate": len(completed) / (len(selected) - len(api_failures)),
                "excluded_api_failure_count": len(api_failures),
                "task_timeouts_remain_failures": True,
            },
            "hidden_correct_count": sum(
                record.get("evaluator", {}).get("status") == "completed"
                and record.get("evaluator", {}).get("return_code") == 0
                and record.get("evaluator", {}).get("grading_source") == "hidden"
                for record in completed
            ),
            "hidden_evaluated_count": len(completed),
            "reference_score": score_stats(official_scores),
            "validity_only_completed_count": len(completed) - len(official_scores),
        },
        "qor_25": {
            "submission_starter_anchored_proxy": {
                **score_stats(proxy_values),
                "mean_q_hw": statistics.fmean(q_hw_values),
                "above_76_count": sum(value > 76.0 for value in proxy_values),
                "formula": "100 * best_q_hw * max(0.8, 1 - 0.10*credit_utilization - 0.10*metered_tool_time_utilization)",
            },
            "evaluator_reference_anchored_score": {
                **score_stats(qo_reference),
                "above_76_count": sum(value > 76.0 for value in qo_reference),
            },
        },
        "categories": categories,
        "token_accounting": {
            "selected_merged_records": aggregate_api(selected),
            "all_attempts_including_retry": aggregate_api(all_attempts),
            "interpretation": "Observed token totals are lower bounds because failed API requests do not report usage.",
        },
        "retry_recovered_task_ids": sorted(retry_recovered),
        "unresolved": unresolved,
    }
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
