"""Run one fresh P0 shard with isolated submission and evaluator roles.

Every task uses a new attempt directory. A resumed shard skips only records
already committed to ``shard_summary.json``; an interrupted task receives a
new attempt directory, so stale kernels, XML reports, or tool workspaces are
never reused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any


TERMINAL_STATUSES = {
    "completed",
    "failed",
    "budget_exceeded",
    "infrastructure_error",
}


def discover_tasks(task_root: Path) -> list[Path]:
    manifests = sorted((task_root / "generated").glob("*/task.toml"))
    manifests += sorted((task_root / "official").glob("*/task.toml"))
    tasks = [manifest.parent.resolve() for manifest in manifests]
    if len(tasks) != 97 or len({task.name for task in tasks}) != 97:
        raise RuntimeError(f"expected 97 unique tasks, found {len(tasks)}")
    return tasks


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execution_source_snapshot(root: Path | None = None) -> dict[str, Any]:
    """Hash the execution/scoring sources used by one long-running shard."""

    project_root = (
        root.resolve()
        if root is not None
        else Path(__file__).resolve().parents[1]
    )
    paths = sorted((project_root / "agent").rglob("*.py"))
    paths.extend(
        project_root / relative
        for relative in (
            "Dockerfile",
            "test_all.sh",
            "run-p0-official-fresh.sh",
            "scoring/scoring_v3.py",
            "scoring/profiles.py",
            "scoring/run_p0_real_api_shard.py",
            "scoring/snapshot_execution_source.py",
            "scoring/reconcile_p0_evaluators.py",
            "scoring/audit_p0_acceptance.py",
            "scoring/audit_p0_official.py",
        )
    )
    entries = {
        str(path.relative_to(project_root)): _sha256(path)
        for path in sorted(set(paths))
        if path.is_file()
    }
    payload = "\n".join(
        f"{relative}:{digest}"
        for relative, digest in sorted(entries.items())
    )
    return {
        "root": str(project_root),
        "file_count": len(entries),
        "tree_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "files": entries,
    }


def _load_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"missing run report: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") not in TERMINAL_STATUSES:
        raise RuntimeError(f"non-canonical status: {report.get('status')!r}")
    return report


def _ok_gate(report: dict[str, Any], name: str) -> bool:
    gate = (report.get("gates") or {}).get(name)
    return isinstance(gate, dict) and gate.get("ok") is True


def validate_submission(report: dict[str, Any], task_id: str) -> list[str]:
    errors: list[str] = []
    if report.get("task_id") != task_id:
        errors.append("task_id_mismatch")
    if report.get("run_role") != "submission":
        errors.append("submission_role_missing")
    if report.get("mode") != "auto":
        errors.append("auto_mode_missing")

    preflight = report.get("task_preflight") or {}
    public_files = preflight.get("public_files_read") or []
    forbidden_names = {"hidden", "reference"}
    if preflight.get("forbidden_artifact_accesses") != 0:
        errors.append("forbidden_artifact_access_recorded")
    for value in public_files:
        parts = {part.lower() for part in PurePosixPath(str(value)).parts}
        if parts & forbidden_names:
            errors.append("hidden_or_reference_in_public_files")
            break

    grading_results = (
        (report.get("execution_trace") or {}).get("grading_results") or []
    )
    if grading_results:
        errors.append("submission_contains_evaluator_results")
    if (report.get("grading") or {}).get("source") is not None:
        errors.append("submission_claims_grading_source")

    compliance = report.get("model_compliance") or {}
    if compliance.get("compliance_proven") is not True:
        errors.append("model_compliance_unproven")
    llm = report.get("llm") or {}
    usage = llm.get("token_usage") or {}
    if llm.get("client") != "OpenAICompatClient":
        errors.append("real_custom_api_client_missing")
    request_count = usage.get("request_count", 0)
    if (
        usage.get("complete") is not True
        or request_count != usage.get("response_count")
        or usage.get("failed_request_count") != 0
        or usage.get("unreported_response_count") != 0
        or usage.get("total_tokens")
        != usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
    ):
        errors.append("real_api_usage_incomplete")
    elif report.get("status") == "completed" and request_count < 1:
        errors.append("completed_auto_run_without_api_request")

    toolchain = report.get("toolchain") or {}
    if toolchain.get("version_gate_ok") is not True:
        errors.append("vitis_2025_2_gate_failed")
    if toolchain.get("part_gate_ok") is not True:
        errors.append("u55c_part_gate_failed")

    if report.get("status") == "completed":
        if not _ok_gate(report, "interface"):
            errors.append("interface_gate_failed")
        if not _ok_gate(report, "frequency_100mhz"):
            errors.append("frequency_gate_failed")
        if not _ok_gate(report, "resource_capacity"):
            errors.append("resource_gate_failed")
        if (report.get("gates") or {}).get("public_acceptance", {}).get(
            "ok"
        ) is not True:
            errors.append("public_acceptance_failed")
        if report.get("cosim_ok") is not None and not _ok_gate(
            report, "required_cosim"
        ):
            errors.append("required_cosim_gate_failed")
        if (report.get("final_artifact") or {}).get(
            "fully_verified"
        ) is not True:
            errors.append("final_artifact_not_fully_verified")
    return errors


def validate_evaluator(
    report: dict[str, Any],
    task_id: str,
    *,
    official_task: bool,
) -> list[str]:
    errors: list[str] = []
    if report.get("task_id") != task_id:
        errors.append("task_id_mismatch")
    if report.get("run_role") != "evaluator":
        errors.append("evaluator_role_missing")
    if report.get("llm") is not None:
        errors.append("evaluator_unexpected_llm")

    grading = report.get("grading") or {}
    expected_source = "public_fallback" if official_task else "hidden"
    if grading.get("source") != expected_source:
        errors.append(
            f"grading_source_{grading.get('source')}_expected_{expected_source}"
        )
    if official_task:
        if grading.get("is_fallback") is not True:
            errors.append("official_public_fallback_not_labelled")
    elif grading.get("is_fallback") is True:
        errors.append("generated_hidden_grading_mislabelled_fallback")

    trace = (report.get("execution_trace") or {}).get(
        "grading_results"
    ) or []
    stages = {item.get("stage"): item for item in trace}
    for stage in ("hidden_csim", "candidate_synth"):
        if stages.get(stage, {}).get("ok") is not True:
            errors.append(f"{stage}_failed_or_missing")
    if report.get("cosim_ok") is not None and stages.get(
        "hidden_cosim", {}
    ).get("ok") is not True:
        errors.append("hidden_cosim_failed_or_missing")

    toolchain = report.get("toolchain") or {}
    if toolchain.get("version_gate_ok") is not True:
        errors.append("vitis_2025_2_gate_failed")
    if toolchain.get("part_gate_ok") is not True:
        errors.append("u55c_part_gate_failed")
    if report.get("status") == "completed":
        if not _ok_gate(report, "interface"):
            errors.append("interface_gate_failed")
        if not _ok_gate(report, "frequency_100mhz"):
            errors.append("frequency_gate_failed")
        if not _ok_gate(report, "resource_capacity"):
            errors.append("resource_gate_failed")
        if (report.get("gates") or {}).get("evaluator_acceptance", {}).get(
            "ok"
        ) is not True:
            errors.append("evaluator_acceptance_failed")
    return errors


def classify_outcome(
    submission: dict[str, Any] | None,
    evaluator: dict[str, Any] | None,
    launcher_error: str,
) -> str:
    if launcher_error:
        return "infrastructure_error"
    if submission is None:
        return "infrastructure_error"
    submission_status = submission.get("status")
    if submission_status != "completed":
        return str(submission_status)
    if evaluator is None:
        return "infrastructure_error"
    evaluator_status = evaluator.get("status")
    if evaluator_status == "completed":
        return "completed"
    reason = evaluator.get("stop_reason")
    if reason == "no_valid_anchor":
        return "no_valid_anchor"
    return str(evaluator_status)


def _run(
    command: list[str],
    log_path: Path,
    timeout_s: float,
) -> tuple[int | None, str, float]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        log_path.write_text(completed.stdout, encoding="utf-8")
        return completed.returncode, "", time.monotonic() - started
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        log_path.write_text(
            output + f"\nLAUNCHER TIMEOUT AFTER {timeout_s}s\n",
            encoding="utf-8",
        )
        return None, f"launcher_timeout_after_{timeout_s}s", (
            time.monotonic() - started
        )


def _next_attempt(task_root: Path) -> Path:
    existing = sorted(task_root.glob("attempt_*"))
    attempt = len(existing) + 1
    path = task_root / f"attempt_{attempt:03d}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def build_evaluator_command(
    *,
    task_dir: Path,
    final_kernel: Path,
    submission_evidence: Path,
    output_root: Path,
) -> list[str]:
    """Build the formal evaluator command with its mandatory evidence link."""
    return [
        sys.executable,
        "-m",
        "agent.main",
        "--task",
        str(task_dir),
        "--run-role",
        "evaluator",
        "--final-kernel",
        str(final_kernel),
        "--submission-evidence",
        str(submission_evidence),
        "--output-root",
        str(output_root),
        "--quiet",
    ]


def submission_requires_evaluator(
    submission: dict[str, Any] | None,
    final_kernel: Path | None,
) -> bool:
    """Only a completed submission can become formal evaluator input."""

    return bool(
        submission is not None
        and submission.get("status") == "completed"
        and final_kernel is not None
        and final_kernel.is_file()
    )


def _summary(
    *,
    shard_index: int,
    shard_count: int,
    selected_count: int,
    started: float,
    records: list[dict[str, Any]],
    source_start: dict[str, Any],
    source_current: dict[str, Any],
) -> dict[str, Any]:
    outcomes: dict[str, int] = {}
    for record in records:
        outcome = record["outcome"]
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    return {
        "schema_version": 2,
        "purpose": "p0_split_role_real_api_vitis_acceptance",
        "freshness_policy": (
            "new attempt directory per task; resume never reuses an "
            "interrupted attempt"
        ),
        "shard_index": shard_index,
        "shard_count": shard_count,
        "selected_task_count": selected_count,
        "completed_record_count": len(records),
        "outcome_counts": dict(sorted(outcomes.items())),
        "audit_error_record_count": sum(
            bool(record.get("audit_errors")) for record in records
        ),
        "execution_source": {
            "start": source_start,
            "current": source_current,
            "stable": (
                source_start.get("tree_sha256")
                == source_current.get("tree_sha256")
            ),
        },
        "elapsed_s": time.monotonic() - started,
        "records": records,
    }


def _write_summary(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run_shard(
    *,
    task_root: Path,
    output_root: Path,
    shard_index: int,
    shard_count: int,
    timeout_s: float,
    resume: bool,
    requested_task_ids: set[str] | None = None,
) -> dict[str, Any]:
    tasks = discover_tasks(task_root)
    if requested_task_ids is not None:
        available = {task.name for task in tasks}
        unknown = sorted(requested_task_ids - available)
        if unknown:
            raise RuntimeError(
                f"requested tasks are outside the corpus: {unknown}"
            )
        tasks = [
            task for task in tasks if task.name in requested_task_ids
        ]
    selected = [
        task
        for index, task in enumerate(tasks)
        if index % shard_count == shard_index
    ]
    summary_path = output_root / "shard_summary.json"
    source_start = execution_source_snapshot()
    records: list[dict[str, Any]] = []
    if output_root.exists():
        if not resume or not summary_path.is_file():
            raise RuntimeError(f"refusing to reuse output root: {output_root}")
        previous = json.loads(summary_path.read_text(encoding="utf-8"))
        previous_source = (
            (previous.get("execution_source") or {}).get("start") or {}
        )
        if (
            previous_source.get("tree_sha256")
            != source_start.get("tree_sha256")
        ):
            raise RuntimeError(
                "refusing to resume shard after execution source drift"
            )
        records = list(previous.get("records") or [])
    else:
        output_root.mkdir(parents=True)
    done = {record["task_id"] for record in records}
    shard_started = time.monotonic()

    for ordinal, task_dir in enumerate(selected, start=1):
        if (
            execution_source_snapshot().get("tree_sha256")
            != source_start.get("tree_sha256")
        ):
            raise RuntimeError(
                "execution source changed during shard; refusing mixed evidence"
            )
        task_id = task_dir.name
        if task_id in done:
            continue
        official = task_dir.parent.name == "official"
        attempt_root = _next_attempt(output_root / "tasks" / task_id)
        submission_root = attempt_root / "submission"
        evaluator_root = attempt_root / "evaluator"
        submission_log = attempt_root / "submission.log"
        evaluator_log = attempt_root / "evaluator.log"

        submission_command = [
            sys.executable,
            "-m",
            "agent.main",
            "--task",
            str(task_dir),
            "--mode",
            "auto",
            "--run-role",
            "submission",
            "--backend",
            "custom",
            "--output-root",
            str(submission_root),
            "--quiet",
        ]
        submission_rc, launcher_error, submission_elapsed = _run(
            submission_command, submission_log, timeout_s
        )
        submission_path = submission_root / task_id / "run_report.json"
        submission: dict[str, Any] | None = None
        submission_errors: list[str] = []
        try:
            submission = _load_report(submission_path)
            submission_errors = validate_submission(submission, task_id)
        except Exception as exc:
            submission_errors = [str(exc)]

        evaluator: dict[str, Any] | None = None
        evaluator_errors: list[str] = []
        evaluator_rc: int | None = None
        evaluator_elapsed = 0.0
        evaluator_path = evaluator_root / task_id / "run_report.json"
        evaluator_command: list[str] | None = None
        submission_evidence_path = (
            submission_root / task_id / "submission_evidence.json"
        )
        final_path_text = (
            (submission or {}).get("final_artifact") or {}
        ).get("path")
        final_path = Path(final_path_text) if final_path_text else None
        if (
            not launcher_error
            and submission_requires_evaluator(submission, final_path)
            and submission_evidence_path.is_file()
        ):
            evaluator_command = build_evaluator_command(
                task_dir=task_dir,
                final_kernel=final_path,
                submission_evidence=submission_evidence_path,
                output_root=evaluator_root,
            )
            evaluator_rc, evaluator_launcher_error, evaluator_elapsed = _run(
                evaluator_command, evaluator_log, timeout_s
            )
            if evaluator_launcher_error:
                launcher_error = evaluator_launcher_error
            try:
                evaluator = _load_report(evaluator_path)
                evaluator_errors = validate_evaluator(
                    evaluator, task_id, official_task=official
                )
            except Exception as exc:
                evaluator_errors = [str(exc)]
        else:
            evaluator_log.write_text(
                "Evaluator not launched because submission did not complete "
                "with a readable, evidence-linked final kernel.\n",
                encoding="utf-8",
            )

        audit_errors = submission_errors + evaluator_errors
        outcome = classify_outcome(submission, evaluator, launcher_error)
        usage = ((submission or {}).get("llm") or {}).get(
            "token_usage"
        ) or {}
        budget = (submission or {}).get("budget") or {}
        frequency = (
            ((submission or {}).get("gates") or {}).get(
                "frequency_100mhz"
            )
            or {}
        )
        record = {
            "ordinal": ordinal,
            "task_id": task_id,
            "task_dir": str(task_dir),
            "official_task": official,
            "attempt_root": str(attempt_root),
            "outcome": outcome,
            "launcher_error": launcher_error,
            "audit_errors": audit_errors,
            "submission": {
                "command": submission_command,
                "return_code": submission_rc,
                "elapsed_s": submission_elapsed,
                "log": str(submission_log),
                "report": str(submission_path),
                "report_sha256": (
                    _sha256(submission_path)
                    if submission_path.is_file()
                    else None
                ),
                "status": (submission or {}).get("status"),
                "stop_reason": (submission or {}).get("stop_reason"),
                "final_kernel": final_path_text,
                "submission_evidence": str(submission_evidence_path),
                "final_kernel_sha256": (
                    _sha256(final_path)
                    if final_path is not None and final_path.is_file()
                    else None
                ),
                "api": usage,
                "budget": budget,
                "frequency_mhz": frequency.get("frequency_mhz"),
                "credits_spent": budget.get("spent"),
                "tool_calls": (submission or {}).get("tool_call_count"),
            },
            "evaluator": {
                "command": evaluator_command,
                "return_code": evaluator_rc,
                "elapsed_s": evaluator_elapsed,
                "log": str(evaluator_log),
                "report": str(evaluator_path),
                "report_sha256": (
                    _sha256(evaluator_path)
                    if evaluator_path.is_file()
                    else None
                ),
                "status": (evaluator or {}).get("status"),
                "stop_reason": (evaluator or {}).get("stop_reason"),
                "grading_source": (
                    (evaluator or {}).get("grading") or {}
                ).get("source"),
                "score": (
                    (evaluator or {}).get("scoring") or {}
                ).get("score"),
            },
        }
        records.append(record)
        source_current = execution_source_snapshot()
        _write_summary(
            summary_path,
            _summary(
                shard_index=shard_index,
                shard_count=shard_count,
                selected_count=len(selected),
                started=shard_started,
                records=records,
                source_start=source_start,
                source_current=source_current,
            ),
        )
        if source_current.get("tree_sha256") != source_start.get(
            "tree_sha256"
        ):
            raise RuntimeError(
                "execution source changed during task; shard evidence is mixed"
            )
        print(
            f"shard={shard_index}/{shard_count} "
            f"task={ordinal}/{len(selected)} id={task_id} "
            f"outcome={outcome} sub_rc={submission_rc} "
            f"eval_rc={evaluator_rc} requests={usage.get('request_count')} "
            f"elapsed={submission_elapsed + evaluator_elapsed:.1f}s",
            flush=True,
        )

    result = json.loads(summary_path.read_text(encoding="utf-8"))
    if not (result.get("execution_source") or {}).get("stable"):
        raise RuntimeError("execution source stability gate failed")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--shard-index", required=True, type=int)
    parser.add_argument("--shard-count", type=int, default=3)
    parser.add_argument("--task-timeout-s", type=float, default=7200.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument(
        "--retry-from-audit",
        type=Path,
        default=None,
        help="Run only task IDs listed in retry_task_ids of a P0 audit",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        raise RuntimeError("shard index is outside shard count")
    requested = set(args.task_id)
    if args.retry_from_audit is not None:
        audit = json.loads(
            args.retry_from_audit.read_text(encoding="utf-8")
        )
        requested.update(audit.get("retry_task_ids") or [])
    result = run_shard(
        task_root=args.task_root.resolve(),
        output_root=args.output_root.resolve(),
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        timeout_s=args.task_timeout_s,
        resume=args.resume,
        requested_task_ids=requested or None,
    )
    return 0 if result["completed_record_count"] == result[
        "selected_task_count"
    ] else 4


if __name__ == "__main__":
    raise SystemExit(main())
