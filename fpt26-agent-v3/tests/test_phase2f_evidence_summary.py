from __future__ import annotations

from tools.summarize_phase2f_evidence import build_summary


def test_phase2f_summary_reports_average_tokens_success_and_open_evidence() -> None:
    summary = build_summary(
        full199={
            "fresh_evidence_only": True,
            "workflow_integrity_ok": True,
            "coverage": {
                "expected_task_count": 4,
                "audit_error_task_count": 0,
                "outcome_counts": {"completed": 3, "failed": 1},
                "stop_reason_counts": {"frequency_failed": 1},
            },
            "model_and_api": {
                "tasks_with_api_requests": 3,
                "token_totals": {
                    "request_count": 6,
                    "total_tokens": 1200,
                },
            },
            "resource_consumption": {
                "credits_spent": 40,
                "tool_call_count": 12,
            },
            "target_gates": {"interface_pass_count": 3},
            "tasks": {
                "a": _task(score=70.0, q_hw=0.70, credits=10),
                "b": _task(score=80.0, q_hw=0.80, credits=10),
                "c": _task(score=90.0, q_hw=0.90, credits=10),
                "d": {"submission": {"budget": {"spent": 10}}},
            },
        },
        formal_ab={
            "task_count": 12,
            "passed": False,
            "baseline": {"q_hw_geomean": 0.8, "mean_tokens_per_task": 100.0},
            "candidate": {"q_hw_geomean": 0.7, "mean_tokens_per_task": 90.0},
            "comparison": {
                "correctness_preservation_rate": 1.0,
                "q_hw_geomean_relative_change": -0.125,
            },
            "gates": {"q_hw_geomean_improves_1pct": False},
        },
        hardcoding={
            "status": "static_audit_only",
            "overall_conclusion": {
                "high_risk_task_answer_hardcoding_found": False,
                "generalized_runtime_ready": True,
                "summary": "No task-specific branch.",
            },
            "literal_scan_summary": {
                "agent_runtime_task_id_literal_count": 0,
                "agent_runtime_workload_literal_count": 7,
            },
            "risk_counts": {"medium": 2},
        },
        triage={
            "phase2f_objective_status": {
                "completion": {
                    "objective_complete": False,
                    "blocking_missing_evidence": ["small A/B missing"],
                },
                "qor_rag_generalized_offline": {
                    "measured_qor_repair_proven": False,
                },
                "failed_task_success_rate_offline": {
                    "measured_success_rate_repair_proven": False,
                },
            }
        },
        small_ab_plan={
            "status": "not_executed",
            "evidence_level": "execution_plan_only",
            "selected_task_count": 2,
            "selected_tasks": [{"task_id": "a"}, {"task_id": "b"}],
            "sample_policy": {
                "measured_report_required": True,
                "full199_allowed": False,
                "execution_freeze_update_allowed": False,
            },
            "comparison": {"command": "finalize"},
        },
        failed_task_plan={
            "status": "not_executed",
            "evidence_level": "execution_plan_only",
            "selected_task_count": 2,
            "selected_tasks": [
                {"task_id": "c2hlsc__des", "prior_failure_reason": "interface_failed"},
                {
                    "task_id": "pp4fpga__parallel_merge_sort",
                    "prior_failure_reason": "frequency_failed",
                },
            ],
            "offline_context": {
                "post_quarantine_success_rate": 0.86,
                "remaining_failure_count": 23,
            },
            "sample_policy": {
                "full199_allowed": False,
                "execution_freeze_update_allowed": False,
            },
            "run": {"command": "run"},
            "audit": {"command": "audit"},
        },
        qor_small_ab_measured=[
            {
                "status": "measured",
                "evidence_level": "small_sample_measured",
                "run_label": "phase2f_qor_rag_small_ab",
                "task_count": 2,
                "tasks": ["a", "b"],
                "small_sample_summary": {
                    "candidate_success_rate": 1.0,
                    "candidate_mean_tokens_per_task": 120.0,
                    "candidate_mean_requests_per_task": 2.0,
                    "candidate_q_hw_geomean": 0.82,
                    "q_hw_relative_change": 0.02,
                    "acceleration_relative_change": 0.05,
                },
                "completion_boundary": {
                    "may_claim_qor_repair": True,
                    "may_update_execution_freeze_json": False,
                },
            },
            {
                "status": "measured",
                "evidence_level": "small_sample_measured",
                "run_label": "phase2f_qor_rag_small_ab_aes1",
                "task_count": 1,
                "tasks": ["machsuite__aes_aes"],
                "small_sample_summary": {
                    "candidate_success_rate": 1.0,
                    "candidate_mean_tokens_per_task": 130.0,
                    "candidate_mean_requests_per_task": 2.0,
                    "candidate_q_hw_geomean": 0.84,
                    "q_hw_relative_change": 0.04,
                    "acceleration_relative_change": 0.06,
                },
                "completion_boundary": {
                    "may_claim_qor_repair": True,
                    "may_update_execution_freeze_json": False,
                },
            },
        ],
        failed_task_measured=[
            {
                "status": "measured",
                "evidence_level": "small_sample_measured",
                "task_count": 2,
                "tasks": ["c2hlsc__des", "pp4fpga__parallel_merge_sort"],
                "small_sample_summary": {
                    "success_rate": 0.5,
                    "completed": 1.0,
                    "failed": 1.0,
                    "failure_reason_counts": {"frequency_failed": 1},
                    "mean_tokens_per_task": 500.0,
                    "mean_requests_per_task": 1.0,
                    "mean_score_completed_tasks": 75.0,
                },
                "acceptance_boundary": {
                    "may_claim_global_success_rate_repair": False,
                    "may_update_execution_freeze_json": False,
                },
            },
            {
                "status": "measured",
                "evidence_level": "small_sample_measured",
                "run_label": "c2hlsc_des_finalgatefix",
                "task_count": 1,
                "tasks": ["c2hlsc__des"],
                "small_sample_summary": {
                    "success_rate": 1.0,
                    "completed": 1.0,
                    "failed": 0.0,
                    "failure_reason_counts": {},
                    "mean_tokens_per_task": 600.0,
                    "mean_requests_per_task": 2.0,
                    "mean_score_completed_tasks": 74.86,
                },
                "acceptance_boundary": {
                    "may_claim_global_success_rate_repair": False,
                    "may_update_execution_freeze_json": False,
                },
            },
        ],
        small_sample_attempts=[
            {
                "status": "preflight_failed",
                "evidence_level": "environment_preflight_only",
                "run_label": "phase2f_qor_rag_small_ab_aes1",
                "task_count": 1,
                "tasks": ["machsuite__aes_aes"],
                "lane_attempted": "legacy_baseline",
                "candidate_lane_run": False,
                "failure": {
                    "type": "TaskPreflightError",
                    "message": "configured Vitis environment did not produce a valid version banner",
                },
                "metrics": {
                    "success_rate": 0.0,
                    "mean_tokens_per_task": None,
                    "mean_requests_per_task": None,
                },
                "completion_boundary": {
                    "may_claim_qor_repair": False,
                    "may_update_execution_freeze_json": False,
                },
            }
        ],
        single_dot={
            "task_count": 1,
            "candidate": {
                "valid": True,
                "score": 76.5,
                "q_hw": 0.7666,
                "api_requests": 1,
                "total_tokens": 4234,
            },
            "comparison": {"q_hw_delta": 0.0},
        },
        public_sample={
            "selected_task_count": 2,
            "outcome_counts": {"completed": 1, "failed": 1},
            "model_and_api": {"request_count": 4, "total_tokens": 1000},
        },
        retrieval_eval={"case_count": 32, "recall_at_3": 0.90625, "passed": True},
    )

    full = summary["full199_acceptance"]
    assert summary["constraints"]["summary_generation_api_or_vitis_run"] is False
    assert summary["constraints"]["small_sample_attempts_included"] is True
    assert full["success_rate"] == 0.75
    assert full["mean_tokens_per_task"] == 300.0
    assert full["mean_requests_per_task"] == 1.5
    assert full["mean_tokens_per_api_task"] == 400.0
    assert full["mean_score_valid_tasks"] == 80.0
    assert full["mean_q_hw_valid_tasks"] == 0.8
    assert full["mean_credits_per_task"] == 10.0
    assert summary["formal_qor_rag_ab"]["failed_gates"] == [
        "q_hw_geomean_improves_1pct"
    ]
    assert summary["hardcoding_audit"][
        "high_risk_task_answer_hardcoding_found"
    ] is False
    assert summary["hardcoding_audit"][
        "agent_runtime_task_id_literal_count"
    ] == 0
    assert summary["hardcoding_audit"][
        "agent_runtime_workload_literal_count"
    ] == 7
    assert summary["small_ab_plan"]["full199_allowed"] is False
    assert summary["failed_task_small_sample_plan"]["selected_task_ids"] == [
        "c2hlsc__des",
        "pp4fpga__parallel_merge_sort",
    ]
    assert summary["failed_task_small_sample_plan"][
        "selected_failure_reasons"
    ] == ["interface_failed", "frequency_failed"]
    assert summary["measured_small_samples"]["qor_rag_small_ab"][
        "candidate_success_rate"
    ] == 1.0
    assert summary["measured_small_samples"]["qor_rag_small_ab"][
        "run_label"
    ] == "phase2f_qor_rag_small_ab"
    assert summary["measured_small_samples"][
        "qor_rag_small_ab:phase2f_qor_rag_small_ab_aes1"
    ]["tasks"] == ["machsuite__aes_aes"]
    assert summary["measured_small_samples"]["qor_rag_small_ab"][
        "may_update_execution_freeze_json"
    ] is False
    assert summary["measured_small_samples"]["failed_task_small_sample"][
        "success_rate"
    ] == 0.5
    assert summary["measured_small_samples"]["failed_task_small_sample"][
        "failure_reason_counts"
    ] == {"frequency_failed": 1}
    assert summary["measured_small_samples"][
        "failed_task_small_sample:c2hlsc_des_finalgatefix"
    ]["success_rate"] == 1.0
    attempt = summary["small_sample_attempts"][
        "small_sample_attempt:phase2f_qor_rag_small_ab_aes1:legacy_baseline"
    ]
    assert attempt["status"] == "preflight_failed"
    assert attempt["candidate_lane_run"] is False
    assert attempt["mean_tokens_per_task"] is None
    assert attempt["may_claim_qor_repair"] is False
    assert summary["objective_status"]["objective_complete"] is False
    assert summary["objective_status"]["fresh_measured_qor_small_sample_count"] == 2
    assert summary["objective_status"]["fresh_measured_qor_small_sample_tasks"] == [
        "a",
        "b",
        "machsuite__aes_aes",
    ]
    assert summary["objective_status"]["current_blocking_missing_evidence"] == [
        "execution-freeze.json must remain stale until an explicit fresh full199 acceptance",
    ]
    assert summary["recommended_next_actions"][0].startswith(
        "Treat the measured QoR small A/B as supportive"
    )
    assert any(
        "failed-task measured sample" in action
        for action in summary["recommended_next_actions"]
    )
    assert summary["recommended_next_actions"][-1].startswith(
        "Keep execution-freeze.json unchanged"
    )
    assert summary["real_small_samples"]["public_hls_12_task_sample"][
        "success_rate"
    ] == 0.5


def _task(*, score: float, q_hw: float, credits: int) -> dict:
    return {
        "evaluator": {
            "scoring": {
                "valid": True,
                "score": score,
                "q_hw": q_hw,
            }
        },
        "submission": {"budget": {"spent": credits}},
    }
