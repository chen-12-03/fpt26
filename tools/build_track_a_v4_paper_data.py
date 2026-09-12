#!/usr/bin/env python3
"""Build the canonical three-model Track-A v4 paper dataset.

Run this script inside the project container because some raw reports use the
container user as their owner.  The script reads frozen run artifacts and
writes one JSON document to stdout.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from summarize_track_a_v4_campaign import (
    CATEGORY_CODES,
    aggregate_api,
    category_of,
    load_records,
    score_stats,
    is_api_failure,
    submission_proxy,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-manifest", required=True, type=Path)
    parser.add_argument("--public-manifest", required=True, type=Path)
    parser.add_argument("--qwen36-base", required=True, type=Path)
    parser.add_argument(
        "--qwen36-retry",
        required=True,
        type=Path,
        action="append",
        help="Qwen3.6 infrastructure retry run; repeat in chronological order.",
    )
    parser.add_argument("--qwen35-base", required=True, type=Path)
    parser.add_argument(
        "--qwen35-retry",
        required=True,
        type=Path,
        action="append",
        help="Qwen3.5 infrastructure retry run; repeat in chronological order.",
    )
    parser.add_argument("--deepseek-base", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def first_shard(run_root: Path) -> dict[str, Any]:
    paths = sorted(run_root.glob("shard_*/shard_summary.json"))
    if not paths:
        raise ValueError(f"no shard summaries under {run_root}")
    return json.loads(paths[0].read_text())


def source_metadata(run_root: Path, records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    shard = first_shard(run_root)
    snapshots = [
        json.loads(path.read_text())["execution_source"]
        for path in sorted(run_root.glob("shard_*/shard_summary.json"))
    ]
    hashes = {
        snapshot["start"]["tree_sha256"]
        for snapshot in snapshots
    } | {
        snapshot["current"]["tree_sha256"]
        for snapshot in snapshots
    }
    stable = all(snapshot.get("stable") is True for snapshot in snapshots)
    if len(hashes) != 1 or not stable:
        raise ValueError(f"unstable execution source under {run_root}")
    compliance_counts = Counter(
        json.dumps(record["submission"].get("model_compliance"), sort_keys=True)
        for record in records.values()
        if record["submission"].get("model_compliance") is not None
    )
    return {
        "agent_source_tree_sha256": hashes.pop(),
        "agent_source_file_count": snapshots[0]["start"]["file_count"],
        "llm_run_contract": shard["llm_run_contract"],
        "tool_timeout_policy": shard["tool_timeout_policy"],
        "model_compliance": {
            "records_with_evidence": sum(compliance_counts.values()),
            "records_without_evidence": len(records) - sum(compliance_counts.values()),
            "variants": [
                {"record_count": count, "evidence": json.loads(payload)}
                for payload, count in sorted(compliance_counts.items())
            ],
        },
        "maximum_shard_elapsed_hours": max(
            json.loads(path.read_text()).get("elapsed_s", 0.0) / 3600.0
            for path in sorted(run_root.glob("shard_*/shard_summary.json"))
        ),
    }


def view_summary(records_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    records = [records_by_id[task_id] for task_id in sorted(records_by_id)]
    completed = [record for record in records if record["outcome"] == "completed"]
    api_failures = [record for record in records if is_api_failure(record)]
    scores = [
        float(record["evaluator"]["score"])
        for record in completed
        if isinstance(record.get("evaluator", {}).get("score"), (int, float))
    ]
    category_rows: dict[str, Any] = {}
    for category in CATEGORY_CODES.values():
        rows = [record for record in records if category_of(record["task_id"]) == category]
        category_scores = [
            float(record["evaluator"]["score"])
            for record in rows
            if isinstance(record.get("evaluator", {}).get("score"), (int, float))
        ]
        category_rows[category] = {
            "task_count": len(rows),
            "outcomes": dict(Counter(record["outcome"] for record in rows)),
            "reference_score": score_stats(category_scores),
            "validity_only_completed_count": sum(
                record["outcome"] == "completed"
                and record.get("evaluator", {}).get("score") is None
                for record in rows
            ),
        }

    qo_rows: dict[str, dict[str, float]] = {}
    for record in records:
        if category_of(record["task_id"]) != "qor_optimization":
            continue
        proxy = submission_proxy(record)
        score = record.get("evaluator", {}).get("score")
        if proxy is not None and isinstance(score, (int, float)):
            qo_rows[record["task_id"]] = {
                "submission_proxy": proxy[0],
                "q_hw": proxy[1],
                "efficiency": proxy[2],
                "reference_score": float(score),
            }
    proxy_values = [row["submission_proxy"] for row in qo_rows.values()]
    reference_values = [row["reference_score"] for row in qo_rows.values()]
    return {
        "outcomes": dict(Counter(record["outcome"] for record in records)),
        "public_gate_completion": {
            "numerator": len(completed),
            "denominator": len(records),
            "percent": 100.0 * len(completed) / len(records),
        },
        "non_infrastructure_conditional_completion": {
            "numerator": len(completed),
            "denominator": sum(record["outcome"] != "infrastructure_error" for record in records),
        },
        "api_clean_agent_completion": {
            "numerator": len(completed),
            "denominator": len(records) - len(api_failures),
            "percent": 100.0 * len(completed) / (len(records) - len(api_failures)),
            "excluded_api_failure_count": len(api_failures),
            "task_timeouts_remain_failures": True,
        },
        "evaluator_hidden_correctness": {
            "numerator": sum(
                record.get("evaluator", {}).get("status") == "completed"
                and record.get("evaluator", {}).get("return_code") == 0
                and record.get("evaluator", {}).get("grading_source") == "hidden"
                for record in completed
            ),
            "denominator": len(completed),
            "corpus_coverage": len(completed),
            "corpus_size": len(records),
        },
        "reference_anchored_official_score": {
            **score_stats(scores),
            "corpus_size": len(records),
            "validity_only_completed_count": len(completed) - len(scores),
        },
        "qor_25": {
            "available_count": len(qo_rows),
            "slice_size": 25,
            "submission_starter_anchored_proxy": score_stats(proxy_values),
            "evaluator_reference_anchored_score": score_stats(reference_values),
            "task_values": qo_rows,
        },
        "categories": category_rows,
        "token_accounting": aggregate_api(records),
        "unresolved": [
            {
                "task_id": record["task_id"],
                "outcome": record["outcome"],
                "submission_stop_reason": record.get("submission", {}).get("stop_reason"),
                "launcher_error": record.get("launcher_error") or None,
            }
            for record in records
            if record["outcome"] != "completed"
        ],
    }


def merged_retry_view(
    base: dict[str, dict[str, Any]], retry: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    if not set(retry).issubset(base):
        raise ValueError("retry includes a task outside the base run")
    invalid = [
        task_id
        for task_id in retry
        if base[task_id]["outcome"] != "infrastructure_error"
    ]
    if invalid:
        raise ValueError(f"retry replaces non-infrastructure records: {invalid}")
    merged = dict(base)
    merged.update(retry)
    return merged


def merged_retry_chain(
    base: dict[str, dict[str, Any]], retry_runs: list[Path]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    merged = dict(base)
    all_retry_records: list[dict[str, Any]] = []
    for retry_run in retry_runs:
        retry = load_records(retry_run)
        merged = merged_retry_view(merged, retry)
        all_retry_records.extend(retry.values())
    return merged, all_retry_records


def mean(values: list[float]) -> float:
    return statistics.fmean(values)


def main() -> None:
    args = parse_args()
    release = json.loads(args.release_manifest.read_text())
    public = json.loads(args.public_manifest.read_text())
    expected_ids = {task["task_id"] for task in public["tasks"]}

    run_paths = {
        "qwen3.6-27b": args.qwen36_base,
        "qwen3.5-122b-a10b": args.qwen35_base,
        "deepseek-v4-pro": args.deepseek_base,
    }
    base_records = {name: load_records(path) for name, path in run_paths.items()}
    for name, records in base_records.items():
        if set(records) != expected_ids:
            raise ValueError(f"{name} does not exactly cover the public manifest")

    model_rows: dict[str, Any] = {}
    for name, records in base_records.items():
        model_rows[name] = {
            "base_run": str(run_paths[name]),
            **source_metadata(run_paths[name], records),
            "base_view": view_summary(records),
        }

    retry_paths = {
        "qwen3.6-27b": list(args.qwen36_retry),
        "qwen3.5-122b-a10b": list(args.qwen35_retry),
        "deepseek-v4-pro": [],
    }
    selected_records: dict[str, dict[str, dict[str, Any]]] = {}
    for name, records in base_records.items():
        merged, all_retry_records = merged_retry_chain(records, retry_paths[name])
        selected_records[name] = merged
        retry_sources = [
            source_metadata(path, load_records(path)) for path in retry_paths[name]
        ]
        model_rows[name]["selected_view"] = view_summary(merged)
        model_rows[name]["selection"] = {
            "policy": (
                "chronological infrastructure-only retries replace the currently selected infrastructure-error record"
                if retry_paths[name]
                else "base run; no infrastructure retry was required"
            ),
            "retry_runs": [str(path) for path in retry_paths[name]],
            "retry_record_count": len(all_retry_records),
            "retry_source_metadata": retry_sources,
            "all_attempt_token_accounting": aggregate_api(
                list(records.values()) + all_retry_records
            ),
        }

    task_sets = {
        name: set(model_rows[name]["selected_view"]["qor_25"]["task_values"])
        for name in model_rows
    }
    common_qor_ids = sorted(set.intersection(*task_sets.values()))
    common_qor = {}
    for name, row in model_rows.items():
        values = row["selected_view"]["qor_25"]["task_values"]
        common_qor[name] = {
            "submission_starter_anchored_proxy_mean": mean(
                [values[task_id]["submission_proxy"] for task_id in common_qor_ids]
            ),
            "evaluator_reference_anchored_score_mean": mean(
                [values[task_id]["reference_score"] for task_id in common_qor_ids]
            ),
        }

    qwen_files = first_shard(args.qwen35_base)["execution_source"]["start"]["files"]
    deepseek_files = first_shard(args.deepseek_base)["execution_source"]["start"]["files"]
    changed_files = sorted(
        path
        for path in set(qwen_files) | set(deepseek_files)
        if qwen_files.get(path) != deepseek_files.get(path)
    )

    result = {
        "schema_version": 1,
        "generated_on": "2026-09-13",
        "scope": "Track-A v4 three-endpoint paper dataset",
        "frozen_release": {
            "path": str(args.release_manifest.parent),
            "task_count": release["task_count"],
            "public_tree_sha256": release["public_tree_sha256"],
            "evaluator_tree_sha256": release["evaluator_tree_sha256"],
            "public_private_separation_pass": release["public_private_separation_pass"],
        },
        "primary_comparison_policy": {
            "view": "one final campaign result per model",
            "reason": "Infrastructure-only retry records replace infrastructure-error records from the same campaign. The final selected record set is the reported run result.",
        },
        "models": model_rows,
        "common_qor_subset": {
            "task_count": len(common_qor_ids),
            "task_ids": common_qor_ids,
            "models": common_qor,
        },
        "comparability_audit": {
            "same_frozen_corpus": True,
            "base_run_has_150_unique_tasks_per_model": True,
            "same_temperature": True,
            "same_max_tokens": True,
            "same_llm_timeout": True,
            "same_llm_retry_count": False,
            "same_infrastructure_only_replacement_rule": True,
            "same_tool_timeouts": True,
            "identical_agent_source_tree": False,
            "retry_source_hashes_retained_for_provenance": True,
            "deepseek_source_files_changed_from_qwen": changed_files,
            "deepseek_provider_thinking_mode": "disabled",
            "execution_source_snapshot_includes_llm4hls_adapter": False,
        },
        "paper_readiness": {
            "descriptive_base_run_results": "ready as immutable endpoint-reliability evidence",
            "descriptive_selected_results": "ready as one final campaign result per model",
            "common_subset_qor_comparison": "ready from selected records",
            "infrastructure_retry_result": "ready; report API-clean ability separately from raw endpoint completion",
            "causal_model_ranking": "unsupported by one campaign per endpoint",
            "causal_agent_component_claims": "unsupported without matched ablations",
            "deepseek_open_source_compliance": "unproven in every run record",
            "full_corpus_reference_score": "unavailable because fixed anchors cover only a subset outside QoR-25",
            "source_provenance": "partial because the execution snapshot excludes llm4hls/llm.py",
        },
    }
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
