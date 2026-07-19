"""Aggregate split-role P0 shard evidence into one machine-readable audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scoring.run_p0_real_api_shard import (
    discover_tasks,
    validate_evaluator,
    validate_submission,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path(value: str | None) -> Path | None:
    if not value:
        return None
    return Path(value)


def _json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _add_tokens(total: dict[str, int], usage: dict[str, Any]) -> None:
    for key in (
        "request_count",
        "response_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "failed_request_count",
        "unreported_response_count",
    ):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            total[key] += value


def audit(task_root: Path, run_roots: list[Path]) -> dict[str, Any]:
    expected = {task.name for task in discover_tasks(task_root)}
    records: dict[str, dict[str, Any]] = {}
    superseded_records: list[dict[str, Any]] = []
    shard_evidence: list[dict[str, Any]] = []
    structural_tasks: set[str] = set()
    execution_source_sha256: str | None = None
    coverage_errors: list[str] = []

    for root in run_roots:
        summary_path = root / "shard_summary.json"
        summary = _json(summary_path)
        if summary is None:
            raise RuntimeError(f"missing shard summary: {summary_path}")
        source = summary.get("execution_source") or {}
        source_start = source.get("start") or {}
        source_sha256 = source_start.get("tree_sha256")
        source_ok = bool(
            source.get("stable") is True
            and isinstance(source_sha256, str)
            and len(source_sha256) == 64
        )
        if not source_ok:
            coverage_errors.append(
                f"execution_source_unproven:{summary_path}"
            )
        elif execution_source_sha256 is None:
            execution_source_sha256 = source_sha256
        elif source_sha256 != execution_source_sha256:
            coverage_errors.append(
                f"execution_source_mismatch:{summary_path}"
            )
        shard_evidence.append(
            {
                "path": str(summary_path),
                "sha256": _sha256(summary_path),
                "shard_index": summary.get("shard_index"),
                "selected_task_count": summary.get(
                    "selected_task_count"
                ),
                "completed_record_count": summary.get(
                    "completed_record_count"
                ),
                "outcome_counts": summary.get("outcome_counts"),
                "audit_error_record_count": summary.get(
                    "audit_error_record_count"
                ),
                "execution_source_stable": source.get("stable"),
                "execution_source_tree_sha256": source_sha256,
            }
        )
        for record in summary.get("records") or []:
            task_id = record.get("task_id")
            if task_id in records:
                previous = records[task_id]
                if previous.get("outcome") != "infrastructure_error":
                    raise RuntimeError(
                        "replacement is allowed only for an earlier "
                        f"infrastructure_error: {task_id}"
                    )
                superseded_records.append(
                    {
                        "task_id": task_id,
                        "old_outcome": previous.get("outcome"),
                        "old_attempt_root": previous.get("attempt_root"),
                        "replacement_outcome": record.get("outcome"),
                        "replacement_attempt_root": record.get(
                            "attempt_root"
                        ),
                    }
                )
            records[task_id] = record

    missing = sorted(expected - set(records))
    unexpected = sorted(set(records) - expected)
    if missing:
        coverage_errors.append(f"missing_tasks:{','.join(missing)}")
    if unexpected:
        coverage_errors.append(
            f"unexpected_tasks:{','.join(unexpected)}"
        )

    token_totals = {
        "request_count": 0,
        "response_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "failed_request_count": 0,
        "unreported_response_count": 0,
    }
    outcome_counts: dict[str, int] = {}
    stop_reason_counts: dict[str, int] = {}
    grading_source_counts: dict[str, int] = {}
    task_audits: dict[str, Any] = {}
    total_credits = 0
    total_credit_limits = 0
    total_tool_calls = 0
    minimum_frequency_mhz: float | None = None
    interface_pass_count = 0
    frequency_pass_count = 0
    resource_pass_count = 0
    required_cosim_pass_count = 0
    api_proven_task_count = 0
    api_request_task_count = 0
    audit_error_task_count = 0
    public_only_submission_count = 0
    model_compliance_task_count = 0
    final_verified_task_count = 0

    for task_id, record in sorted(records.items()):
        task_dir = _path(record.get("task_dir"))
        official = bool(record.get("official_task"))
        submission_path = _path(
            (record.get("submission") or {}).get("report")
        )
        evaluator_path = _path(
            (record.get("evaluator") or {}).get("report")
        )
        submission = _json(submission_path)
        evaluator = _json(evaluator_path)
        launcher_audit_errors = list(record.get("audit_errors") or [])
        errors: list[str] = []

        if submission is None:
            errors.append("submission_report_missing")
        else:
            errors.extend(validate_submission(submission, task_id))
        if evaluator is None:
            final_path_value = (
                ((submission or {}).get("final_artifact") or {}).get("path")
            )
            if final_path_value and Path(final_path_value).is_file():
                errors.append("evaluator_report_missing")
        else:
            errors.extend(
                validate_evaluator(
                    evaluator, task_id, official_task=official
                )
            )
        errors = sorted(set(errors))
        if errors:
            audit_error_task_count += 1

        outcome = str(record.get("outcome"))
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        terminal_reason = (
            (evaluator or {}).get("stop_reason")
            if evaluator is not None
            and evaluator.get("status") != "completed"
            else (submission or {}).get("stop_reason")
        )
        if terminal_reason:
            reason = str(terminal_reason)
            stop_reason_counts[reason] = stop_reason_counts.get(reason, 0) + 1
        usage = (
            ((submission or {}).get("llm") or {}).get("token_usage")
            or {}
        )
        _add_tokens(token_totals, usage)
        if usage.get("complete") is True:
            api_proven_task_count += 1
        if usage.get("request_count", 0) >= 1:
            api_request_task_count += 1

        preflight = (submission or {}).get("task_preflight") or {}
        if (
            preflight.get("forbidden_artifact_accesses") == 0
            and not (
                (submission or {}).get("execution_trace") or {}
            ).get("grading_results")
        ):
            public_only_submission_count += 1
        if (
            (submission or {}).get("model_compliance") or {}
        ).get("compliance_proven") is True:
            model_compliance_task_count += 1

        gates = (submission or {}).get("gates") or {}
        if (gates.get("interface") or {}).get("ok") is True:
            interface_pass_count += 1
        if (gates.get("frequency_100mhz") or {}).get("ok") is True:
            frequency_pass_count += 1
        if (gates.get("resource_capacity") or {}).get("ok") is True:
            resource_pass_count += 1
        if (submission or {}).get("cosim_ok") is not None:
            structural_tasks.add(task_id)
            if (gates.get("required_cosim") or {}).get("ok") is True:
                required_cosim_pass_count += 1
        frequency = (gates.get("frequency_100mhz") or {}).get(
            "frequency_mhz"
        )
        if isinstance(frequency, (int, float)):
            minimum_frequency_mhz = (
                float(frequency)
                if minimum_frequency_mhz is None
                else min(minimum_frequency_mhz, float(frequency))
            )
        if (
            (submission or {}).get("final_artifact") or {}
        ).get("fully_verified") is True:
            final_verified_task_count += 1

        budget = (submission or {}).get("budget") or {}
        if isinstance(budget.get("spent"), int):
            total_credits += budget["spent"]
        if isinstance(budget.get("total"), int):
            total_credit_limits += budget["total"]
        if isinstance((submission or {}).get("tool_call_count"), int):
            total_tool_calls += submission["tool_call_count"]

        source = (
            (evaluator or {}).get("grading") or {}
        ).get("source")
        if source:
            grading_source_counts[source] = (
                grading_source_counts.get(source, 0) + 1
            )

        final_path = _path(
            ((submission or {}).get("final_artifact") or {}).get("path")
        )
        task_audits[task_id] = {
            "outcome": outcome,
            "official_task": official,
            "task_dir": str(task_dir) if task_dir else None,
            "audit_ok": not errors,
            "audit_errors": errors,
            "launcher_audit_errors": launcher_audit_errors,
            "submission": {
                "status": (submission or {}).get("status"),
                "stop_reason": (submission or {}).get("stop_reason"),
                "report": str(submission_path) if submission_path else None,
                "report_sha256": (
                    _sha256(submission_path)
                    if submission_path and submission_path.is_file()
                    else None
                ),
                "final_kernel": str(final_path) if final_path else None,
                "final_kernel_sha256": (
                    _sha256(final_path)
                    if final_path and final_path.is_file()
                    else None
                ),
                "token_usage": usage,
                "budget": budget,
                "tool_call_count": (submission or {}).get(
                    "tool_call_count"
                ),
                "final_hardware": (submission or {}).get(
                    "final_hardware"
                ),
                "gates": gates,
                "toolchain": (submission or {}).get("toolchain"),
            },
            "evaluator": {
                "status": (evaluator or {}).get("status"),
                "stop_reason": (evaluator or {}).get("stop_reason"),
                "report": str(evaluator_path) if evaluator_path else None,
                "report_sha256": (
                    _sha256(evaluator_path)
                    if evaluator_path and evaluator_path.is_file()
                    else None
                ),
                "grading": (evaluator or {}).get("grading"),
                "scoring": (evaluator or {}).get("scoring"),
                "gates": (evaluator or {}).get("gates"),
            },
        }

    task_count = len(records)
    workflow_integrity_ok = bool(
        not coverage_errors
        and task_count == 97
        and audit_error_task_count == 0
        and api_proven_task_count == 97
        and public_only_submission_count == 97
        and model_compliance_task_count == 97
        and token_totals["failed_request_count"] == 0
        and token_totals["unreported_response_count"] == 0
    )
    retry_task_ids = sorted(
        task_id
        for task_id, result in task_audits.items()
        if result["outcome"] == "infrastructure_error"
        or not result["audit_ok"]
    )
    return {
        "schema_version": 1,
        "purpose": "p0_97_task_fresh_split_role_acceptance",
        "fresh_evidence_only": True,
        "execution_source_tree_sha256": execution_source_sha256,
        "workflow_integrity_ok": workflow_integrity_ok,
        "retry_task_ids": retry_task_ids,
        "superseded_records": superseded_records,
        "coverage": {
            "expected_task_count": 97,
            "recorded_task_count": task_count,
            "coverage_errors": coverage_errors,
            "audit_error_task_count": audit_error_task_count,
            "outcome_counts": dict(sorted(outcome_counts.items())),
            "stop_reason_counts": dict(sorted(stop_reason_counts.items())),
        },
        "submission_isolation": {
            "public_only_submission_count": public_only_submission_count,
            "forbidden_access_count": 97 - public_only_submission_count,
        },
        "model_and_api": {
            "model_compliance_proven_task_count": (
                model_compliance_task_count
            ),
            "real_api_config_and_usage_proven_task_count": (
                api_proven_task_count
            ),
            "tasks_with_api_requests": api_request_task_count,
            "tasks_without_api_requests_due_to_pre_llm_terminal_gate": (
                97 - api_request_task_count
            ),
            "token_totals": token_totals,
        },
        "target_gates": {
            "interface_pass_count": interface_pass_count,
            "frequency_100mhz_pass_count": frequency_pass_count,
            "resource_capacity_pass_count": resource_pass_count,
            "required_cosim_task_count": len(structural_tasks),
            "required_cosim_pass_count": required_cosim_pass_count,
            "required_cosim_task_ids": sorted(structural_tasks),
            "minimum_observed_frequency_mhz": minimum_frequency_mhz,
            "final_fully_verified_count": final_verified_task_count,
        },
        "evaluator": {
            "grading_source_counts": dict(
                sorted(grading_source_counts.items())
            ),
        },
        "resource_consumption": {
            "credits_spent": total_credits,
            "credit_limits_sum": total_credit_limits,
            "tool_call_count": total_tool_calls,
        },
        "shards": shard_evidence,
        "tasks": task_audits,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", required=True, type=Path)
    parser.add_argument("--run-root", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite output: {args.output}")
    result = audit(
        args.task_root.resolve(),
        [root.resolve() for root in args.run_root],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"P0 audit: tasks={result['coverage']['recorded_task_count']} "
        f"outcomes={result['coverage']['outcome_counts']} "
        f"api_requests={result['model_and_api']['token_totals']['request_count']} "
        f"tokens={result['model_and_api']['token_totals']['total_tokens']} "
        f"integrity={result['workflow_integrity_ok']} "
        f"output={args.output}"
    )
    return 0 if result["workflow_integrity_ok"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
