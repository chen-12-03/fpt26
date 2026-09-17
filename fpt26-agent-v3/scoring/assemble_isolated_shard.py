"""Assemble portable shard evidence from two-container task attempts."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scoring.run_p0_real_api_shard import (
    classify_outcome,
    execution_source_snapshot,
    validate_evaluator,
    validate_submission,
)


def _load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def _report_ref(path: Path, shard_root: Path, report_prefix: str) -> str:
    relative = _relative(path, shard_root)
    return "/workspace/" + str(Path(report_prefix) / relative)


def summarize_audit_status(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate execution/isolation validity from model compliance evidence."""

    model_unproven = sum(
        "model_compliance_unproven" in (record.get("audit_errors") or [])
        for record in records
    )
    execution_errors = sum(
        any(
            error != "model_compliance_unproven"
            for error in (record.get("audit_errors") or [])
        )
        for record in records
    )
    any_errors = sum(bool(record.get("audit_errors")) for record in records)
    if model_unproven == 0:
        compliance = "proven"
    elif model_unproven == len(records):
        compliance = "unproven"
    else:
        compliance = "mixed"
    return {
        "audit_error_record_count": any_errors,
        "execution_audit_error_record_count": execution_errors,
        "model_compliance_unproven_record_count": model_unproven,
        "status": {
            "record_collection": "complete",
            "execution_audit": "passed" if execution_errors == 0 else "failed",
            "model_compliance": compliance,
            "overall_audit": "passed" if any_errors == 0 else "failed",
            "launcher_exit_code": 0 if any_errors == 0 else 4,
        },
    }


def _record(
    shard_root: Path,
    task_root: Path,
    attempt: Path,
    ordinal: int,
    report_prefix: str,
) -> dict[str, Any]:
    task_id = task_root.name
    submission_root = attempt / "submission"
    evaluator_root = attempt / "evaluator"
    submission_path = submission_root / task_id / "run_report.json"
    evaluator_path = evaluator_root / task_id / "run_report.json"
    submission = _load(submission_path)
    evaluator = _load(evaluator_path)
    submission_attestation = _load(
        submission_root / task_id / "container_isolation.json"
    ) or {}
    evaluator_attestation = _load(
        evaluator_root / task_id / "container_isolation.json"
    ) or {}

    contract = submission_attestation.get("llm_contract") or {}
    submission_errors: list[str] = []
    evaluator_errors: list[str] = []
    if submission is None:
        submission_errors.append("submission_report_missing")
    else:
        submission_errors.extend(
            validate_submission(
                submission,
                task_id,
                expected_client=contract.get("expected_client", "OpenAICompatClient"),
                expected_model=contract.get("model"),
            )
        )
    if submission_attestation.get("physical_isolation_proven") is not True:
        submission_errors.append("submission_physical_isolation_unproven")
    if not submission_attestation.get("execution_source"):
        submission_errors.append("submission_execution_source_missing")

    if submission is not None and submission.get("status") == "completed":
        if evaluator is None:
            evaluator_errors.append("evaluator_report_missing")
        else:
            evaluator_errors.extend(
                validate_evaluator(
                    evaluator,
                    task_id,
                    official_task=False,
                    expected_grading_source="hidden",
                )
            )
        if evaluator_attestation.get("physical_isolation_proven") is not True:
            evaluator_errors.append("evaluator_physical_isolation_unproven")
        if evaluator_attestation.get("api_credentials_visible") is not False:
            evaluator_errors.append("evaluator_api_isolation_unproven")
        if evaluator_attestation.get("network_isolated") is not True:
            evaluator_errors.append("evaluator_network_isolation_unproven")
        if evaluator_attestation.get("network_interfaces") != ["lo"]:
            evaluator_errors.append("evaluator_non_loopback_interface_visible")
        submission_source = submission_attestation.get("execution_source") or {}
        evaluator_source = evaluator_attestation.get("execution_source") or {}
        if submission_source.get("tree_sha256") != evaluator_source.get("tree_sha256"):
            evaluator_errors.append("role_execution_source_mismatch")

    launcher_error = ""
    if submission is None:
        launcher_error = "submission_report_missing"
    elif submission.get("status") == "completed" and evaluator is None:
        launcher_error = "evaluator_report_missing"
    outcome = classify_outcome(submission, evaluator, launcher_error)

    usage = ((submission or {}).get("llm") or {}).get("token_usage") or {}
    llm = (submission or {}).get("llm") or {}
    budget = (submission or {}).get("budget") or {}
    trace = (submission or {}).get("execution_trace") or {}
    calls = Counter(str(item.get("kind") or "unknown") for item in trace.get("transcript") or [])
    failed_calls = Counter(
        str(item.get("kind") or "unknown")
        for item in trace.get("metered_results") or []
        if item.get("ok") is not True
    )
    evaluator_trace = (
        ((evaluator or {}).get("execution_trace") or {}).get("grading_results") or []
    )
    final_text = ((submission or {}).get("final_artifact") or {}).get("path")
    final_path = (
        submission_root / task_id / Path(final_text).name if final_text else None
    )
    frequency = ((submission or {}).get("gates") or {}).get("frequency_100mhz") or {}

    return {
        "ordinal": ordinal,
        "task_id": task_id,
        "task_dir": f"evaluator_private/{task_id}",
        "submission_task_dir": f"public_agent/{task_id}",
        "evaluator_task_dir": f"evaluator_private/{task_id}",
        "official_task": False,
        "attempt_root": _relative(attempt, shard_root),
        "outcome": outcome,
        "launcher_error": launcher_error,
        "audit_errors": submission_errors + evaluator_errors,
        "isolation": {
            "submission": submission_attestation,
            "evaluator": evaluator_attestation,
        },
        "submission": {
            "backend": contract.get("backend"),
            "command": "isolated submission container; see launcher metadata",
            "return_code": 0 if (submission or {}).get("status") == "completed" else 4 if submission else None,
            "elapsed_s": ((submission or {}).get("evaluation") or {}).get("wall_time_seconds"),
            "log": _report_ref(attempt / "submission.log", shard_root, report_prefix),
            "report": _report_ref(submission_path, shard_root, report_prefix),
            "report_sha256": _sha256(submission_path),
            "status": (submission or {}).get("status"),
            "stop_reason": (submission or {}).get("stop_reason"),
            "final_kernel": _report_ref(final_path, shard_root, report_prefix) if final_path and final_path.exists() else None,
            "submission_evidence": _report_ref(
                submission_root / task_id / "submission_evidence.json", shard_root, report_prefix
            ),
            "final_kernel_sha256": _sha256(final_path) if final_path else None,
            "api": usage,
            "llm_client": llm.get("client"),
            "model": llm.get("model"),
            "model_compliance": (submission or {}).get("model_compliance"),
            "budget": budget,
            "frequency_mhz": frequency.get("frequency_mhz"),
            "credits_spent": budget.get("spent"),
            "tool_calls": (submission or {}).get("tool_call_count"),
            "calls_by_tool": dict(sorted(calls.items())),
            "failed_calls_by_tool": dict(sorted(failed_calls.items())),
        },
        "evaluator": {
            "command": "isolated evaluator container; network=none; no API env",
            "return_code": 0 if (evaluator or {}).get("status") == "completed" else 4 if evaluator else None,
            "elapsed_s": ((evaluator or {}).get("evaluation") or {}).get("wall_time_seconds"),
            "log": _report_ref(attempt / "evaluator.log", shard_root, report_prefix),
            "report": _report_ref(evaluator_path, shard_root, report_prefix),
            "report_sha256": _sha256(evaluator_path),
            "status": (evaluator or {}).get("status"),
            "stop_reason": (evaluator or {}).get("stop_reason"),
            "grading_source": ((evaluator or {}).get("grading") or {}).get("source"),
            "score": ((evaluator or {}).get("scoring") or {}).get("score"),
            "grading_tool_call_count": len(evaluator_trace),
            "grading_calls_by_stage": dict(
                sorted(Counter(str(item.get("stage") or "unknown") for item in evaluator_trace).items())
            ),
        },
    }


def assemble(
    shard_root: Path,
    shard_index: int,
    shard_count: int,
    report_prefix: str,
    csim_timeout_s: float,
    synth_timeout_s: float,
    cosim_timeout_s: float,
) -> dict[str, Any]:
    task_roots = sorted(path for path in (shard_root / "tasks").glob("*") if path.is_dir())
    selected_attempts = []
    for task_root in task_roots:
        attempts = sorted(path for path in task_root.glob("attempt_*") if path.is_dir())
        if attempts:
            selected_attempts.append((task_root, attempts[-1]))
    records = [
        _record(shard_root, task_root, attempt, ordinal, report_prefix)
        for ordinal, (task_root, attempt) in enumerate(selected_attempts, start=1)
    ]
    outcomes = Counter(record["outcome"] for record in records)
    contracts = {
        json.dumps(
            (record.get("isolation") or {}).get("submission", {}).get("llm_contract") or {},
            sort_keys=True,
        )
        for record in records
        if (record.get("isolation") or {}).get("submission")
    }
    if len(contracts) > 1:
        raise RuntimeError("refusing to assemble a shard with mixed LLM contracts")
    llm_contract = json.loads(next(iter(contracts))) if contracts else None
    captured_sources = [
        (record.get("isolation") or {}).get("submission", {}).get("execution_source")
        for record in records
    ]
    captured_sources = [source for source in captured_sources if source]
    captured_hashes = {source.get("tree_sha256") for source in captured_sources}
    if len(captured_hashes) > 1:
        raise RuntimeError("refusing to assemble a shard with mixed execution sources")
    source = captured_sources[0] if captured_sources else execution_source_snapshot()
    values_s = {
        "csim": csim_timeout_s,
        "synth": synth_timeout_s,
        "cosim": cosim_timeout_s,
    }
    timeout_env = {
        "LLM4HLS_CSIM_TIMEOUT_S": str(csim_timeout_s),
        "LLM4HLS_SYNTH_TIMEOUT_S": str(synth_timeout_s),
        "LLM4HLS_COSIM_TIMEOUT_S": str(cosim_timeout_s),
    }
    elapsed_s = sum(
        float(record[role].get("elapsed_s") or 0.0)
        for record in records
        for role in ("submission", "evaluator")
    )
    audit_status = summarize_audit_status(records)
    result = {
        "schema_version": 3,
        "purpose": "p0_physically_isolated_split_role_real_api_vitis_acceptance",
        "isolation_contract": {
            "submission_private_mount": False,
            "evaluator_private_mount": True,
            "evaluator_network": "none",
            "evaluator_api_credentials": False,
        },
        "shard_index": shard_index,
        "shard_count": shard_count,
        "selected_task_count": len(records),
        "completed_record_count": len(records),
        "outcome_counts": dict(sorted(outcomes.items())),
        **audit_status,
        "execution_source": {"start": source, "current": source, "stable": True},
        "execution_source_capture": "submission_start" if captured_sources else "assembly_fallback",
        "elapsed_s": elapsed_s,
        "llm_run_contract": llm_contract,
        "tool_timeout_policy": {
            "scope": "track_a_150",
            "task_root_kind": "evaluator_private",
            "source": "environment_override",
            "values_s": values_s,
            "env_overrides": timeout_env,
            "explicit_override_names": sorted(timeout_env),
        },
        "task_roots": {
            "submission": "/fpt26-public-tasks",
            "evaluator": "/fpt26-evaluator-tasks",
            "physically_separated": True,
        },
        "records": records,
    }
    temporary = shard_root / "shard_summary.json.tmp"
    final = shard_root / "shard_summary.json"
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(final)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard-root", required=True, type=Path)
    parser.add_argument("--shard-index", required=True, type=int)
    parser.add_argument("--shard-count", required=True, type=int)
    parser.add_argument("--report-prefix", required=True)
    parser.add_argument("--csim-timeout-s", type=float, default=30.0)
    parser.add_argument("--synth-timeout-s", type=float, default=180.0)
    parser.add_argument("--cosim-timeout-s", type=float, default=240.0)
    args = parser.parse_args()
    result = assemble(
        args.shard_root,
        args.shard_index,
        args.shard_count,
        args.report_prefix,
        args.csim_timeout_s,
        args.synth_timeout_s,
        args.cosim_timeout_s,
    )
    print(json.dumps({
        "records": result["completed_record_count"],
        "outcomes": result["outcome_counts"],
        "audit_error_records": result["audit_error_record_count"],
    }, sort_keys=True))
    return 0 if result["audit_error_record_count"] == 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())
