#!/usr/bin/env python3
"""Prepare a non-executed QoR-RAG small-sample A/B plan.

The output is an execution plan only.  It does not launch Vitis, call an LLM,
or promote results to the execution freeze.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_TRIAGE_REPORT = Path(
    "fpt26-agent-v3/scoring/reports/phase2f_offline_agent_triage_20260725.json"
)
DEFAULT_OUTPUT = Path(
    "fpt26-agent-v3/scoring/reports/phase2f_qor_rag_small_ab_plan_20260725.json"
)
DEFAULT_TASK_LIST_OUTPUT = Path(
    "fpt26-agent-v3/evals/qor_rag_small_ab_priority_tasks_latest.txt"
)


def build_plan(
    triage_report: Mapping[str, Any],
    *,
    triage_report_path: Path,
    plan_output: Path,
    task_list_output: Path,
    run_label: str = "phase2f_qor_rag_small_ab",
    max_tasks: int = 3,
    task_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    if max_tasks < 1 or max_tasks > 3:
        raise ValueError("max_tasks must stay in the user-approved 1-3 range")

    objective = triage_report.get("phase2f_objective_status")
    if not isinstance(objective, Mapping):
        raise ValueError("triage report missing phase2f_objective_status")
    qor = objective.get("qor_rag_generalized_offline")
    if not isinstance(qor, Mapping):
        raise ValueError("triage report missing qor_rag_generalized_offline")

    records = qor.get("records", [])
    if not isinstance(records, list):
        raise ValueError("qor_rag_generalized_offline.records must be a list")

    selected = _select_task_records(records, max_tasks=max_tasks, task_ids=task_ids)
    if not selected:
        raise ValueError("no QoR tasks require real small A/B evidence")

    task_ids = [record["task_id"] for record in selected]
    task_flags = " ".join(f"--task-id {task_id}" for task_id in task_ids)
    task_list_text = "\n".join(task_ids) + "\n"
    legacy_root = f"runs/{run_label}_legacy_20260725"
    generalized_root = f"runs/{run_label}_generalized_20260725"
    measured_report = (
        "fpt26-agent-v3/scoring/reports/"
        f"{run_label}_measured_20260725.json"
    )
    raw_compare_report = (
        "fpt26-agent-v3/scoring/reports/"
        f"{run_label}_raw_compare_20260725.json"
    )
    plan_report = str(plan_output)

    lanes = {
        "legacy_baseline": {
            "description": (
                "Legacy/default retrieval with formal early-stop disabled; "
                "used only as the small-sample baseline."
            ),
            "env": {
                "FPT26_QOR_RAG_GENERALIZED": "0",
                "FPT26_QOR_RAG_EARLY_STOP": "0",
                "PYTHONPATH": "fpt26-agent-v3:.",
            },
            "output_root": legacy_root,
            "command": _run_command(
                generalized="0",
                output_root=legacy_root,
                task_flags=task_flags,
            ),
        },
        "generalized_candidate": {
            "description": (
                "Generalized retrieval with exact task/source boosts disabled "
                "and formal early-stop disabled."
            ),
            "env": {
                "FPT26_QOR_RAG_GENERALIZED": "1",
                "FPT26_QOR_RAG_EARLY_STOP": "0",
                "PYTHONPATH": "fpt26-agent-v3:.",
            },
            "output_root": generalized_root,
            "command": _run_command(
                generalized="1",
                output_root=generalized_root,
                task_flags=task_flags,
            ),
        },
    }

    return {
        "schema_version": 1,
        "purpose": "phase2f_generalized_qor_rag_small_sample_ab_plan",
        "status": "not_executed",
        "evidence_level": "execution_plan_only",
        "source_triage_report": str(triage_report_path),
        "run_label": run_label,
        "task_list_output": str(task_list_output),
        "task_list_text": task_list_text,
        "selected_task_count": len(selected),
        "selected_tasks": selected,
        "sample_policy": {
            "max_real_api_vitis_tasks": 3,
            "planned_task_count": len(selected),
            "full199_allowed": False,
            "execution_freeze_update_allowed": False,
            "measured_report_required": True,
        },
        "guardrails": [
            "Do not run full199 for this plan.",
            "Do not update fpt26-agent-v3/execution-freeze.json from this plan.",
            "Run at most 1-3 real API/Vitis tasks per optimization loop.",
            "Write measured A/B output under fpt26-agent-v3/scoring/reports/.",
            "Label measured output as small-sample evidence, not acceptance.",
        ],
        "lanes": lanes,
        "comparison": {
            "task_list_path": str(task_list_output),
            "output_report": measured_report,
            "command": (
                "PYTHONPATH=fpt26-agent-v3:. "
                "python3 tools/finalize_qor_rag_small_ab.py "
                f"--plan {plan_report} "
                f"--baseline-root {legacy_root} "
                f"--candidate-root {generalized_root} "
                f"--task-list {task_list_output} "
                f"--output {measured_report}"
            ),
            "raw_compare_command": (
                "PYTHONPATH=fpt26-agent-v3:. python3 -m agent.qor_rag_ab "
                f"--baseline-root {legacy_root} "
                f"--candidate-root {generalized_root} "
                f"--task-list {task_list_output} "
                f"--output {raw_compare_report}"
            ),
            "raw_compare_output_report": raw_compare_report,
        },
        "required_measured_fields": [
            "task_id",
            "submission status and evaluator status",
            "success/outcome and failure reason",
            "score, valid, q_hw, latency_ratio/acceleration",
            "request_count, prompt_tokens, completion_tokens, total_tokens",
            "credits_spent and wasted_attempts",
        ],
        "post_edit_verification": [
            (
                "PYTHONPATH=fpt26-agent-v3:. python3 -m pytest -q "
                "fpt26-agent-v3/tests/test_qor_rag.py "
                "fpt26-agent-v3/tests/test_p0_batch_runner.py "
                "fpt26-agent-v3/tests/test_offline_agent_triage.py "
                "fpt26-agent-v3/tests/test_p0_candidate_validation.py"
            ),
            (
                "PYTHONPATH=fpt26-agent-v3:. python3 -m "
                "agent.qor_rag_retrieval_eval --output "
                "fpt26-agent-v3/evals/qor_rag_retrieval_eval_latest.json"
            ),
            "git diff --check",
        ],
        "promotion_policy": {
            "may_claim_qor_repair": (
                "only after the measured small A/B report preserves "
                "correctness and improves or explains each priority regression"
            ),
            "may_update_execution_freeze_json": (
                "false for small samples; requires explicit fresh full199 "
                "acceptance"
            ),
        },
    }


def _task_plan_record(record: Mapping[str, Any]) -> dict[str, Any]:
    task_id = record.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("QoR task record missing task_id")
    return {
        "task_id": task_id,
        "expected_generalized_rule": record.get("expected_generalized_rule"),
        "offline_status": record.get("status"),
        "generalized_retrieved_ids": [
            str(item)
            for item in record.get("generalized_retrieved_ids", [])
            if isinstance(item, str)
        ],
        "generalized_exact_source_measured_case_count": record.get(
            "generalized_exact_source_measured_case_count"
        ),
        "prior_q_hw_delta": record.get("q_hw_delta"),
        "prior_acceleration_delta": record.get("acceleration_delta"),
        "offline_hypotheses": [
            str(item)
            for item in record.get("hypotheses", [])
            if isinstance(item, str)
        ],
        "required_evidence": (
            "fresh split-role real API/Vitis A/B for this task under both "
            "legacy and generalized lanes"
        ),
    }


def _select_task_records(
    records: Sequence[Any],
    *,
    max_tasks: int,
    task_ids: Sequence[str] | None,
) -> list[dict[str, Any]]:
    eligible = [
        record
        for record in records
        if isinstance(record, Mapping) and record.get("requires_real_small_ab")
    ]
    if task_ids is None:
        return [_task_plan_record(record) for record in eligible[:max_tasks]]

    requested = _normalize_requested_task_ids(task_ids)
    if len(requested) > max_tasks:
        raise ValueError(
            "requested task count must not exceed max_tasks in the 1-3 range"
        )

    by_task_id: dict[str, Mapping[str, Any]] = {}
    for record in eligible:
        task_id = record.get("task_id")
        if isinstance(task_id, str) and task_id:
            by_task_id[task_id] = record

    missing = [task_id for task_id in requested if task_id not in by_task_id]
    if missing:
        raise ValueError(
            "requested task ids are not available for real small A/B: "
            + ", ".join(missing)
        )

    return [_task_plan_record(by_task_id[task_id]) for task_id in requested]


def _normalize_requested_task_ids(task_ids: Sequence[str]) -> list[str]:
    requested: list[str] = []
    seen: set[str] = set()
    for task_id in task_ids:
        normalized = task_id.strip()
        if not normalized:
            raise ValueError("requested task ids must be non-empty")
        if normalized in seen:
            raise ValueError(f"duplicate requested task id: {normalized}")
        requested.append(normalized)
        seen.add(normalized)
    return requested


def _run_command(
    *,
    generalized: str,
    output_root: str,
    task_flags: str,
) -> str:
    return (
        f"FPT26_QOR_RAG_GENERALIZED={generalized} "
        "FPT26_QOR_RAG_EARLY_STOP=0 "
        "PYTHONPATH=fpt26-agent-v3:. "
        "python3 -m scoring.run_p0_real_api_shard "
        "--task-root tasks "
        f"--output-root {output_root} "
        "--shard-index 0 --shard-count 1 "
        f"{task_flags}"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--triage-report", type=Path, default=DEFAULT_TRIAGE_REPORT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--task-list-output", type=Path, default=DEFAULT_TASK_LIST_OUTPUT
    )
    parser.add_argument(
        "--run-label",
        default="phase2f_qor_rag_small_ab",
        help=(
            "Label used for run roots and measured report names. The default "
            "preserves the canonical Phase 2F artifact names."
        ),
    )
    parser.add_argument("--max-tasks", type=int, default=3)
    parser.add_argument(
        "--task-id",
        action="append",
        dest="task_ids",
        help=(
            "Explicit QoR small A/B task id to include. May be repeated; "
            "selection preserves this order and still respects --max-tasks."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    triage = json.loads(args.triage_report.read_text(encoding="utf-8"))
    plan = build_plan(
        triage,
        triage_report_path=args.triage_report,
        plan_output=args.output,
        task_list_output=args.task_list_output,
        run_label=args.run_label,
        max_tasks=args.max_tasks,
        task_ids=args.task_ids,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.task_list_output.parent.mkdir(parents=True, exist_ok=True)
    args.task_list_output.write_text(plan["task_list_text"], encoding="utf-8")
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
