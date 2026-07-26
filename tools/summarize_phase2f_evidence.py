#!/usr/bin/env python3
"""Summarize current Phase 2F evidence without running API or Vitis."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_FULL199 = Path(
    "fpt26-agent-v3/scoring/reports/"
    "phase2d_full199_acceptance_with_retry1_20260725.json"
)
DEFAULT_FORMAL_AB = Path(
    "fpt26-agent-v3/scoring/reports/"
    "phase2e_qor_rag_ab_current_vs_legacy_20260725.json"
)
DEFAULT_HARDCODING = Path(
    "fpt26-agent-v3/scoring/reports/phase2f_agent_hardcoding_audit_20260725.json"
)
DEFAULT_TRIAGE = Path(
    "fpt26-agent-v3/scoring/reports/phase2f_offline_agent_triage_20260725.json"
)
DEFAULT_SMALL_AB_PLAN = Path(
    "fpt26-agent-v3/scoring/reports/phase2f_qor_rag_small_ab_plan_20260725.json"
)
DEFAULT_QOR_SMALL_AB_MEASURED = Path(
    "fpt26-agent-v3/scoring/reports/"
    "phase2f_qor_rag_small_ab_measured_20260725.json"
)
DEFAULT_FAILED_TASK_PLAN = Path(
    "fpt26-agent-v3/scoring/reports/"
    "phase2f_failed_task_small_sample_plan_20260725.json"
)
DEFAULT_FAILED_TASK_MEASURED = Path(
    "fpt26-agent-v3/scoring/reports/"
    "phase2f_failed_task_small_sample_measured_20260725.json"
)
DEFAULT_SINGLE_DOT = Path(
    "fpt26-agent-v3/scoring/reports/phase2b_single_dot_current_rag_ab_20260725.json"
)
DEFAULT_PUBLIC_SAMPLE = Path(
    "fpt26-agent-v3/scoring/reports/phase2c_public_hls_sample_audit_20260725.json"
)
DEFAULT_RETRIEVAL_EVAL = Path(
    "fpt26-agent-v3/evals/qor_rag_retrieval_eval_latest.json"
)
DEFAULT_OUTPUT = Path(
    "fpt26-agent-v3/scoring/reports/phase2f_current_evidence_summary_20260725.json"
)


def build_summary(
    *,
    full199: Mapping[str, Any],
    formal_ab: Mapping[str, Any],
    hardcoding: Mapping[str, Any],
    triage: Mapping[str, Any],
    small_ab_plan: Mapping[str, Any],
    failed_task_plan: Mapping[str, Any] | None = None,
    qor_small_ab_measured: (
        Mapping[str, Any] | Sequence[Mapping[str, Any] | None] | None
    ) = None,
    failed_task_measured: (
        Mapping[str, Any] | Sequence[Mapping[str, Any] | None] | None
    ) = None,
    small_sample_attempts: Sequence[Mapping[str, Any] | None] | None = None,
    single_dot: Mapping[str, Any] | None = None,
    public_sample: Mapping[str, Any] | None = None,
    retrieval_eval: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    objective = triage.get("phase2f_objective_status", {})
    attempt_reports = _optional_report_list(small_sample_attempts)
    qor_measured_reports = _optional_report_list(qor_small_ab_measured)
    failed_task_measured_reports = _optional_report_list(failed_task_measured)
    current_missing_evidence = _current_missing_evidence(
        small_ab_plan=small_ab_plan,
        qor_measured_reports=qor_measured_reports,
        failed_task_measured_reports=failed_task_measured_reports,
    )
    return {
        "schema_version": 1,
        "purpose": "phase2f_current_evidence_summary",
        "status": "offline_summary_only",
        "constraints": {
            "api_or_vitis_run": False,
            "summary_generation_api_or_vitis_run": False,
            "small_sample_attempts_included": bool(attempt_reports),
            "full199_run": False,
            "execution_freeze_updated": False,
            "hidden_reference_or_evaluator_private_reads": False,
        },
        "full199_acceptance": _full199_summary(full199),
        "formal_qor_rag_ab": _formal_ab_summary(formal_ab),
        "real_small_samples": _sample_summaries(single_dot, public_sample),
        "measured_small_samples": _measured_small_sample_summaries(
            qor_small_ab_measured,
            failed_task_measured_reports,
        ),
        "small_sample_attempts": _attempt_summaries(attempt_reports),
        "retrieval_eval": _retrieval_summary(retrieval_eval),
        "hardcoding_audit": _hardcoding_summary(hardcoding),
        "small_ab_plan": _small_plan_summary(small_ab_plan),
        "failed_task_small_sample_plan": _failed_plan_summary(
            failed_task_plan
        ),
        "objective_status": {
            "objective_complete": _get(
                objective, "completion", "objective_complete"
            ),
            "current_blocking_missing_evidence": current_missing_evidence,
            "blocking_missing_evidence": _get(
                objective, "completion", "blocking_missing_evidence"
            )
            or [],
            "fresh_measured_qor_small_sample_count": len(qor_measured_reports),
            "fresh_measured_qor_small_sample_tasks": _measured_qor_tasks(
                qor_measured_reports
            ),
            "measured_qor_repair_proven": _get(
                objective,
                "qor_rag_generalized_offline",
                "measured_qor_repair_proven",
            ),
            "measured_success_rate_repair_proven": _get(
                objective,
                "failed_task_success_rate_offline",
                "measured_success_rate_repair_proven",
            ),
        },
        "recommended_next_actions": _recommended_next_actions(
            current_missing_evidence=current_missing_evidence,
            qor_measured_reports=qor_measured_reports,
            failed_task_measured_reports=failed_task_measured_reports,
        ),
    }


def _full199_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    coverage = _mapping(report.get("coverage"))
    model = _mapping(report.get("model_and_api"))
    token_totals = _mapping(model.get("token_totals"))
    resources = _mapping(report.get("resource_consumption"))
    target_gates = _mapping(report.get("target_gates"))
    tasks = _mapping(report.get("tasks"))
    expected = _num(coverage.get("expected_task_count")) or len(tasks)
    outcomes = _mapping(coverage.get("outcome_counts"))
    completed = _num(outcomes.get("completed")) or 0
    failed = _num(outcomes.get("failed")) or 0
    request_count = _num(token_totals.get("request_count"))
    total_tokens = _num(token_totals.get("total_tokens"))
    tasks_with_api = _num(model.get("tasks_with_api_requests"))
    scores: list[float] = []
    q_hws: list[float] = []
    credits: list[float] = []
    for record in tasks.values():
        if not isinstance(record, Mapping):
            continue
        evaluator = _mapping(record.get("evaluator"))
        scoring = _mapping(evaluator.get("scoring"))
        if scoring.get("valid") is True:
            _append_number(scores, scoring.get("score"))
            _append_number(q_hws, scoring.get("q_hw"))
        submission = _mapping(record.get("submission"))
        budget = _mapping(submission.get("budget"))
        _append_number(credits, budget.get("spent"))
    return {
        "task_count": expected,
        "completed": completed,
        "failed": failed,
        "success_rate": _ratio(completed, expected),
        "failure_reason_counts": coverage.get("stop_reason_counts") or {},
        "audit_error_task_count": coverage.get("audit_error_task_count"),
        "workflow_integrity_ok": report.get("workflow_integrity_ok"),
        "fresh_evidence_only": report.get("fresh_evidence_only"),
        "valid_score_count": len(scores),
        "mean_score_valid_tasks": _mean(scores),
        "mean_q_hw_valid_tasks": _mean(q_hws),
        "total_requests": request_count,
        "total_tokens": total_tokens,
        "mean_requests_per_task": _ratio(request_count, expected),
        "mean_tokens_per_task": _ratio(total_tokens, expected),
        "tasks_with_api_requests": tasks_with_api,
        "mean_requests_per_api_task": _ratio(request_count, tasks_with_api),
        "mean_tokens_per_api_task": _ratio(total_tokens, tasks_with_api),
        "mean_credits_per_task": _mean(credits),
        "credits_spent": resources.get("credits_spent"),
        "tool_call_count": resources.get("tool_call_count"),
        "target_gate_counts": {
            "interface_pass_count": target_gates.get("interface_pass_count"),
            "frequency_100mhz_pass_count": target_gates.get(
                "frequency_100mhz_pass_count"
            ),
            "resource_capacity_pass_count": target_gates.get(
                "resource_capacity_pass_count"
            ),
            "minimum_observed_frequency_mhz": target_gates.get(
                "minimum_observed_frequency_mhz"
            ),
        },
    }


def _formal_ab_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    baseline = _mapping(report.get("baseline"))
    candidate = _mapping(report.get("candidate"))
    comparison = _mapping(report.get("comparison"))
    return {
        "task_count": report.get("task_count"),
        "passed": report.get("passed"),
        "baseline": _ab_lane_summary(baseline),
        "candidate": _ab_lane_summary(candidate),
        "comparison": {
            "correctness_preservation_rate": comparison.get(
                "correctness_preservation_rate"
            ),
            "q_hw_geomean_relative_change": comparison.get(
                "q_hw_geomean_relative_change"
            ),
            "acceleration_geomean_relative_change": comparison.get(
                "acceleration_geomean_relative_change"
            ),
            "mean_tokens_relative_change": comparison.get(
                "mean_tokens_relative_change"
            ),
            "mean_credits_relative_change_monitor_only": comparison.get(
                "mean_credits_relative_change_monitor_only"
            ),
        },
        "failed_gates": [
            name
            for name, value in _mapping(report.get("gates")).items()
            if value is False
        ],
    }


def _ab_lane_summary(lane: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "success_count": lane.get("success_count"),
        "success_rate": lane.get("success_rate"),
        "q_hw_geomean": lane.get("q_hw_geomean"),
        "acceleration_geomean": lane.get("acceleration_geomean"),
        "mean_tokens_per_task": lane.get("mean_tokens_per_task"),
        "mean_prompt_tokens_per_task": lane.get("mean_prompt_tokens_per_task"),
        "mean_completion_tokens_per_task": lane.get(
            "mean_completion_tokens_per_task"
        ),
        "mean_requests_per_task": lane.get("mean_requests_per_task"),
        "mean_credits_per_task": lane.get("mean_credits_per_task"),
        "failure_reason_counts": lane.get("failure_reason_counts"),
        "report_error_counts": lane.get("report_error_counts"),
    }


def _sample_summaries(
    single_dot: Mapping[str, Any] | None,
    public_sample: Mapping[str, Any] | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if single_dot:
        candidate = _mapping(single_dot.get("candidate"))
        comparison = _mapping(single_dot.get("comparison"))
        result["single_dot_current_rag_ab"] = {
            "task_count": single_dot.get("task_count"),
            "success_rate": 1.0 if candidate.get("valid") is True else 0.0,
            "score": candidate.get("score"),
            "q_hw": candidate.get("q_hw"),
            "requests": candidate.get("api_requests"),
            "total_tokens": candidate.get("total_tokens"),
            "mean_tokens_per_task": candidate.get("total_tokens"),
            "token_relative_change": comparison.get("total_token_relative_change"),
            "q_hw_delta": comparison.get("q_hw_delta"),
        }
    if public_sample:
        outcome_counts = _mapping(public_sample.get("outcome_counts"))
        selected = _num(public_sample.get("selected_task_count"))
        tokens = _mapping(public_sample.get("model_and_api"))
        completed = _num(outcome_counts.get("completed")) or 0
        result["public_hls_12_task_sample"] = {
            "task_count": selected,
            "completed": completed,
            "failed": outcome_counts.get("failed"),
            "success_rate": _ratio(completed, selected),
            "total_requests": tokens.get("request_count"),
            "total_tokens": tokens.get("total_tokens"),
            "mean_requests_per_task": _ratio(
                _num(tokens.get("request_count")), selected
            ),
            "mean_tokens_per_task": _ratio(
                _num(tokens.get("total_tokens")), selected
            ),
        }
    return result


def _measured_small_sample_summaries(
    qor_small_ab: Mapping[str, Any] | Sequence[Mapping[str, Any] | None] | None,
    failed_task: Mapping[str, Any] | Sequence[Mapping[str, Any] | None] | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for index, report in enumerate(_optional_report_list(qor_small_ab)):
        key = "qor_rag_small_ab" if index == 0 else _qor_measured_key(report)
        result[key] = _qor_measured_summary(report)
    for index, report in enumerate(_optional_report_list(failed_task)):
        key = (
            "failed_task_small_sample"
            if index == 0
            else _failed_task_measured_key(report)
        )
        summary = _mapping(report.get("small_sample_summary"))
        boundary = _mapping(report.get("acceptance_boundary"))
        result[key] = {
            "status": report.get("status"),
            "evidence_level": report.get("evidence_level"),
            "task_count": report.get("task_count"),
            "tasks": report.get("tasks"),
            "success_rate": summary.get("success_rate"),
            "completed": summary.get("completed"),
            "failed": summary.get("failed"),
            "failure_reason_counts": summary.get("failure_reason_counts"),
            "mean_tokens_per_task": summary.get("mean_tokens_per_task"),
            "mean_requests_per_task": summary.get("mean_requests_per_task"),
            "mean_score_completed_tasks": summary.get(
                "mean_score_completed_tasks"
            ),
            "may_claim_global_success_rate_repair": boundary.get(
                "may_claim_global_success_rate_repair"
            ),
            "may_update_execution_freeze_json": boundary.get(
                "may_update_execution_freeze_json"
            ),
        }
    return result


def _optional_report_list(
    value: Mapping[str, Any] | Sequence[Mapping[str, Any] | None] | None,
) -> list[Mapping[str, Any]]:
    if not value:
        return []
    if isinstance(value, Mapping):
        return [value]
    return [item for item in value if isinstance(item, Mapping)]


def _qor_measured_key(report: Mapping[str, Any]) -> str:
    label = report.get("run_label")
    if isinstance(label, str) and label:
        return f"qor_rag_small_ab:{label}"
    source_plan = report.get("source_plan")
    if isinstance(source_plan, str) and source_plan:
        return f"qor_rag_small_ab:{Path(source_plan).stem}"
    tasks = [
        str(item)
        for item in report.get("tasks", [])
        if isinstance(item, str) and item
    ]
    suffix = "_".join(tasks) if tasks else "additional"
    return f"qor_rag_small_ab:{suffix}"


def _failed_task_measured_key(report: Mapping[str, Any]) -> str:
    label = report.get("run_label")
    if isinstance(label, str) and label:
        return f"failed_task_small_sample:{label}"
    source_plan = report.get("source_plan")
    if isinstance(source_plan, str) and source_plan:
        return f"failed_task_small_sample:{Path(source_plan).stem}"
    tasks = [
        str(item)
        for item in report.get("tasks", [])
        if isinstance(item, str) and item
    ]
    suffix = "_".join(tasks) if tasks else "additional"
    return f"failed_task_small_sample:{suffix}"


def _qor_measured_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping(report.get("small_sample_summary"))
    boundary = _mapping(report.get("completion_boundary"))
    return {
        "status": report.get("status"),
        "evidence_level": report.get("evidence_level"),
        "run_label": report.get("run_label"),
        "task_count": report.get("task_count"),
        "tasks": report.get("tasks"),
        "candidate_success_rate": summary.get("candidate_success_rate"),
        "candidate_mean_tokens_per_task": summary.get(
            "candidate_mean_tokens_per_task"
        ),
        "candidate_mean_requests_per_task": summary.get(
            "candidate_mean_requests_per_task"
        ),
        "candidate_q_hw_geomean": summary.get("candidate_q_hw_geomean"),
        "q_hw_relative_change": summary.get("q_hw_relative_change"),
        "acceleration_relative_change": summary.get(
            "acceleration_relative_change"
        ),
        "may_claim_qor_repair": boundary.get("may_claim_qor_repair"),
        "may_update_execution_freeze_json": boundary.get(
            "may_update_execution_freeze_json"
        ),
    }


def _retrieval_summary(report: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    return {
        "case_count": report.get("case_count"),
        "hits_at_3": report.get("hits_at_3"),
        "recall_at_3": report.get("recall_at_3"),
        "passed": report.get("passed"),
        "deterministic": report.get("deterministic"),
        "max_prompt_token_upper_bound": report.get(
            "max_prompt_token_upper_bound"
        ),
    }


def _attempt_summaries(
    reports: Sequence[Mapping[str, Any] | None] | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not reports:
        return result
    for report in reports:
        if not isinstance(report, Mapping):
            continue
        key = _attempt_key(report)
        failure = _mapping(report.get("failure"))
        metrics = _mapping(report.get("metrics"))
        result[key] = {
            "status": report.get("status"),
            "evidence_level": report.get("evidence_level"),
            "task_count": report.get("task_count"),
            "tasks": report.get("tasks"),
            "lane_attempted": report.get("lane_attempted"),
            "candidate_lane_run": report.get("candidate_lane_run"),
            "failure_type": failure.get("type"),
            "failure_message": failure.get("message"),
            "mean_tokens_per_task": metrics.get("mean_tokens_per_task"),
            "mean_requests_per_task": metrics.get("mean_requests_per_task"),
            "success_rate": metrics.get("success_rate"),
            "may_claim_qor_repair": _get(
                report, "completion_boundary", "may_claim_qor_repair"
            ),
            "may_update_execution_freeze_json": _get(
                report, "completion_boundary", "may_update_execution_freeze_json"
            ),
        }
    return result


def _attempt_key(report: Mapping[str, Any]) -> str:
    label = report.get("run_label")
    lane = report.get("lane_attempted")
    if isinstance(label, str) and label:
        suffix = label
    else:
        suffix = str(report.get("purpose") or "attempt")
    if isinstance(lane, str) and lane:
        suffix = f"{suffix}:{lane}"
    return f"small_sample_attempt:{suffix}"


def _current_missing_evidence(
    *,
    small_ab_plan: Mapping[str, Any],
    qor_measured_reports: Sequence[Mapping[str, Any]],
    failed_task_measured_reports: Sequence[Mapping[str, Any]],
) -> list[str]:
    missing: list[str] = []
    planned_qor_tasks = [
        item.get("task_id")
        for item in small_ab_plan.get("selected_tasks", [])
        if isinstance(item, Mapping) and isinstance(item.get("task_id"), str)
    ]
    measured_qor_tasks = set(_measured_qor_tasks(qor_measured_reports))
    if planned_qor_tasks:
        unmeasured = [
            task_id for task_id in planned_qor_tasks if task_id not in measured_qor_tasks
        ]
        if unmeasured:
            missing.append(
                "QoR-RAG measured small A/B currently covers "
                f"{len(measured_qor_tasks)}/{len(planned_qor_tasks)} planned "
                f"priority tasks; remaining={unmeasured}"
            )
    elif not measured_qor_tasks:
        missing.append("QoR-RAG measured small A/B is missing")
    if not failed_task_measured_reports:
        missing.append("failed-task measured small sample is missing")
    missing.append(
        "execution-freeze.json must remain stale until an explicit fresh full199 acceptance"
    )
    return missing


def _measured_qor_tasks(reports: Sequence[Mapping[str, Any]]) -> list[str]:
    tasks: list[str] = []
    for report in reports:
        for task in report.get("tasks", []):
            if isinstance(task, str) and task not in tasks:
                tasks.append(task)
    return tasks


def _recommended_next_actions(
    *,
    current_missing_evidence: Sequence[str],
    qor_measured_reports: Sequence[Mapping[str, Any]],
    failed_task_measured_reports: Sequence[Mapping[str, Any]],
) -> list[str]:
    actions: list[str] = []
    if any("QoR-RAG measured small A/B" in item for item in current_missing_evidence):
        actions.append(
            "Run the remaining 1-3 task QoR-RAG small A/B plan and finalize it "
            "with tools/finalize_qor_rag_small_ab.py."
        )
    elif _qor_samples_show_unrepaired_regression(qor_measured_reports):
        actions.append(
            "Use the measured QoR small A/B reports to localize the remaining "
            "regression, especially tasks whose generalized q_hw relative "
            "change is negative or may_claim_qor_repair=false."
        )
    elif qor_measured_reports:
        actions.append(
            "Treat the measured QoR small A/B as supportive small-sample "
            "evidence only; formal QoR A/B is still required before claiming "
            "global repair."
        )

    if not failed_task_measured_reports:
        actions.append(
            "Run the failed-task 1-3 task sample plan and audit it with "
            "tools/finalize_failed_task_small_sample.py before claiming "
            "success-rate repair."
        )
    elif any(
        not _get(
            report,
            "acceptance_boundary",
            "may_claim_global_success_rate_repair",
        )
        for report in failed_task_measured_reports
    ):
        actions.append(
            "Use the failed-task measured sample to target the remaining "
            "interface/frequency failure classes before any larger acceptance run."
        )

    actions.append(
        "Keep execution-freeze.json unchanged until an explicit fresh full199 "
        "acceptance is completed."
    )
    return actions


def _qor_samples_show_unrepaired_regression(
    reports: Sequence[Mapping[str, Any]],
) -> bool:
    for report in reports:
        if _get(report, "completion_boundary", "may_claim_qor_repair") is False:
            return True
        q_hw_change = _get(report, "small_sample_summary", "q_hw_relative_change")
        if isinstance(q_hw_change, (int, float)) and q_hw_change < 0:
            return True
    return False


def _hardcoding_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    conclusion = _mapping(report.get("overall_conclusion"))
    scan = _mapping(report.get("literal_scan_summary"))
    return {
        "status": report.get("status"),
        "high_risk_task_answer_hardcoding_found": conclusion.get(
            "high_risk_task_answer_hardcoding_found"
        ),
        "generalized_runtime_ready": conclusion.get("generalized_runtime_ready"),
        "risk_counts": report.get("risk_counts"),
        "agent_runtime_task_id_literal_count": scan.get(
            "agent_runtime_task_id_literal_count",
            scan.get("agent_runtime_concrete_task_id_literal_count"),
        ),
        "agent_runtime_workload_literal_count": scan.get(
            "agent_runtime_workload_literal_count"
        ),
        "summary": conclusion.get("summary"),
    }


def _small_plan_summary(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": plan.get("status"),
        "evidence_level": plan.get("evidence_level"),
        "selected_task_count": plan.get("selected_task_count"),
        "selected_task_ids": [
            item.get("task_id")
            for item in plan.get("selected_tasks", [])
            if isinstance(item, Mapping)
        ],
        "measured_report_required": _get(
            plan, "sample_policy", "measured_report_required"
        ),
        "full199_allowed": _get(plan, "sample_policy", "full199_allowed"),
        "execution_freeze_update_allowed": _get(
            plan, "sample_policy", "execution_freeze_update_allowed"
        ),
        "finalize_command": _get(plan, "comparison", "command"),
    }


def _failed_plan_summary(plan: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not plan:
        return None
    return {
        "status": plan.get("status"),
        "evidence_level": plan.get("evidence_level"),
        "selected_task_count": plan.get("selected_task_count"),
        "selected_task_ids": [
            item.get("task_id")
            for item in plan.get("selected_tasks", [])
            if isinstance(item, Mapping)
        ],
        "selected_failure_reasons": [
            item.get("prior_failure_reason")
            for item in plan.get("selected_tasks", [])
            if isinstance(item, Mapping)
        ],
        "post_quarantine_success_rate": _get(
            plan, "offline_context", "post_quarantine_success_rate"
        ),
        "remaining_failure_count": _get(
            plan, "offline_context", "remaining_failure_count"
        ),
        "full199_allowed": _get(plan, "sample_policy", "full199_allowed"),
        "execution_freeze_update_allowed": _get(
            plan, "sample_policy", "execution_freeze_update_allowed"
        ),
        "run_command": _get(plan, "run", "command"),
        "audit_command": _get(plan, "audit", "command"),
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


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _append_number(values: list[float], value: Any) -> None:
    numeric = _num(value)
    if numeric is not None:
        values.append(numeric)


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 6) if values else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator, 6)


def _read_optional(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full199", type=Path, default=DEFAULT_FULL199)
    parser.add_argument("--formal-ab", type=Path, default=DEFAULT_FORMAL_AB)
    parser.add_argument("--hardcoding", type=Path, default=DEFAULT_HARDCODING)
    parser.add_argument("--triage", type=Path, default=DEFAULT_TRIAGE)
    parser.add_argument("--small-ab-plan", type=Path, default=DEFAULT_SMALL_AB_PLAN)
    parser.add_argument(
        "--qor-small-ab-measured",
        type=Path,
        default=DEFAULT_QOR_SMALL_AB_MEASURED,
    )
    parser.add_argument(
        "--extra-qor-small-ab-measured",
        action="append",
        type=Path,
        default=[],
        help=(
            "Optional additional QoR-RAG small A/B measured report. "
            "Use for isolated 1-task follow-up samples."
        ),
    )
    parser.add_argument(
        "--failed-task-plan", type=Path, default=DEFAULT_FAILED_TASK_PLAN
    )
    parser.add_argument(
        "--failed-task-measured",
        type=Path,
        default=DEFAULT_FAILED_TASK_MEASURED,
    )
    parser.add_argument(
        "--extra-failed-task-measured",
        action="append",
        type=Path,
        default=[],
        help=(
            "Optional additional failed-task measured report. "
            "Use for isolated 1-task follow-up samples."
        ),
    )
    parser.add_argument(
        "--small-sample-attempt-report",
        action="append",
        type=Path,
        default=[],
        help=(
            "Optional real small-sample attempt report, including preflight "
            "failures that are not measured A/B evidence."
        ),
    )
    parser.add_argument("--single-dot", type=Path, default=DEFAULT_SINGLE_DOT)
    parser.add_argument("--public-sample", type=Path, default=DEFAULT_PUBLIC_SAMPLE)
    parser.add_argument(
        "--retrieval-eval", type=Path, default=DEFAULT_RETRIEVAL_EVAL
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    qor_measured_reports = [_read_optional(args.qor_small_ab_measured)]
    qor_measured_reports.extend(
        _read_optional(path) for path in args.extra_qor_small_ab_measured
    )
    small_sample_attempts = [
        _read_optional(path) for path in args.small_sample_attempt_report
    ]
    failed_task_measured_reports = [_read_optional(args.failed_task_measured)]
    failed_task_measured_reports.extend(
        _read_optional(path) for path in args.extra_failed_task_measured
    )
    summary = build_summary(
        full199=json.loads(args.full199.read_text(encoding="utf-8")),
        formal_ab=json.loads(args.formal_ab.read_text(encoding="utf-8")),
        hardcoding=json.loads(args.hardcoding.read_text(encoding="utf-8")),
        triage=json.loads(args.triage.read_text(encoding="utf-8")),
        small_ab_plan=json.loads(args.small_ab_plan.read_text(encoding="utf-8")),
        failed_task_plan=_read_optional(args.failed_task_plan),
        qor_small_ab_measured=qor_measured_reports,
        failed_task_measured=failed_task_measured_reports,
        small_sample_attempts=small_sample_attempts,
        single_dot=_read_optional(args.single_dot),
        public_sample=_read_optional(args.public_sample),
        retrieval_eval=_read_optional(args.retrieval_eval),
    )
    rendered = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
