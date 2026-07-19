"""Audit the three clean-image official split-role acceptance runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from scoring.run_p0_real_api_shard import (
    execution_source_snapshot,
    validate_evaluator,
    validate_submission,
)


OFFICIAL_TASKS = (
    "projection_bugfix",
    "dotProduct_optimize",
    "residual_stream_deadlock",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"missing report: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def audit(run_root: Path) -> dict[str, Any]:
    tasks: dict[str, Any] = {}
    all_errors: list[str] = []
    source_start_path = run_root / "execution-source-start.json"
    source_end_path = run_root / "execution-source-end.json"
    source_start = _load(source_start_path)
    source_end = _load(source_end_path)
    source_current = execution_source_snapshot()
    source_tree = source_start.get("tree_sha256")
    if (
        not isinstance(source_tree, str)
        or len(source_tree) != 64
        or source_end.get("tree_sha256") != source_tree
    ):
        all_errors.append("execution_source_changed_during_official_run")
    if source_current.get("tree_sha256") != source_tree:
        all_errors.append("execution_source_changed_before_official_audit")
    totals = {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "credits_spent": 0,
        "tool_call_count": 0,
    }
    minimum_frequency: float | None = None

    for task_id in OFFICIAL_TASKS:
        submission_path = (
            run_root
            / task_id
            / "submission"
            / task_id
            / "run_report.json"
        )
        evaluator_path = (
            run_root
            / task_id
            / "evaluator"
            / task_id
            / "run_report.json"
        )
        submission = _load(submission_path)
        evaluator = _load(evaluator_path)
        errors = validate_submission(submission, task_id)
        errors.extend(
            validate_evaluator(
                evaluator, task_id, official_task=True
            )
        )
        if submission.get("status") != "completed":
            errors.append(
                f"submission_status_{submission.get('status')}"
            )
        if evaluator.get("status") != "completed":
            errors.append(
                f"evaluator_status_{evaluator.get('status')}"
            )

        final = submission.get("final_artifact") or {}
        final_path = Path(final.get("path") or "")
        if not final_path.is_file():
            errors.append("final_kernel_missing")
            final_hash = None
        else:
            final_hash = _sha256(final_path)
            if final_hash != final.get("sha256"):
                errors.append("final_kernel_hash_mismatch")

        evaluator_final = evaluator.get("final_artifact") or {}
        evaluator_final_path = Path(evaluator_final.get("path") or "")
        if not evaluator_final_path.is_file():
            errors.append("evaluator_final_kernel_missing")
            evaluator_final_hash = None
        else:
            evaluator_final_hash = _sha256(evaluator_final_path)
            if evaluator_final_hash != evaluator_final.get("sha256"):
                errors.append("evaluator_final_kernel_hash_mismatch")
        if (
            final_hash is not None
            and evaluator_final_hash is not None
            and evaluator_final_hash != final_hash
        ):
            errors.append("submission_evaluator_kernel_hash_mismatch")

        if task_id == "residual_stream_deadlock":
            cosim = (
                submission.get("final_hardware") or {}
            ).get("cosim") or {}
            if (
                cosim.get("ok") is not True
                or cosim.get("latency_max") is None
            ):
                errors.append("residual_final_required_cosim_missing")
            if final_hash is not None and cosim.get(
                "source_sha256"
            ) != final_hash:
                errors.append("residual_submission_cosim_kernel_mismatch")
            evaluator_cosim = (
                evaluator.get("final_hardware") or {}
            ).get("cosim") or {}
            if (
                evaluator_cosim.get("ok") is not True
                or evaluator_cosim.get("latency_max") is None
            ):
                errors.append("residual_evaluator_required_cosim_missing")
            if evaluator_final_hash is not None and evaluator_cosim.get(
                "source_sha256"
            ) != evaluator_final_hash:
                errors.append("residual_evaluator_cosim_kernel_mismatch")

        frequency_gate = (
            (submission.get("gates") or {}).get("frequency_100mhz")
            or {}
        )
        frequency = frequency_gate.get("frequency_mhz")
        period = frequency_gate.get("candidate_clock_ns")
        frequency_valid = bool(
            isinstance(period, (int, float))
            and not isinstance(period, bool)
            and math.isfinite(float(period))
            and 0.0 < float(period) <= 10.0
            and isinstance(frequency, (int, float))
            and not isinstance(frequency, bool)
            and math.isfinite(float(frequency))
            and float(frequency) >= 100.0
            and math.isclose(
                float(frequency),
                1000.0 / float(period),
                rel_tol=1e-9,
                abs_tol=1e-6,
            )
        )
        if frequency_valid:
            minimum_frequency = (
                float(frequency)
                if minimum_frequency is None
                else min(minimum_frequency, float(frequency))
            )
        else:
            errors.append("frequency_evidence_invalid")

        usage = (submission.get("llm") or {}).get(
            "token_usage"
        ) or {}
        for key in (
            "request_count",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
        ):
            value = usage.get(key)
            if isinstance(value, int):
                totals[key] += value
        budget = submission.get("budget") or {}
        if isinstance(budget.get("spent"), int):
            totals["credits_spent"] += budget["spent"]
        if isinstance(submission.get("tool_call_count"), int):
            totals["tool_call_count"] += submission[
                "tool_call_count"
            ]

        errors = sorted(set(errors))
        all_errors.extend(f"{task_id}:{error}" for error in errors)
        tasks[task_id] = {
            "acceptance_ok": not errors,
            "errors": errors,
            "submission_report": str(submission_path),
            "submission_report_sha256": _sha256(submission_path),
            "evaluator_report": str(evaluator_path),
            "evaluator_report_sha256": _sha256(evaluator_path),
            "final_kernel": str(final_path),
            "final_kernel_sha256": final_hash,
            "evaluator_final_kernel": str(evaluator_final_path),
            "evaluator_final_kernel_sha256": evaluator_final_hash,
            "frequency_mhz": frequency,
            "required_cosim": (
                (submission.get("final_hardware") or {}).get("cosim")
            ),
            "grading": evaluator.get("grading"),
            "score": (evaluator.get("scoring") or {}).get("score"),
            "token_usage": usage,
            "budget": budget,
            "tool_call_count": submission.get("tool_call_count"),
            "toolchain": submission.get("toolchain"),
        }

    return {
        "schema_version": 1,
        "purpose": "p0_clean_image_official_split_role_acceptance",
        "acceptance_ok": not all_errors,
        "execution_source": {
            "start": str(source_start_path),
            "start_sha256": _sha256(source_start_path),
            "end": str(source_end_path),
            "end_sha256": _sha256(source_end_path),
            "tree_sha256": source_tree,
            "current_tree_sha256": source_current.get("tree_sha256"),
            "stable": not any(
                error.startswith("execution_source_changed")
                for error in all_errors
            ),
        },
        "task_count": len(tasks),
        "errors": all_errors,
        "minimum_frequency_mhz": minimum_frequency,
        "resource_consumption": totals,
        "tasks": tasks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite output: {args.output}")
    result = audit(args.run_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"official P0 audit: ok={result['acceptance_ok']} "
        f"tasks={result['task_count']} "
        f"requests={result['resource_consumption']['request_count']} "
        f"tokens={result['resource_consumption']['total_tokens']} "
        f"output={args.output}"
    )
    return 0 if result["acceptance_ok"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
