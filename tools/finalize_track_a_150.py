#!/usr/bin/env python3
"""Aggregate Track-A initial gates and real-API shard checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


INFRA_OUTCOMES = {"infrastructure_error"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _record_rank(record: dict[str, Any], source_index: int) -> tuple[int, int]:
    # A retry supersedes only infrastructure failures.  Genuine task outcomes
    # stay first-class results and must not be silently retried away.
    non_infra = not _is_infrastructure(record)
    return (1 if non_infra else 0, source_index)


def _is_infrastructure(record: dict[str, Any]) -> bool:
    if record.get("outcome") in INFRA_OUTCOMES or record.get("launcher_error"):
        return True
    audit = " ".join(str(item) for item in record.get("audit_errors") or [])
    return any(
        marker in audit
        for marker in (
            "real_api_usage_incomplete",
            "missing run report",
            "launcher_timeout",
        )
    )


def finalize(
    *,
    corpus_manifest: Path,
    gate_matrix: Path,
    run_root: Path,
    shard_summaries: list[Path],
) -> dict[str, Any]:
    corpus = _load(corpus_manifest)
    gates = _load(gate_matrix)
    if corpus.get("task_count") != 150 or gates.get("fully_accepted") is not True:
        raise RuntimeError("150-task initial acceptance is not frozen")
    corpus_by_task = {
        str(item["task_id"]): item for item in corpus.get("tasks", [])
    }
    category_by_task = {
        task_id: str(item["category"])
        for task_id, item in corpus_by_task.items()
    }
    replacement_audit_path = gate_matrix.parent / "candidate_replacement_audit.json"
    replacement_audit = (
        _load(replacement_audit_path)
        if replacement_audit_path.is_file()
        else {
            "schema_version": 1,
            "purpose": "track_a_candidate_replacement_audit",
            "replaced_count": 0,
            "replacements": [],
        }
    )
    incident_resolution_path = run_root / "api_incident_resolution.json"
    incident_resolution = (
        _load(incident_resolution_path)
        if incident_resolution_path.is_file()
        else None
    )
    if len(category_by_task) != 150:
        raise RuntimeError("accepted manifest does not contain 150 unique tasks")

    candidates: dict[str, list[tuple[int, dict[str, Any], Path]]] = defaultdict(list)
    shard_meta = []
    all_attempt_records: list[tuple[dict[str, Any], Path]] = []
    for source_index, path in enumerate(shard_summaries):
        summary = _load(path)
        stable = (summary.get("execution_source") or {}).get("stable") is True
        if not stable:
            raise RuntimeError(f"execution source drift in {path}")
        shard_meta.append(
            {
                "path": str(path),
                "sha256": _sha256(path),
                "selected_task_count": summary.get("selected_task_count"),
                "completed_record_count": summary.get("completed_record_count"),
                "elapsed_s": summary.get("elapsed_s"),
                "execution_source_tree_sha256": (
                    (summary.get("execution_source") or {}).get("start") or {}
                ).get("tree_sha256"),
            }
        )
        for record in summary.get("records", []):
            task_id = str(record.get("task_id"))
            if task_id not in category_by_task:
                raise RuntimeError(f"result outside frozen corpus: {task_id}")
            candidates[task_id].append((source_index, record, path))
            all_attempt_records.append((record, path))

    selected: dict[str, tuple[dict[str, Any], Path]] = {}
    superseded = []
    for task_id, values in candidates.items():
        best = max(
            values, key=lambda item: _record_rank(item[1], item[0])
        )
        selected[task_id] = (best[1], best[2])
        for value in values:
            if value is not best:
                superseded.append(
                    {
                        "task_id": task_id,
                        "outcome": value[1].get("outcome"),
                        "source": str(value[2]),
                        "reason": "retry_superseded_infrastructure_record",
                    }
                )

    missing = sorted(set(category_by_task) - set(selected))
    if missing:
        raise RuntimeError(f"missing task results: {missing}")

    per_task: dict[str, dict[str, Any]] = {}
    category_stats: dict[str, dict[str, Any]] = {}
    totals: Counter[str] = Counter()
    total_score = 0.0
    scored_count = 0
    total_task_wall_time_s = 0.0
    models: set[str] = set()
    clients: set[str] = set()
    compliance_proven = 0
    calls_by_tool_total: Counter[str] = Counter()
    failed_calls_by_tool_total: Counter[str] = Counter()
    evaluator_calls_by_stage_total: Counter[str] = Counter()
    failure_audit = []
    retry_task_ids = []
    unscored_completed_task_ids = []
    for task_id in sorted(selected):
        record, source = selected[task_id]
        category = category_by_task[task_id]
        submission = record.get("submission") or {}
        evaluator = record.get("evaluator") or {}
        api = submission.get("api") or {}
        budget = submission.get("budget") or {}
        if submission.get("model"):
            models.add(str(submission["model"]))
        if submission.get("llm_client"):
            clients.add(str(submission["llm_client"]))
        compliance = submission.get("model_compliance") or {}
        compliance_proven += int(compliance.get("compliance_proven") is True)
        outcome = str(record.get("outcome"))
        score = evaluator.get("score")
        success = outcome == "completed" and not record.get("audit_errors")
        if isinstance(score, (int, float)):
            total_score += float(score)
            scored_count += 1
        elif outcome == "completed":
            unscored_completed_task_ids.append(task_id)
        totals["request_count"] += int(api.get("request_count") or 0)
        totals["response_count"] += int(api.get("response_count") or 0)
        totals["failed_request_count"] += int(api.get("failed_request_count") or 0)
        totals["prompt_tokens"] += int(api.get("prompt_tokens") or 0)
        totals["completion_tokens"] += int(api.get("completion_tokens") or 0)
        totals["total_tokens"] += int(api.get("total_tokens") or 0)
        totals["credits_spent"] += int(submission.get("credits_spent") or 0)
        totals["tool_calls"] += int(submission.get("tool_calls") or 0)
        calls_by_tool_total.update(submission.get("calls_by_tool") or {})
        failed_calls_by_tool_total.update(
            submission.get("failed_calls_by_tool") or {}
        )
        evaluator_calls_by_stage_total.update(
            evaluator.get("grading_calls_by_stage") or {}
        )
        totals["evaluator_grading_tool_calls"] += int(
            evaluator.get("grading_tool_call_count") or 0
        )
        totals["credit_limit"] += int(budget.get("total") or 0)
        task_wall_time_s = float(submission.get("elapsed_s") or 0) + float(
            evaluator.get("elapsed_s") or 0
        )
        total_task_wall_time_s += task_wall_time_s
        cat = category_stats.setdefault(
            category,
            {
                "task_count": 0,
                "success_count": 0,
                "score_sum": 0.0,
                "scored_count": 0,
                "tokens": 0,
                "api_requests": 0,
                "tool_calls": 0,
                "credits": 0,
                "credit_limit": 0,
                "wall_time_s": 0.0,
            },
        )
        cat["task_count"] += 1
        cat["success_count"] += int(success)
        cat["tokens"] += int(api.get("total_tokens") or 0)
        cat["api_requests"] += int(api.get("request_count") or 0)
        cat["tool_calls"] += int(submission.get("tool_calls") or 0)
        cat["credits"] += int(submission.get("credits_spent") or 0)
        cat["credit_limit"] += int(budget.get("total") or 0)
        cat["wall_time_s"] += float(submission.get("elapsed_s") or 0) + float(
            evaluator.get("elapsed_s") or 0
        )
        if isinstance(score, (int, float)):
            cat["score_sum"] += float(score)
            cat["scored_count"] += 1

        per_task[task_id] = {
            "category": category,
            "initial_gate_evidence": corpus_by_task[task_id].get("evidence"),
            "initial_gate_evidence_sha256": corpus_by_task[task_id].get(
                "evidence_sha256"
            ),
            "outcome": outcome,
            "success": success,
            "official_score": score,
            "audit_errors": record.get("audit_errors") or [],
            "submission_status": submission.get("status"),
            "submission_stop_reason": submission.get("stop_reason"),
            "evaluator_status": evaluator.get("status"),
            "evaluator_stop_reason": evaluator.get("stop_reason"),
            "tokens": {
                "prompt": api.get("prompt_tokens"),
                "completion": api.get("completion_tokens"),
                "total": api.get("total_tokens"),
            },
            "api_requests": api.get("request_count"),
            "api_responses": api.get("response_count"),
            "failed_api_requests": api.get("failed_request_count"),
            "tool_calls": submission.get("tool_calls"),
            "calls_by_tool": submission.get("calls_by_tool") or {},
            "failed_calls_by_tool": submission.get("failed_calls_by_tool") or {},
            "evaluator_grading_tool_calls": evaluator.get(
                "grading_tool_call_count"
            ),
            "evaluator_calls_by_stage": evaluator.get(
                "grading_calls_by_stage"
            )
            or {},
            "credits_spent": submission.get("credits_spent"),
            "budget": budget,
            "wall_time_s": task_wall_time_s,
            "frequency_mhz": submission.get("frequency_mhz"),
            "submission_report": submission.get("report"),
            "submission_report_sha256": submission.get("report_sha256"),
            "evaluator_report": evaluator.get("report"),
            "evaluator_report_sha256": evaluator.get("report_sha256"),
            "final_kernel": submission.get("final_kernel"),
            "final_kernel_sha256": submission.get("final_kernel_sha256"),
            "checkpoint_source": str(source),
            "model": submission.get("model"),
            "llm_client": submission.get("llm_client"),
            "model_compliance_proven": compliance.get("compliance_proven"),
        }
        if not success:
            failure_audit.append(
                {
                    "task_id": task_id,
                    "category": category,
                    "outcome": outcome,
                    "audit_errors": record.get("audit_errors") or [],
                    "launcher_error": record.get("launcher_error"),
                    "submission_status": submission.get("status"),
                    "submission_stop_reason": submission.get("stop_reason"),
                    "evaluator_status": evaluator.get("status"),
                    "evaluator_stop_reason": evaluator.get("stop_reason"),
                }
            )
        if _is_infrastructure(record):
            retry_task_ids.append(task_id)

    for value in category_stats.values():
        value["success_rate"] = value["success_count"] / value["task_count"]
        value["mean_official_score_all_tasks"] = (
            value["score_sum"] / value["task_count"]
        )
        value["mean_official_score_scored_tasks"] = (
            value["score_sum"] / value["scored_count"]
            if value["scored_count"]
            else 0.0
        )
        value["wall_time_s"] = round(value["wall_time_s"], 3)
        del value["score_sum"]

    outcome_counts = Counter(
        item["outcome"] for item in per_task.values()
    )
    shard_elapsed = [
        float(item.get("elapsed_s") or 0.0) for item in shard_meta
    ]
    execution_hashes = {
        item["execution_source_tree_sha256"] for item in shard_meta
    }
    attempt_totals: Counter[str] = Counter()
    attempt_outcomes: Counter[str] = Counter()
    attempt_calls_by_tool: Counter[str] = Counter()
    attempt_evaluator_calls_by_stage: Counter[str] = Counter()
    for record, _ in all_attempt_records:
        submission = record.get("submission") or {}
        evaluator = record.get("evaluator") or {}
        api = submission.get("api") or {}
        budget = submission.get("budget") or {}
        attempt_outcomes[str(record.get("outcome"))] += 1
        for key in (
            "request_count",
            "response_count",
            "failed_request_count",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
        ):
            attempt_totals[key] += int(api.get(key) or 0)
        attempt_totals["credits_spent"] += int(
            submission.get("credits_spent") or 0
        )
        attempt_totals["credit_limit"] += int(budget.get("total") or 0)
        attempt_totals["tool_calls"] += int(
            submission.get("tool_calls") or 0
        )
        attempt_totals["evaluator_grading_tool_calls"] += int(
            evaluator.get("grading_tool_call_count") or 0
        )
        attempt_totals["task_wall_time_ms"] += int(
            round(
                (
                    float(submission.get("elapsed_s") or 0)
                    + float(evaluator.get("elapsed_s") or 0)
                )
                * 1000
            )
        )
        attempt_calls_by_tool.update(submission.get("calls_by_tool") or {})
        attempt_evaluator_calls_by_stage.update(
            evaluator.get("grading_calls_by_stage") or {}
        )
    blocked_audit_path = run_root / "blocked_api_audit.json"
    diagnostic = {}
    if blocked_audit_path.is_file():
        blocking = (_load(blocked_audit_path).get("blocking_condition") or {})
        diagnostic = {
            "api_requests": int(
                blocking.get("minimal_diagnostic_api_requests") or 0
            ),
            "api_responses": int(
                blocking.get("minimal_diagnostic_api_responses") or 0
            ),
            "failed_api_requests": int(
                blocking.get("minimal_diagnostic_failed_api_requests") or 0
            ),
            "tokens": 0,
            "credentials_recorded": False,
        }
    payload = {
        "schema_version": 1,
        "purpose": "track_a_150_real_ali_api_final_report",
        "run_root": str(run_root),
        "frozen_corpus_manifest": {
            "path": str(corpus_manifest),
            "sha256": _sha256(corpus_manifest),
        },
        "initial_gate_matrix": {
            "path": str(gate_matrix),
            "sha256": _sha256(gate_matrix),
            "accepted_count": gates.get("accepted_count"),
        },
        "benchmark_construction_failure_audit": {
            "path": str(replacement_audit_path)
            if replacement_audit_path.is_file()
            else None,
            "sha256": _sha256(replacement_audit_path)
            if replacement_audit_path.is_file()
            else None,
            "replaced_count": replacement_audit.get("replaced_count", 0),
            "replacements": replacement_audit.get("replacements", []),
        },
        "api_incident_resolution": {
            "path": str(incident_resolution_path)
            if incident_resolution is not None
            else None,
            "sha256": _sha256(incident_resolution_path)
            if incident_resolution is not None
            else None,
            "status": (incident_resolution or {}).get("status"),
            "campaign_timing": (incident_resolution or {}).get(
                "campaign_timing"
            ),
        },
        "finalizer": {
            "path": str(Path(__file__).resolve()),
            "sha256": _sha256(Path(__file__).resolve()),
        },
        "coverage": {
            "expected_task_count": 150,
            "recorded_task_count": len(per_task),
            "outcome_counts": dict(sorted(outcome_counts.items())),
            "execution_source_stable": len(execution_hashes) == 1,
            "execution_source_tree_sha256": next(iter(execution_hashes))
            if len(execution_hashes) == 1
            else None,
        },
        "aggregate": {
            "success_count": sum(item["success"] for item in per_task.values()),
            "success_rate": sum(item["success"] for item in per_task.values()) / 150,
            "official_score_sum": total_score,
            "official_score_mean_all_tasks": total_score / 150,
            "official_score_mean_scored_tasks": total_score / scored_count
            if scored_count
            else 0.0,
            "scored_task_count": scored_count,
            "tokens": {
                "prompt": totals["prompt_tokens"],
                "completion": totals["completion_tokens"],
                "total": totals["total_tokens"],
            },
            "api_requests": totals["request_count"],
            "api_responses": totals["response_count"],
            "failed_api_requests": totals["failed_request_count"],
            "tool_calls": totals["tool_calls"],
            "calls_by_tool": dict(sorted(calls_by_tool_total.items())),
            "failed_calls_by_tool": dict(
                sorted(failed_calls_by_tool_total.items())
            ),
            "evaluator_grading_tool_calls": totals[
                "evaluator_grading_tool_calls"
            ],
            "evaluator_calls_by_stage": dict(
                sorted(evaluator_calls_by_stage_total.items())
            ),
            "credits_spent": totals["credits_spent"],
            "credit_limit": totals["credit_limit"],
            "task_wall_time_s": round(total_task_wall_time_s, 3),
            "shard_elapsed_sum_s": round(sum(shard_elapsed), 3),
            "parallel_campaign_elapsed_max_shard_s": round(
                max(shard_elapsed, default=0.0), 3
            ),
        },
        "all_attempt_accounting": {
            "task_attempt_record_count": len(all_attempt_records),
            "unique_task_count": len(candidates),
            "superseded_task_attempt_count": len(all_attempt_records)
            - len(selected),
            "outcome_counts": dict(sorted(attempt_outcomes.items())),
            "tokens": {
                "prompt": attempt_totals["prompt_tokens"],
                "completion": attempt_totals["completion_tokens"],
                "total": attempt_totals["total_tokens"],
            },
            "api_requests_in_task_attempts": attempt_totals["request_count"],
            "api_responses_in_task_attempts": attempt_totals["response_count"],
            "failed_api_requests_in_task_attempts": attempt_totals[
                "failed_request_count"
            ],
            "diagnostic_api_usage": diagnostic,
            "total_observed_api_requests": attempt_totals["request_count"]
            + int(diagnostic.get("api_requests") or 0),
            "total_observed_api_responses": attempt_totals["response_count"]
            + int(diagnostic.get("api_responses") or 0),
            "total_observed_failed_api_requests": attempt_totals[
                "failed_request_count"
            ]
            + int(diagnostic.get("failed_api_requests") or 0),
            "tool_calls": attempt_totals["tool_calls"],
            "calls_by_tool": dict(sorted(attempt_calls_by_tool.items())),
            "evaluator_grading_tool_calls": attempt_totals[
                "evaluator_grading_tool_calls"
            ],
            "evaluator_calls_by_stage": dict(
                sorted(attempt_evaluator_calls_by_stage.items())
            ),
            "credits_spent": attempt_totals["credits_spent"],
            "credit_limit_across_attempts": attempt_totals["credit_limit"],
            "task_attempt_wall_time_s": round(
                attempt_totals["task_wall_time_ms"] / 1000, 3
            ),
        },
        "score_availability": {
            "scored_task_count": scored_count,
            "unscored_completed_task_count": len(
                unscored_completed_task_ids
            ),
            "unscored_completed_task_ids": sorted(
                unscored_completed_task_ids
            ),
            "unscored_reason": (
                "evaluator acceptance passed but no valid QoR anchor "
                "score was available"
            ),
        },
        "model_and_api": {
            "models": sorted(models),
            "clients": sorted(clients),
            "model_compliance_proven_task_count": compliance_proven,
            "real_api_only": clients == {"OpenAICompatClient"}
            and totals["request_count"] == totals["response_count"]
            and totals["failed_request_count"] == 0,
            "mock_or_scripted_backend_observed": any(
                value.lower() in {"scripted", "mock", "replay"} for value in clients
            ),
        },
        "category_metrics": dict(sorted(category_stats.items())),
        "retry_task_ids": sorted(retry_task_ids),
        "failure_audit": failure_audit,
        "per_task": per_task,
        "shards": shard_meta,
        "superseded_records": superseded,
    }
    _atomic_json(run_root / "final_report.json", payload)
    _atomic_json(run_root / "per_task_evidence.json", per_task)
    _atomic_json(
        run_root / "retry_manifest.json",
        {
            "schema_version": 1,
            "retry_policy": "infrastructure_only",
            "retry_task_ids": sorted(retry_task_ids),
        },
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-manifest", required=True, type=Path)
    parser.add_argument("--gate-matrix", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--shard-summary", action="append", type=Path, default=[])
    args = parser.parse_args()
    summaries = args.shard_summary or sorted(
        args.run_root.glob("**/shard_summary.json")
    )
    report = finalize(
        corpus_manifest=args.corpus_manifest,
        gate_matrix=args.gate_matrix,
        run_root=args.run_root,
        shard_summaries=summaries,
    )
    aggregate = report["aggregate"]
    print(
        f"tasks={report['coverage']['recorded_task_count']} "
        f"success={aggregate['success_count']} "
        f"score={aggregate['official_score_sum']:.3f} "
        f"tokens={aggregate['tokens']['total']} "
        f"requests={aggregate['api_requests']} "
        f"retries={len(report['retry_task_ids'])}"
    )
    return 0 if not report["retry_task_ids"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
