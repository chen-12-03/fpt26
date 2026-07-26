#!/usr/bin/env python3
"""Offline triage for QoR-RAG regressions and full-corpus failures.

This script consumes already-written aggregate JSON reports.  It does not read
private evaluator artifacts, launch Vitis, or call an LLM API.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


_REPO_ROOT = Path(__file__).resolve().parents[1]
_AGENT_ROOT = _REPO_ROOT / "fpt26-agent-v3"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from agent.analysis.source_metadata import (  # noqa: E402
    bounded_metadata_payload,
    extract_design_metadata,
)
from agent.knowledge import (  # noqa: E402
    KnowledgeEntry,
    KnowledgeQuery,
    format_for_prompt,
    prompt_token_upper_bound,
    retrieve_knowledge,
)


_MAX_PUBLIC_TEXT_CHARS = 300_000
_PUBLIC_FORBIDDEN_PARTS = {"hidden", "reference", "evaluator", "solution"}


def analyze_qor_rag_ab(
    report: Mapping[str, Any],
    *,
    task_root: Path | None = None,
    entries: Sequence[KnowledgeEntry] | None = None,
) -> dict[str, Any]:
    baseline = report.get("baseline", {})
    candidate = report.get("candidate", {})
    baseline_tasks = (
        baseline.get("tasks", {}) if isinstance(baseline, Mapping) else {}
    )
    candidate_tasks = (
        candidate.get("tasks", {}) if isinstance(candidate, Mapping) else {}
    )
    regressions = []
    improvements = []
    unchanged = []
    for task_id in sorted(set(baseline_tasks) & set(candidate_tasks)):
        base = baseline_tasks[task_id]
        cand = candidate_tasks[task_id]
        if not isinstance(base, Mapping) or not isinstance(cand, Mapping):
            continue
        delta = _task_delta(base, cand)
        record = {
            "task_id": task_id,
            **delta,
            "hypotheses": _qor_regression_hypotheses(delta),
            "next_offline_checks": [
                "inspect candidate and baseline knowledge_retrievals in raw submission run_report metadata",
                "diff accepted candidate pragmas/source against baseline final kernel",
                "check whether early stop or low measured-candidate count limited exploration",
            ],
        }
        if task_root is not None:
            record["offline_retrieval_replay"] = _replay_qor_retrieval(
                task_root,
                task_id,
                base,
                cand,
                entries=entries,
            )
        if delta["q_hw_delta"] < -1e-9 or delta["acceleration_delta"] < -1e-9:
            regressions.append(record)
        elif delta["q_hw_delta"] > 1e-9 or delta["acceleration_delta"] > 1e-9:
            improvements.append(record)
        else:
            unchanged.append(record)

    regressions.sort(
        key=lambda item: (
            item["q_hw_delta"],
            item["acceleration_relative_change"],
        )
    )
    return {
        "task_count": report.get("task_count"),
        "passed": report.get("passed"),
        "gates": report.get("gates"),
        "comparison": report.get("comparison"),
        "regression_count": len(regressions),
        "improvement_count": len(improvements),
        "unchanged_count": len(unchanged),
        "largest_regressions": regressions[:12],
        "priority_tasks": [
            task["task_id"]
            for task in regressions
            if task["task_id"]
            in {
                "machsuite__aes_aes",
                "machsuite__gemm_blocked",
                "polybench__cholesky",
            }
        ],
        "evidence_limitations": [
            "aggregate A/B report is enough for metric deltas but not final root-cause",
            "raw submission metadata is required to prove retrieval-vs-prompt-vs-early-stop cause",
        ],
    }


def analyze_full199_failures(
    report: Mapping[str, Any], *, task_root: Path | None = None
) -> dict[str, Any]:
    tasks = report.get("tasks", {})
    if not isinstance(tasks, Mapping):
        tasks = {}
    by_reason: Counter[str] = Counter()
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    failed_records = []
    for task_id, record in sorted(tasks.items()):
        if not isinstance(record, Mapping):
            continue
        if record.get("outcome") == "completed":
            continue
        reason = _stop_reason(record)
        family = _family(task_id, bool(record.get("official_task")))
        by_reason[reason] += 1
        by_family[family][reason] += 1
        failed_records.append(
            {
                "task_id": task_id,
                "family": family,
                "reason": reason,
                "triage_class": _failure_triage_class(reason, family),
            }
        )
    priority = [
        record
        for record in failed_records
        if record["family"] == "amd_accel"
        and record["reason"] == "anchor_invalid: starter"
    ][:8]
    static_audits = []
    if task_root is not None:
        static_audits = [
            _static_anchor_audit(task_root, item["task_id"])
            for item in priority
        ]
    public_hls_metric_completeness = (
        _public_hls_metric_completeness(task_root, failed_records)
        if task_root is not None
        else {}
    )
    return {
        "expected_task_count": (report.get("coverage") or {}).get(
            "expected_task_count"
        ),
        "failure_count": len(failed_records),
        "failure_reason_counts": dict(sorted(by_reason.items())),
        "family_reason_counts": {
            family: dict(counter)
            for family, counter in sorted(by_family.items())
        },
        "priority_static_audit_samples": priority,
        "priority_static_audits": static_audits,
        "public_hls_metric_completeness": public_hls_metric_completeness,
        "suggested_small_sample_tasks": [
            item["task_id"] for item in priority[:3]
        ],
        "triage_notes": {
            "anchor_invalid: starter": (
                "audit imported starter/reference/anchor validity before "
                "changing prompt behavior"
            ),
            "frequency_failed": (
                "inspect achieved clock and candidate pragmas; likely target "
                "gate or over-parallelization issue"
            ),
            "interface_failed": (
                "inspect top signature, generated wrappers, and task.toml "
                "interface contract"
            ),
        },
    }


def analyze_post_quarantine_failures(
    report: Mapping[str, Any],
    quarantine_report: Mapping[str, Any] | None = None,
    *,
    excluded_task_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Summarize the residual failure surface after static task quarantine."""

    excluded = set(excluded_task_ids or [])
    if quarantine_report is not None:
        excluded.update(_quarantine_task_ids(quarantine_report))
    tasks = report.get("tasks", {})
    if not isinstance(tasks, Mapping):
        tasks = {}

    failed_records = _failure_records(tasks)
    remaining = [
        record for record in failed_records if record["task_id"] not in excluded
    ]
    excluded_failures = [
        record for record in failed_records if record["task_id"] in excluded
    ]
    by_reason: Counter[str] = Counter(record["reason"] for record in remaining)
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    for record in remaining:
        by_family[record["family"]][record["reason"]] += 1

    completed_count = sum(
        1
        for record in tasks.values()
        if isinstance(record, Mapping) and record.get("outcome") == "completed"
    )
    remaining_task_count = max(len(tasks) - len(excluded), 0)
    suggestions = _post_quarantine_suggestions(remaining)
    return {
        "excluded_task_count": len(excluded),
        "excluded_failed_task_count": len(excluded_failures),
        "remaining_task_count": remaining_task_count,
        "completed_count": completed_count,
        "remaining_failure_count": len(remaining),
        "estimated_success_rate_after_quarantine": (
            completed_count / remaining_task_count
            if remaining_task_count
            else None
        ),
        "failure_reason_counts": dict(sorted(by_reason.items())),
        "family_reason_counts": {
            family: dict(counter) for family, counter in sorted(by_family.items())
        },
        "remaining_failures": remaining,
        "suggested_small_sample_tasks": [
            item["task_id"] for item in suggestions[:3]
        ],
        "suggested_small_sample_records": suggestions,
        "triage_notes": {
            "markdown_fence_in_candidate": (
                "generic candidate extraction/sanitization issue; verify with "
                "one interface-failed task before touching optimizer policy"
            ),
            "candidate_clock_invalid": (
                "clock/frequency gate saw invalid or zero clock; inspect synth "
                "metric extraction and empty/constant datapath cases"
            ),
            "true_frequency_miss": (
                "candidate synthesized but missed 100 MHz; prioritize the "
                "closest miss to test clock-aware acceptance"
            ),
            "residual_anchor_invalid": (
                "not explained by metric-incomplete quarantine; audit starter "
                "anchor provenance before changing prompt behavior"
            ),
        },
    }


def _replay_qor_retrieval(
    task_root: Path,
    task_id: str,
    baseline_record: Mapping[str, Any],
    candidate_record: Mapping[str, Any],
    *,
    entries: Sequence[KnowledgeEntry] | None = None,
) -> dict[str, Any]:
    package = _read_public_task_package(task_root, task_id)
    if "error" in package:
        return {
            "available": False,
            "error": package["error"],
            "policy": "public task package only; no Vitis, LLM, hidden, or reference reads",
        }

    source_text = str(package.get("source_text", ""))
    metadata = bounded_metadata_payload(
        extract_design_metadata(source_text), max_chars=2_000
    )
    query = KnowledgeQuery(
        source_metadata=metadata,
        baseline_qor={
            "q_hw": _num(candidate_record.get("q_hw"))
            or _num(baseline_record.get("q_hw")),
            "acceleration": _num(candidate_record.get("acceleration")),
            "loop_metrics": [],
            "clock_period_ns": (
                package.get("target", {}).get("clock_ns")
                if isinstance(package.get("target"), Mapping)
                else None
            ),
            "bottleneck": "aggregate_report_only",
        },
        synth_diagnostics={
            "summary": (
                "offline aggregate replay has no raw synth loop report; "
                "retrieval is driven by public source metadata and description"
            )
        },
        resource_headroom={},
        history=[],
        description=_retrieval_description(package),
        target_part=str(
            package.get("target", {}).get("part", "")
            if isinstance(package.get("target"), Mapping)
            else ""
        ),
        vitis_version="2025.2",
        task_id=task_id,
    )
    return {
        "available": True,
        "policy": "public task package only; no Vitis, LLM, hidden, or reference reads",
        "public_files_read": package.get("public_files_read", []),
        "source_metadata_summary": {
            "parse_status": metadata.get("parse_status"),
            "loop_count": metadata.get("loop_count"),
            "array_count": metadata.get("array_count"),
        },
        "modes": {
            "default": _retrieval_mode_record(
                query,
                task_id,
                generalized=False,
                entries=entries,
            ),
            "generalized": _retrieval_mode_record(
                query,
                task_id,
                generalized=True,
                entries=entries,
            ),
        },
        "hypothesis_evidence": _offline_qor_hypothesis_evidence(
            baseline_record,
            candidate_record,
        ),
    }


def analyze_phase2f_objective_status(
    qor_analysis: Mapping[str, Any],
    post_quarantine: Mapping[str, Any],
) -> dict[str, Any]:
    """Summarize which Phase 2F objectives are proven offline vs still open."""

    priority_expectations = {
        "machsuite__aes_aes": "hlsgen.crypto.lookup_round_guard",
        "polybench__cholesky": (
            "hlsgen.linear_algebra.factorization_dependency_guard"
        ),
        "machsuite__gemm_blocked": "hlsgen.gemm.tiled_reuse",
    }
    regressions = qor_analysis.get("largest_regressions", [])
    if not isinstance(regressions, Sequence):
        regressions = []

    priority_records = []
    for task_id, expected_rule in priority_expectations.items():
        record = next(
            (
                item
                for item in regressions
                if isinstance(item, Mapping) and item.get("task_id") == task_id
            ),
            None,
        )
        priority_records.append(
            _priority_qor_repair_status(task_id, expected_rule, record)
        )

    offline_clean = [
        item
        for item in priority_records
        if item["generalized_exact_source_measured_case_count"] == 0
    ]
    offline_covered = [
        item
        for item in priority_records
        if item["status"] == "offline_prompt_coverage_ready"
    ]
    small_samples = [
        item["task_id"]
        for item in priority_records
        if item["requires_real_small_ab"]
    ]
    post_samples = post_quarantine.get("suggested_small_sample_tasks", [])
    if not isinstance(post_samples, list):
        post_samples = []

    return {
        "schema_version": 1,
        "qor_rag_generalized_offline": {
            "priority_task_count": len(priority_records),
            "exact_source_clean_count": len(offline_clean),
            "offline_prompt_coverage_ready_count": len(offline_covered),
            "records": priority_records,
            "measured_qor_repair_proven": False,
            "remaining_required_evidence": (
                "1-task generalized-RAG real API/Vitis A/B for each priority "
                "regression before claiming QoR recovery"
            ),
            "suggested_qor_small_ab_tasks": small_samples,
        },
        "failed_task_success_rate_offline": {
            "post_quarantine_success_rate": post_quarantine.get(
                "estimated_success_rate_after_quarantine"
            ),
            "remaining_failure_count": post_quarantine.get(
                "remaining_failure_count"
            ),
            "suggested_failure_small_sample_tasks": [
                str(item) for item in post_samples[:3]
            ],
            "measured_success_rate_repair_proven": False,
        },
        "completion": {
            "objective_complete": False,
            "blocking_missing_evidence": [
                "expanded QoR-RAG regressions have offline prompt coverage but no fresh measured small A/B",
                "post-quarantine success-rate improvement is an offline estimate, not a fresh acceptance",
                "execution-freeze.json must remain stale until an explicit fresh full199 acceptance",
            ],
        },
    }


def _priority_qor_repair_status(
    task_id: str,
    expected_rule: str,
    record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if record is None:
        return {
            "task_id": task_id,
            "expected_generalized_rule": expected_rule,
            "status": "missing_from_qor_regression_report",
            "generalized_retrieved_ids": [],
            "generalized_exact_source_measured_case_count": None,
            "requires_real_small_ab": True,
        }
    replay = record.get("offline_retrieval_replay", {})
    generalized = (
        replay.get("modes", {}).get("generalized", {})
        if isinstance(replay, Mapping)
        else {}
    )
    if not isinstance(generalized, Mapping):
        generalized = {}
    retrieved = [
        str(item)
        for item in generalized.get("retrieved_ids", [])
        if isinstance(item, str)
    ]
    exact_count = generalized.get("exact_source_measured_case_count")
    status = "needs_retrieval_repair"
    if exact_count not in (0, None):
        status = "generalized_exact_source_risk"
    elif retrieved and retrieved[0] == expected_rule:
        status = "offline_prompt_coverage_ready"
    return {
        "task_id": task_id,
        "expected_generalized_rule": expected_rule,
        "status": status,
        "generalized_retrieved_ids": retrieved,
        "generalized_exact_source_measured_case_count": exact_count,
        "q_hw_delta": record.get("q_hw_delta"),
        "acceleration_delta": record.get("acceleration_delta"),
        "hypotheses": record.get("hypotheses", []),
        "requires_real_small_ab": True,
    }


def _failure_records(tasks: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = []
    for task_id, record in sorted(tasks.items()):
        if not isinstance(record, Mapping):
            continue
        if record.get("outcome") == "completed":
            continue
        reason = _stop_reason(record)
        family = _family(task_id, bool(record.get("official_task")))
        records.append(
            {
                "task_id": task_id,
                "family": family,
                "reason": reason,
                "triage_class": _failure_triage_class(reason, family),
                "gate_evidence": _failure_gate_evidence(record),
            }
        )
    return records


def _failure_gate_evidence(record: Mapping[str, Any]) -> dict[str, Any]:
    submission = (
        record.get("submission") if isinstance(record.get("submission"), Mapping) else {}
    )
    evaluator = (
        record.get("evaluator") if isinstance(record.get("evaluator"), Mapping) else {}
    )
    submission_gates = (
        submission.get("gates") if isinstance(submission.get("gates"), Mapping) else {}
    )
    evaluator_gates = (
        evaluator.get("gates") if isinstance(evaluator.get("gates"), Mapping) else {}
    )
    final_hw = (
        submission.get("final_hardware")
        if isinstance(submission.get("final_hardware"), Mapping)
        else {}
    )
    token_usage = (
        submission.get("token_usage")
        if isinstance(submission.get("token_usage"), Mapping)
        else {}
    )
    return {
        "submission": {
            "status": submission.get("status"),
            "stop_reason": submission.get("stop_reason"),
            "interface": _gate_subset(
                submission_gates.get("interface"), ("ok", "reason", "stage")
            ),
            "frequency_100mhz": _gate_subset(
                submission_gates.get("frequency_100mhz"),
                (
                    "ok",
                    "reason",
                    "candidate_clock_ns",
                    "frequency_mhz",
                    "minimum_frequency_mhz",
                    "target_clock_ns",
                ),
            ),
            "resource_capacity": _gate_subset(
                submission_gates.get("resource_capacity"),
                ("ok", "reason", "resources", "available"),
            ),
            "public_acceptance": _gate_subset(
                submission_gates.get("public_acceptance"), ("ok", "failures")
            ),
            "token_usage": _gate_subset(
                token_usage,
                (
                    "complete",
                    "request_count",
                    "prompt_tokens",
                    "completion_tokens",
                    "total_tokens",
                ),
            ),
        },
        "evaluator": {
            "status": evaluator.get("status"),
            "stop_reason": evaluator.get("stop_reason"),
            "grading": _gate_subset(
                evaluator.get("grading"),
                ("source", "hidden_available", "is_fallback"),
            ),
            "evaluator_acceptance": _gate_subset(
                evaluator_gates.get("evaluator_acceptance"),
                (
                    "ok",
                    "failures",
                    "anchor_source",
                    "anchor_valid",
                    "grading_source",
                    "hidden_available",
                ),
            ),
            "interface": _gate_subset(
                evaluator_gates.get("interface"), ("ok", "reason", "stage")
            ),
            "frequency_100mhz": _gate_subset(
                evaluator_gates.get("frequency_100mhz"),
                (
                    "ok",
                    "reason",
                    "candidate_clock_ns",
                    "frequency_mhz",
                    "minimum_frequency_mhz",
                    "target_clock_ns",
                ),
            ),
        },
        "final_hardware": _gate_subset(
            final_hw,
            (
                "stage",
                "clock_period_ns",
                "frequency_mhz",
                "latency_worst",
                "interval_max",
                "resources",
            ),
        ),
    }


def _gate_subset(value: Any, keys: Sequence[str]) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {key: value.get(key) for key in keys if key in value}


def _quarantine_task_ids(report: Mapping[str, Any]) -> set[str]:
    for key in (
        "exclude_task_ids",
        "metric_incomplete_task_ids",
        "excluded_task_ids",
    ):
        value = report.get(key)
        if isinstance(value, list):
            return {str(item) for item in value if isinstance(item, str)}

    full199 = report.get("full199_failures")
    if isinstance(full199, Mapping):
        completeness = full199.get("public_hls_metric_completeness")
        if isinstance(completeness, Mapping):
            value = completeness.get("metric_incomplete_task_ids")
            if isinstance(value, list):
                return {str(item) for item in value if isinstance(item, str)}

    completeness = report.get("public_hls_metric_completeness")
    if isinstance(completeness, Mapping):
        value = completeness.get("metric_incomplete_task_ids")
        if isinstance(value, list):
            return {str(item) for item in value if isinstance(item, str)}
    return set()


def _post_quarantine_suggestions(
    records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []

    markdown = _first_by_interface_reason(records, "markdown_fence_in_candidate")
    if markdown is not None:
        suggestions.append(
            _suggestion_record(
                markdown,
                "interface_markdown_fence",
                "candidate extraction/sanitization can be fixed generically",
            )
        )

    true_frequency = _closest_true_frequency_miss(records)
    if true_frequency is not None:
        suggestions.append(
            _suggestion_record(
                true_frequency,
                "true_frequency_miss",
                "closest synthesized clock miss is the cheapest clock-policy probe",
            )
        )

    clock_invalid = _first_by_frequency_reason(records, "candidate_clock_invalid")
    if clock_invalid is not None:
        suggestions.append(
            _suggestion_record(
                clock_invalid,
                "candidate_clock_invalid",
                "zero/invalid clock cluster needs metric-extraction diagnosis",
            )
        )

    anchor = next(
        (
            record
            for record in records
            if record.get("reason") == "anchor_invalid: starter"
        ),
        None,
    )
    if anchor is not None:
        suggestions.append(
            _suggestion_record(
                anchor,
                "residual_anchor_invalid",
                "remaining starter-anchor failures are not covered by metric quarantine",
            )
        )
    return suggestions


def _first_by_interface_reason(
    records: Sequence[Mapping[str, Any]], reason: str
) -> Mapping[str, Any] | None:
    for record in records:
        interface = (
            (record.get("gate_evidence") or {})
            .get("submission", {})
            .get("interface")
        )
        if isinstance(interface, Mapping) and interface.get("reason") == reason:
            return record
    return None


def _first_by_frequency_reason(
    records: Sequence[Mapping[str, Any]], reason: str
) -> Mapping[str, Any] | None:
    for record in records:
        frequency = (
            (record.get("gate_evidence") or {})
            .get("submission", {})
            .get("frequency_100mhz")
        )
        if isinstance(frequency, Mapping) and frequency.get("reason") == reason:
            return record
    return None


def _closest_true_frequency_miss(
    records: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    candidates = []
    for record in records:
        if record.get("reason") != "frequency_failed":
            continue
        frequency = (
            (record.get("gate_evidence") or {})
            .get("submission", {})
            .get("frequency_100mhz")
        )
        if not isinstance(frequency, Mapping):
            continue
        if frequency.get("reason") == "candidate_clock_invalid":
            continue
        mhz = _num(frequency.get("frequency_mhz"))
        minimum = _num(frequency.get("minimum_frequency_mhz"))
        if mhz <= 0 or minimum <= 0 or mhz >= minimum:
            continue
        candidates.append((minimum - mhz, record))
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1] if candidates else None


def _suggestion_record(
    record: Mapping[str, Any], category: str, rationale: str
) -> dict[str, Any]:
    return {
        "task_id": record.get("task_id"),
        "family": record.get("family"),
        "reason": record.get("reason"),
        "category": category,
        "rationale": rationale,
        "gate_evidence": record.get("gate_evidence"),
    }


def _retrieval_mode_record(
    query: KnowledgeQuery,
    task_id: str,
    *,
    generalized: bool,
    entries: Sequence[KnowledgeEntry] | None,
) -> dict[str, Any]:
    matches = retrieve_knowledge(query, entries=entries, generalized=generalized)
    prompt_text = format_for_prompt(matches)
    summaries = [_knowledge_entry_summary(entry, task_id) for entry in matches]
    return {
        "generalized": generalized,
        "retrieved_ids": [item["id"] for item in summaries],
        "families": [item["family"] for item in summaries],
        "sources": [item["source"] for item in summaries],
        "entries": summaries,
        "measured_case_count": sum(
            1 for item in summaries if item["kind"] != "rule"
        ),
        "exact_source_measured_case_count": sum(
            1
            for item in summaries
            if item["kind"] != "rule" and item["source_matches_task"]
        ),
        "prompt_token_upper_bound": prompt_token_upper_bound(prompt_text),
    }


def _knowledge_entry_summary(
    entry: KnowledgeEntry, task_id: str
) -> dict[str, Any]:
    return {
        "id": entry.id,
        "kind": entry.kind,
        "family": entry.family,
        "status": entry.status,
        "source": entry.source,
        "tags": list(entry.tags[:12]),
        "source_matches_task": _source_matches_task(entry.source, task_id),
    }


def _source_matches_task(source: str, task_id: str) -> bool:
    source_tokens = _normalized_tokens(source)
    task_tokens = _normalized_tokens(task_id)
    if not task_tokens:
        return False
    compact_source = "".join(sorted(source_tokens))
    compact_task = "".join(sorted(task_tokens))
    return bool(
        task_tokens <= source_tokens
        or compact_task in compact_source
        or _normalize_identifier(task_id) in _normalize_identifier(source)
    )


def _offline_qor_hypothesis_evidence(
    baseline_record: Mapping[str, Any],
    candidate_record: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_tokens = _num(baseline_record.get("tokens"))
    candidate_tokens = _num(candidate_record.get("tokens"))
    baseline_credits = _num(baseline_record.get("credits"))
    candidate_credits = _num(candidate_record.get("credits"))
    baseline_acc = _num(baseline_record.get("acceleration"))
    candidate_acc = _num(candidate_record.get("acceleration"))
    return {
        "token_delta": candidate_tokens - baseline_tokens,
        "token_relative_change": _relative(baseline_tokens, candidate_tokens),
        "credit_delta": candidate_credits - baseline_credits,
        "credit_relative_change": _relative(baseline_credits, candidate_credits),
        "wasted_attempt_delta": int(candidate_record.get("wasted_attempts") or 0)
        - int(baseline_record.get("wasted_attempts") or 0),
        "acceleration_relative_change": _relative(baseline_acc, candidate_acc),
        "signals": [
            signal
            for signal, enabled in {
                "low_token_conservative_behavior": (
                    baseline_tokens > 0
                    and candidate_tokens < baseline_tokens * 0.8
                ),
                "lower_credit_under_exploration": (
                    baseline_credits > 0
                    and candidate_credits < baseline_credits
                ),
                "missed_strategy_lane": (
                    baseline_acc > 0 and candidate_acc < baseline_acc * 0.8
                ),
                "same_or_fewer_wasted_attempts": int(
                    candidate_record.get("wasted_attempts") or 0
                )
                <= int(baseline_record.get("wasted_attempts") or 0),
            }.items()
            if enabled
        ],
    }


def _static_anchor_audit(task_root: Path, task_id: str) -> dict[str, Any]:
    package = _read_public_task_package(task_root, task_id)
    if "error" in package:
        return {
            "task_id": task_id,
            "available": False,
            "error": package["error"],
            "policy": "public task package only; no Vitis, LLM, hidden, or reference reads",
        }
    top = str(package.get("top", "") or "")
    kernel = str(package.get("kernel_text", ""))
    headers = str(package.get("header_text", ""))
    public_tb = str(package.get("public_tb_text", ""))
    public_text = "\n".join([kernel, headers, public_tb])
    provenance = package.get("provenance", {})
    generated_tb = (
        bool(provenance.get("generated_testbench"))
        if isinstance(provenance, Mapping)
        else False
    )
    top_in_kernel = _function_decl_or_def_present(kernel, top)
    top_in_header = _function_decl_or_def_present(headers, top)
    tb_calls_top = _call_present(public_tb, top)
    tb_has_check = _testbench_has_result_check(public_tb)
    host_markers = _host_runtime_markers(public_text)
    kernel_host_markers = _host_runtime_markers(kernel)
    tripcount = _tripcount_static_summary(kernel)
    issues = [
        issue
        for issue, enabled in {
            "top_not_found_in_kernel_or_header": not (
                top_in_kernel or top_in_header
            ),
            "public_tb_does_not_call_top": not tb_calls_top,
            "generated_public_tb_has_no_observable_result_check": (
                generated_tb and not tb_has_check
            ),
            "kernel_contains_host_runtime_markers": bool(kernel_host_markers),
            "variable_bound_loops_without_tripcount": (
                tripcount["variable_bound_loop_count"] > 0
                and tripcount["loop_tripcount_pragma_count"] == 0
            ),
        }.items()
        if enabled
    ]
    return {
        "task_id": task_id,
        "available": True,
        "policy": "public task package only; no Vitis, LLM, hidden, or reference reads",
        "public_files_read": package.get("public_files_read", []),
        "top": top,
        "kernel_file": package.get("kernel_file"),
        "public_tb": package.get("public_tb"),
        "headers": package.get("header_files", []),
        "top_in_kernel": top_in_kernel,
        "top_in_header": top_in_header,
        "public_tb_calls_top": tb_calls_top,
        "public_tb_has_result_check": tb_has_check,
        "generated_public_tb": generated_tb,
        "host_runtime_markers": host_markers,
        "kernel_host_runtime_markers": kernel_host_markers,
        "tripcount_static_summary": tripcount,
        "provenance": _public_provenance_summary(provenance),
        "issues": issues,
        "anchor_hypothesis": _anchor_hypothesis(issues),
    }


def _task_delta(base: Mapping[str, Any], cand: Mapping[str, Any]) -> dict[str, Any]:
    base_q = _num(base.get("q_hw"))
    cand_q = _num(cand.get("q_hw"))
    base_acc = _num(base.get("acceleration"))
    cand_acc = _num(cand.get("acceleration"))
    base_tokens = _num(base.get("tokens"))
    cand_tokens = _num(cand.get("tokens"))
    base_credits = _num(base.get("credits"))
    cand_credits = _num(cand.get("credits"))
    return {
        "baseline_q_hw": base_q,
        "candidate_q_hw": cand_q,
        "q_hw_delta": cand_q - base_q,
        "q_hw_relative_change": _relative(base_q, cand_q),
        "baseline_acceleration": base_acc,
        "candidate_acceleration": cand_acc,
        "acceleration_delta": cand_acc - base_acc,
        "acceleration_relative_change": _relative(base_acc, cand_acc),
        "baseline_tokens": base_tokens,
        "candidate_tokens": cand_tokens,
        "tokens_relative_change": _relative(base_tokens, cand_tokens),
        "baseline_credits": base_credits,
        "candidate_credits": cand_credits,
        "credits_relative_change": _relative(base_credits, cand_credits),
        "baseline_wasted_attempts": int(base.get("wasted_attempts") or 0),
        "candidate_wasted_attempts": int(cand.get("wasted_attempts") or 0),
    }


def _qor_regression_hypotheses(delta: Mapping[str, Any]) -> list[str]:
    hypotheses = []
    if delta["tokens_relative_change"] < -0.05:
        hypotheses.append("prompt_or_retrieval_became_more_conservative")
    if delta["candidate_wasted_attempts"] <= delta["baseline_wasted_attempts"]:
        hypotheses.append("early_stop_or_under_exploration_possible")
    if delta["acceleration_relative_change"] < -0.20:
        hypotheses.append("missed_parallel_architecture_or_strategy_lane")
    if delta["q_hw_relative_change"] < -0.01 and delta["candidate_credits"] <= delta["baseline_credits"]:
        hypotheses.append("lower_tool_spend_correlates_with_lower_qor")
    return hypotheses or ["metric_regression_requires_raw_metadata_inspection"]


def _stop_reason(record: Mapping[str, Any]) -> str:
    evaluator = record.get("evaluator") if isinstance(record.get("evaluator"), Mapping) else {}
    submission = record.get("submission") if isinstance(record.get("submission"), Mapping) else {}
    return str(
        evaluator.get("stop_reason")
        or submission.get("stop_reason")
        or record.get("outcome")
        or "unknown"
    )


def _family(task_id: str, official: bool) -> str:
    if official:
        return "official"
    return task_id.split("__", 1)[0] if "__" in task_id else "generated_other"


def _failure_triage_class(reason: str, family: str) -> str:
    if reason == "anchor_invalid: starter":
        return (
            "public_hls_import_or_anchor_validation"
            if family.startswith("amd_")
            else "starter_anchor_invalid"
        )
    if reason == "frequency_failed":
        return "frequency_gate_or_over_parallelization"
    if reason == "interface_failed":
        return "interface_contract_or_wrapper"
    return "other"


def _read_public_task_package(task_root: Path, task_id: str) -> dict[str, Any]:
    task_dir = _resolve_task_dir(task_root, task_id)
    if task_dir is None:
        return {"error": f"task directory not found for {task_id}"}
    toml_path = task_dir / "task.toml"
    try:
        spec = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return {"error": f"invalid task.toml: {exc}"}

    kernel_file = spec.get("kernel_file")
    public_tb = spec.get("public_tb")
    header_files = spec.get("header_files", [])
    if not isinstance(kernel_file, str) or not isinstance(public_tb, str):
        return {"error": "task.toml missing kernel_file or public_tb"}
    if not isinstance(header_files, list) or not all(
        isinstance(item, str) for item in header_files
    ):
        return {"error": "task.toml header_files must be a list of strings"}

    public_files_read = ["task.toml"]
    description = _safe_public_read(task_dir, "description.md", required=False)
    if description is not None:
        public_files_read.append("description.md")
    kernel_text = _safe_public_read(task_dir, kernel_file, required=True)
    public_tb_text = _safe_public_read(task_dir, public_tb, required=True)
    if isinstance(kernel_text, dict):
        return kernel_text
    if isinstance(public_tb_text, dict):
        return public_tb_text
    public_files_read.extend([kernel_file, public_tb])

    headers: dict[str, str] = {}
    for header in header_files:
        text = _safe_public_read(task_dir, header, required=True)
        if isinstance(text, dict):
            return text
        headers[header] = text
        public_files_read.append(header)

    target = spec.get("target", {})
    provenance = spec.get("provenance", {})
    source_text = "\n".join(
        [kernel_text, *headers.values(), public_tb_text]
    )[:_MAX_PUBLIC_TEXT_CHARS]
    return {
        "task_dir": str(task_dir),
        "task_id": str(spec.get("task_id") or task_id),
        "top": str(spec.get("top", "") or ""),
        "initial_condition": str(spec.get("initial_condition", "") or ""),
        "target": target if isinstance(target, Mapping) else {},
        "provenance": provenance if isinstance(provenance, Mapping) else {},
        "description": description or "",
        "kernel_file": kernel_file,
        "kernel_text": kernel_text,
        "public_tb": public_tb,
        "public_tb_text": public_tb_text,
        "header_files": list(header_files),
        "header_text": "\n".join(headers.values()),
        "source_text": source_text,
        "public_files_read": sorted(set(public_files_read)),
    }


def _resolve_task_dir(task_root: Path, task_id: str) -> Path | None:
    candidates = [
        task_root / task_id,
        task_root / "generated" / task_id,
    ]
    if task_root.name == "generated":
        candidates.insert(0, task_root / task_id)
    for candidate in candidates:
        if (candidate / "task.toml").is_file():
            return candidate.resolve()
    return None


def _safe_public_read(
    task_dir: Path, name: str, *, required: bool
) -> str | dict[str, Any] | None:
    if not isinstance(name, str) or not name.strip():
        if required:
            return {"error": "empty public filename"}
        return None
    relative = Path(name)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        return {"error": f"unsafe public filename: {name}"}
    if set(part.lower() for part in relative.parts) & _PUBLIC_FORBIDDEN_PARTS:
        return {"error": f"forbidden public filename component: {name}"}
    path = (task_dir / relative).resolve()
    try:
        path.relative_to(task_dir.resolve())
    except ValueError:
        return {"error": f"public filename escapes task directory: {name}"}
    if not path.is_file():
        if required:
            return {"error": f"public file not found: {name}"}
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:_MAX_PUBLIC_TEXT_CHARS]


def _retrieval_description(package: Mapping[str, Any]) -> str:
    parts = [
        str(package.get("description", "") or ""),
        str(package.get("initial_condition", "") or ""),
        "top " + str(package.get("top", "") or ""),
    ]
    provenance = package.get("provenance", {})
    if isinstance(provenance, Mapping):
        source_path = provenance.get("source_path")
        if source_path:
            parts.append("public source path " + str(source_path))
    return "\n".join(part for part in parts if part.strip())[:12_000]


def _function_decl_or_def_present(source: str, name: str) -> bool:
    if not name:
        return False
    return re.search(
        rf"(?:^|[\s;{{}}])(?:extern\s+\"C\"\s*)?(?:[A-Za-z_]\w*(?:::\w+)?[\s*&]+)+"
        rf"{re.escape(name)}\s*\(",
        source,
        flags=re.MULTILINE,
    ) is not None


def _call_present(source: str, name: str) -> bool:
    if not name:
        return False
    return re.search(rf"\b{re.escape(name)}\s*\(", source) is not None


def _testbench_has_result_check(source: str) -> bool:
    lowered = source.lower()
    if any(token in lowered for token in ("assert(", "return 1", "fail", "mismatch")):
        return True
    if re.search(r"\bif\s*\([^)]*(?:!=|==|<|>)", source):
        return True
    if re.search(r"\bfor\s*\(", source) and re.search(r"\b(expected|gold|ref|check)\b", lowered):
        return True
    return False


def _host_runtime_markers(source: str) -> list[str]:
    markers = []
    checks = {
        "xrt_runtime": ("xrt::", "xrt/", "experimental/xrt"),
        "opencl_runtime": ("cl::", "cl2.hpp", "CL/cl", "xcl2.hpp"),
        "host_api": ("xclbin", "enqueueTask", "enqueueMigrateMemObjects"),
    }
    for label, needles in checks.items():
        if any(needle in source for needle in needles):
            markers.append(label)
    return markers


def _tripcount_static_summary(source: str) -> dict[str, int]:
    clean = re.sub(r"//.*?$|/\*.*?\*/", "", source, flags=re.MULTILINE | re.DOTALL)
    loop_headers = re.findall(r"\bfor\s*\(([^;]*);([^;]*);([^)]*)\)", clean)
    variable_bound = 0
    for _init, condition, _increment in loop_headers:
        if not re.search(r"[<>]=?\s*[+-]?\d+\b", condition):
            variable_bound += 1
    return {
        "for_loop_count": len(loop_headers),
        "variable_bound_loop_count": variable_bound,
        "loop_tripcount_pragma_count": len(
            re.findall(r"#\s*pragma\s+HLS\s+LOOP_TRIPCOUNT\b", clean)
        ),
    }


def _public_hls_metric_completeness(
    task_root: Path, failed_records: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    manifest_path = _public_hls_manifest_path(task_root)
    if manifest_path is None:
        return {"available": False, "error": "public HLS validated manifest not found"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "error": f"invalid manifest: {exc}"}
    validated = manifest.get("validated", [])
    if not isinstance(validated, list):
        return {"available": False, "error": "manifest validated field is not a list"}
    metric_incomplete = []
    for record in validated:
        if not isinstance(record, Mapping):
            continue
        task_id = str(record.get("task_id", "") or "")
        if not task_id:
            continue
        latency_ok = record.get("latency_worst") is not None
        interval_ok = (
            record.get("interval_max") is not None
            if "interval_max" in record
            else True
        )
        scoreable_ok = record.get("scoreable_synth_ok")
        if scoreable_ok is None:
            scoreable_ok = latency_ok and interval_ok
        if scoreable_ok is not True:
            metric_incomplete.append(
                {
                    "task_id": task_id,
                    "source": record.get("source"),
                    "latency_worst": record.get("latency_worst"),
                    "interval_max": record.get("interval_max"),
                }
            )
    failed_anchor = {
        str(record.get("task_id"))
        for record in failed_records
        if record.get("reason") == "anchor_invalid: starter"
    }
    metric_ids = {item["task_id"] for item in metric_incomplete}
    overlap = sorted(metric_ids & failed_anchor)
    tripcount_patch_candidates = []
    for item in metric_incomplete:
        task_id = item["task_id"]
        package = _read_public_task_package(task_root, task_id)
        if "error" in package:
            continue
        tripcount = _tripcount_static_summary(str(package.get("kernel_text", "")))
        if (
            tripcount["variable_bound_loop_count"] > 0
            and tripcount["loop_tripcount_pragma_count"] == 0
        ):
            tripcount_patch_candidates.append(
                {
                    "task_id": task_id,
                    "source": item.get("source"),
                    "for_loop_count": tripcount["for_loop_count"],
                    "variable_bound_loop_count": tripcount[
                        "variable_bound_loop_count"
                    ],
                }
            )
    by_source: Counter[str] = Counter(
        str(item.get("source") or "unknown") for item in metric_incomplete
    )
    return {
        "available": True,
        "manifest": str(manifest_path),
        "validated_count": manifest.get("validated_count"),
        "metric_incomplete_count": len(metric_incomplete),
        "metric_incomplete_by_source": dict(sorted(by_source.items())),
        "anchor_invalid_overlap_count": len(overlap),
        "anchor_invalid_overlap_task_ids": overlap,
        "tripcount_patch_candidate_count": len(tripcount_patch_candidates),
        "tripcount_patch_candidates": tripcount_patch_candidates,
        "suggested_tripcount_small_sample_tasks": [
            item["task_id"] for item in tripcount_patch_candidates[:3]
        ],
        "metric_incomplete_task_ids": [
            item["task_id"] for item in metric_incomplete
        ],
        "hypothesis": (
            "CSim+Synth-only public-HLS smoke admitted tasks whose starter "
            "synth reports lacked latency/II; these cannot serve as scoreable "
            "starter anchors until tripcount/metric completeness is fixed or "
            "they are quarantined from the scored corpus."
        ),
    }


def _public_hls_manifest_path(task_root: Path) -> Path | None:
    candidates = [
        task_root / "generated" / "public_hls_validated_tasks_manifest.json",
        task_root / "public_hls_validated_tasks_manifest.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _public_provenance_summary(provenance: Any) -> dict[str, Any]:
    if not isinstance(provenance, Mapping):
        return {}
    keys = (
        "source",
        "source_path",
        "license",
        "top_function",
        "public_only",
        "hidden_imported",
        "reference_imported",
        "generated_testbench",
    )
    return {key: provenance.get(key) for key in keys if key in provenance}


def _anchor_hypothesis(issues: Sequence[str]) -> str:
    if "top_not_found_in_kernel_or_header" in issues:
        return "public import/top mapping likely invalid before agent optimization"
    if "public_tb_does_not_call_top" in issues:
        return "generated public testbench may not exercise the declared top"
    if "kernel_contains_host_runtime_markers" in issues:
        return "host/XRT code may have been imported as an HLS kernel"
    if "variable_bound_loops_without_tripcount" in issues:
        return "starter synth may pass but lack latency/II because variable-bound loops have no LOOP_TRIPCOUNT"
    if "generated_public_tb_has_no_observable_result_check" in issues:
        return "starter anchor may pass CSim without proving output behavior"
    return "static public package shape is plausible; verify with one small Vitis sample if prioritized"


def _normalized_tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def _normalize_identifier(value: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", value.lower()))


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _relative(before: float, after: float) -> float | None:
    if before == 0:
        return None
    return round((after - before) / before, 9)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ab-report", type=Path, required=True)
    parser.add_argument("--full199-report", type=Path, required=True)
    parser.add_argument("--quarantine-report", type=Path)
    parser.add_argument("--task-root", type=Path, default=Path("tasks"))
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ab = json.loads(args.ab_report.read_text(encoding="utf-8"))
    full = json.loads(args.full199_report.read_text(encoding="utf-8"))
    quarantine = (
        json.loads(args.quarantine_report.read_text(encoding="utf-8"))
        if args.quarantine_report is not None
        else None
    )
    qor_analysis = analyze_qor_rag_ab(ab, task_root=args.task_root)
    full199_analysis = analyze_full199_failures(full, task_root=args.task_root)
    post_quarantine = analyze_post_quarantine_failures(full, quarantine)
    result = {
        "schema_version": 2,
        "inputs": {
            "ab_report": str(args.ab_report),
            "full199_report": str(args.full199_report),
            "quarantine_report": (
                str(args.quarantine_report)
                if args.quarantine_report is not None
                else None
            ),
            "task_root": str(args.task_root),
        },
        "qor_rag_ab": qor_analysis,
        "full199_failures": full199_analysis,
        "post_quarantine_failures": post_quarantine,
        "phase2f_objective_status": analyze_phase2f_objective_status(
            qor_analysis, post_quarantine
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
