from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.finalize_failed_task_small_sample import build_measured_report
from tools.prepare_failed_task_small_sample_plan import build_plan


def _triage_report() -> dict:
    return {
        "phase2f_objective_status": {
            "failed_task_success_rate_offline": {
                "post_quarantine_success_rate": 0.86,
                "remaining_failure_count": 23,
                "measured_success_rate_repair_proven": False,
                "suggested_failure_small_sample_tasks": [
                    "c2hlsc__des",
                    "pp4fpga__parallel_merge_sort",
                    "amd_accel__performance_host_global_bandwidth_src_kernel",
                    "extra_not_selected",
                ],
            }
        },
        "post_quarantine_failures": {
            "remaining_failures": [
                {
                    "task_id": "c2hlsc__des",
                    "family": "c2hlsc",
                    "reason": "interface_failed",
                    "triage_class": "interface_contract_or_wrapper",
                    "gate_evidence": {
                        "submission": {
                            "status": "failed",
                            "stop_reason": "interface_failed",
                            "interface": {"ok": False},
                            "frequency_100mhz": {"frequency_mhz": 619.5},
                            "token_usage": {
                                "request_count": 2,
                                "prompt_tokens": 22,
                                "completion_tokens": 8,
                                "total_tokens": 30,
                            },
                        },
                        "final_hardware": {
                            "stage": "pipeline_synth",
                            "clock_period_ns": 1.6,
                            "frequency_mhz": 619.5,
                            "latency_worst": 91,
                            "interval_max": 92,
                        },
                    },
                },
                {
                    "task_id": "pp4fpga__parallel_merge_sort",
                    "family": "pp4fpga",
                    "reason": "frequency_failed",
                    "triage_class": "frequency_gate_or_over_parallelization",
                    "gate_evidence": {
                        "submission": {
                            "status": "failed",
                            "stop_reason": "frequency_failed",
                            "interface": {"ok": True},
                            "frequency_100mhz": {"frequency_mhz": 94.2},
                            "token_usage": {"total_tokens": 0},
                        }
                    },
                },
            ]
        },
    }


def test_failed_task_small_sample_plan_is_non_executed_and_capped() -> None:
    plan = build_plan(
        _triage_report(),
        triage_report_path=Path("triage.json"),
        task_list_output=Path("tasks.txt"),
        max_tasks=3,
    )

    assert plan["status"] == "not_executed"
    assert plan["evidence_level"] == "execution_plan_only"
    assert plan["selected_task_count"] == 3
    assert plan["sample_policy"]["full199_allowed"] is False
    assert plan["sample_policy"]["execution_freeze_update_allowed"] is False
    assert "extra_not_selected" not in plan["task_list_text"]
    assert "--task-id c2hlsc__des" in plan["run"]["command"]
    assert "--task-id pp4fpga__parallel_merge_sort" in plan["run"]["command"]
    assert "tools/finalize_failed_task_small_sample.py" in plan["audit"]["command"]
    assert "tools/audit_public_hls_sample.py" in plan["audit"]["raw_audit_command"]
    assert plan["selected_tasks"][0]["prior_failure_reason"] == "interface_failed"
    assert plan["selected_tasks"][0]["prior_token_usage"]["total_tokens"] == 30


def test_failed_task_small_sample_plan_rejects_large_sample() -> None:
    with pytest.raises(ValueError, match="1-3"):
        build_plan(
            _triage_report(),
            triage_report_path=Path("triage.json"),
            task_list_output=Path("tasks.txt"),
            max_tasks=4,
        )


def test_finalize_failed_task_small_sample_wraps_measured_audit(
    tmp_path: Path,
) -> None:
    plan = build_plan(
        _triage_report(),
        triage_report_path=Path("triage.json"),
        task_list_output=Path("tasks.txt"),
        max_tasks=2,
    )
    run_root = tmp_path / "run"
    task_ids = [item["task_id"] for item in plan["selected_tasks"]]
    _write_fake_run(run_root, task_ids)

    report = build_measured_report(
        plan,
        plan_path=Path("plan.json"),
        run_root=run_root,
    )

    assert report["status"] == "measured"
    assert report["evidence_level"] == "small_sample_measured"
    assert report["acceptance_boundary"]["is_full199_acceptance"] is False
    assert report["acceptance_boundary"][
        "may_update_execution_freeze_json"
    ] is False
    assert report["small_sample_summary"]["success_rate"] == 1.0
    assert report["small_sample_summary"]["mean_requests_per_task"] == 1.0
    assert report["small_sample_summary"]["mean_tokens_per_task"] == 120.0
    assert report["small_sample_summary"]["mean_score_completed_tasks"] == 75.0


def test_finalize_failed_task_small_sample_accepts_runner_discovery_order(
    tmp_path: Path,
) -> None:
    plan = build_plan(
        _triage_report(),
        triage_report_path=Path("triage.json"),
        task_list_output=Path("tasks.txt"),
        max_tasks=3,
    )
    run_root = tmp_path / "run"
    task_ids = [item["task_id"] for item in plan["selected_tasks"]]
    _write_fake_run(run_root, list(reversed(task_ids)))

    report = build_measured_report(
        plan,
        plan_path=Path("plan.json"),
        run_root=run_root,
    )

    assert report["tasks"] == task_ids
    assert [
        record["task_id"] for record in report["raw_audit"]["records"]
    ] == task_ids
    assert report["small_sample_summary"]["success_rate"] == 1.0


def test_finalize_failed_task_small_sample_rejects_task_mismatch(
    tmp_path: Path,
) -> None:
    plan = build_plan(
        _triage_report(),
        triage_report_path=Path("triage.json"),
        task_list_output=Path("tasks.txt"),
        max_tasks=2,
    )
    run_root = tmp_path / "run"
    _write_fake_run(run_root, ["c2hlsc__des", "wrong_task"])

    with pytest.raises(ValueError, match="does not match"):
        build_measured_report(
            plan,
            plan_path=Path("plan.json"),
            run_root=run_root,
        )


def _write_fake_run(run_root: Path, task_ids: list[str]) -> None:
    records = []
    for task_id in task_ids:
        task_dir = run_root / "tasks" / task_id / "task"
        task_dir.mkdir(parents=True, exist_ok=True)
        attempt = run_root / "tasks" / task_id / "attempt_001"
        submission = attempt / "submission" / task_id / "run_report.json"
        evaluator = attempt / "evaluator" / task_id / "run_report.json"
        submission.parent.mkdir(parents=True, exist_ok=True)
        evaluator.parent.mkdir(parents=True, exist_ok=True)
        submission.write_text(
            json.dumps(_submission_report(task_id)),
            encoding="utf-8",
        )
        evaluator.write_text(
            json.dumps(_evaluator_report(task_id)),
            encoding="utf-8",
        )
        records.append(
            {
                "task_id": task_id,
                "task_dir": str(task_dir),
                "official_task": False,
                "outcome": "completed",
                "submission": {"report": str(submission)},
                "evaluator": {"report": str(evaluator)},
            }
        )
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "shard_summary.json").write_text(
        json.dumps(
            {
                "selected_task_count": len(task_ids),
                "completed_record_count": len(task_ids),
                "execution_source": {"stable": True},
                "records": records,
            }
        ),
        encoding="utf-8",
    )


def _submission_report(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "run_role": "submission",
        "mode": "auto",
        "status": "completed",
        "task_preflight": {
            "public_files_read": [],
            "forbidden_artifact_accesses": 0,
        },
        "model_compliance": {"compliance_proven": True},
        "llm": {
            "client": "OpenAICompatClient",
            "token_usage": {
                "complete": True,
                "request_count": 1,
                "response_count": 1,
                "failed_request_count": 0,
                "unreported_response_count": 0,
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        },
        "toolchain": {"version_gate_ok": True, "part_gate_ok": True},
        "gates": {
            "interface": {"ok": True},
            "frequency_100mhz": {"ok": True, "frequency_mhz": 200.0},
            "resource_capacity": {"ok": True},
            "public_acceptance": {"ok": True},
        },
        "final_artifact": {"fully_verified": True},
        "budget": {"spent": 10},
    }


def _evaluator_report(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "run_role": "evaluator",
        "status": "completed",
        "grading": {"source": "public_fallback", "is_fallback": True},
        "execution_trace": {
            "grading_results": [
                {"stage": "hidden_csim", "ok": True},
                {"stage": "candidate_synth", "ok": True},
            ]
        },
        "toolchain": {"version_gate_ok": True, "part_gate_ok": True},
        "gates": {
            "interface": {"ok": True},
            "frequency_100mhz": {"ok": True},
            "resource_capacity": {"ok": True},
            "evaluator_acceptance": {"ok": True},
        },
        "scoring": {"valid": True, "score": 75.0, "q_hw": 0.75},
    }
