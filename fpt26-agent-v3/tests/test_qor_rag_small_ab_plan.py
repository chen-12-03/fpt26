from __future__ import annotations

from pathlib import Path
import json

import pytest

from tools.finalize_qor_rag_small_ab import build_measured_report
from tools.prepare_qor_rag_small_ab_plan import build_plan


def _triage_report() -> dict:
    return {
        "phase2f_objective_status": {
            "qor_rag_generalized_offline": {
                "records": [
                    {
                        "task_id": "machsuite__aes_aes",
                        "expected_generalized_rule": (
                            "hlsgen.crypto.lookup_round_guard"
                        ),
                        "status": "offline_prompt_coverage_ready",
                        "generalized_retrieved_ids": [
                            "hlsgen.crypto.lookup_round_guard"
                        ],
                        "generalized_exact_source_measured_case_count": 0,
                        "q_hw_delta": -0.24,
                        "acceleration_delta": -7.8,
                        "hypotheses": ["missed_strategy_lane"],
                        "requires_real_small_ab": True,
                    },
                    {
                        "task_id": "polybench__cholesky",
                        "expected_generalized_rule": (
                            "hlsgen.linear_algebra.factorization_dependency_guard"
                        ),
                        "status": "offline_prompt_coverage_ready",
                        "generalized_retrieved_ids": [
                            "hlsgen.linear_algebra.factorization_dependency_guard"
                        ],
                        "generalized_exact_source_measured_case_count": 0,
                        "q_hw_delta": -0.12,
                        "acceleration_delta": -0.9,
                        "hypotheses": ["lower_tool_spend"],
                        "requires_real_small_ab": True,
                    },
                    {
                        "task_id": "machsuite__gemm_blocked",
                        "expected_generalized_rule": "hlsgen.gemm.tiled_reuse",
                        "status": "offline_prompt_coverage_ready",
                        "generalized_retrieved_ids": [
                            "hlsgen.gemm.tiled_reuse"
                        ],
                        "generalized_exact_source_measured_case_count": 0,
                        "q_hw_delta": -0.11,
                        "acceleration_delta": -65.3,
                        "hypotheses": ["under_exploration"],
                        "requires_real_small_ab": True,
                    },
                    {
                        "task_id": "not_selected_fourth",
                        "requires_real_small_ab": True,
                    },
                ]
            }
        }
    }


def test_build_qor_rag_small_ab_plan_is_non_executed_and_capped() -> None:
    plan = build_plan(
        _triage_report(),
        triage_report_path=Path("triage.json"),
        plan_output=Path("plan.json"),
        task_list_output=Path("tasks.txt"),
        max_tasks=3,
    )

    assert plan["status"] == "not_executed"
    assert plan["evidence_level"] == "execution_plan_only"
    assert plan["selected_task_count"] == 3
    assert plan["sample_policy"]["full199_allowed"] is False
    assert plan["sample_policy"]["execution_freeze_update_allowed"] is False
    assert plan["selected_tasks"][0]["task_id"] == "machsuite__aes_aes"
    assert "not_selected_fourth" not in plan["task_list_text"]


def test_build_qor_rag_small_ab_plan_commands_distinguish_lanes() -> None:
    plan = build_plan(
        _triage_report(),
        triage_report_path=Path("triage.json"),
        plan_output=Path("custom_plan.json"),
        task_list_output=Path("tasks.txt"),
        run_label="custom_qor_ab",
        max_tasks=2,
    )

    legacy = plan["lanes"]["legacy_baseline"]
    generalized = plan["lanes"]["generalized_candidate"]
    assert legacy["env"]["FPT26_QOR_RAG_GENERALIZED"] == "0"
    assert generalized["env"]["FPT26_QOR_RAG_GENERALIZED"] == "1"
    assert "FPT26_QOR_RAG_EARLY_STOP=0" in legacy["command"]
    assert "--shard-count 1" in generalized["command"]
    assert "--task-id machsuite__aes_aes" in generalized["command"]
    assert "--task-id polybench__cholesky" in generalized["command"]
    assert "--task-id machsuite__gemm_blocked" not in generalized["command"]
    assert "tools/finalize_qor_rag_small_ab.py" in plan["comparison"]["command"]
    assert "python3 -m agent.qor_rag_ab" in plan["comparison"]["raw_compare_command"]
    assert "--plan custom_plan.json" in plan["comparison"]["command"]
    assert "runs/custom_qor_ab_legacy_20260725" in legacy["command"]
    assert "custom_qor_ab_measured_20260725.json" in plan["comparison"][
        "output_report"
    ]
    assert plan["comparison"]["raw_compare_output_report"].endswith(
        "custom_qor_ab_raw_compare_20260725.json"
    )


def test_build_qor_rag_small_ab_plan_can_select_explicit_tasks() -> None:
    plan = build_plan(
        _triage_report(),
        triage_report_path=Path("triage.json"),
        plan_output=Path("rem2_plan.json"),
        task_list_output=Path("rem2_tasks.txt"),
        run_label="phase2f_qor_rag_small_ab_rem2_envfix",
        max_tasks=2,
        task_ids=["polybench__cholesky", "machsuite__gemm_blocked"],
    )

    assert plan["selected_task_count"] == 2
    assert [item["task_id"] for item in plan["selected_tasks"]] == [
        "polybench__cholesky",
        "machsuite__gemm_blocked",
    ]
    assert "machsuite__aes_aes" not in plan["task_list_text"]
    command = plan["lanes"]["generalized_candidate"]["command"]
    assert "--task-id polybench__cholesky" in command
    assert "--task-id machsuite__gemm_blocked" in command
    assert "--task-id machsuite__aes_aes" not in command
    assert "phase2f_qor_rag_small_ab_rem2_envfix_measured_20260725.json" in plan[
        "comparison"
    ]["output_report"]


def test_build_qor_rag_small_ab_plan_rejects_unavailable_explicit_task() -> None:
    with pytest.raises(ValueError, match="not available"):
        build_plan(
            _triage_report(),
            triage_report_path=Path("triage.json"),
            plan_output=Path("plan.json"),
            task_list_output=Path("tasks.txt"),
            max_tasks=2,
            task_ids=["not_a_priority_task"],
        )


def test_build_qor_rag_small_ab_plan_rejects_large_sample() -> None:
    with pytest.raises(ValueError, match="1-3"):
        build_plan(
            _triage_report(),
            triage_report_path=Path("triage.json"),
            plan_output=Path("plan.json"),
            task_list_output=Path("tasks.txt"),
            max_tasks=4,
        )


def test_finalize_small_ab_marks_measured_without_formal_acceptance(
    tmp_path: Path,
) -> None:
    plan = build_plan(
        _triage_report(),
        triage_report_path=Path("triage.json"),
        plan_output=Path("plan.json"),
        task_list_output=tmp_path / "tasks.txt",
        max_tasks=3,
    )
    task_ids = [item["task_id"] for item in plan["selected_tasks"]]
    task_list = tmp_path / "tasks.txt"
    task_list.write_text("\n".join(task_ids) + "\n", encoding="utf-8")
    baseline = tmp_path / "legacy"
    candidate = tmp_path / "generalized"
    for task_id in task_ids:
        _write_ab_pair(baseline, task_id, q_hw=0.75, requests=1, tokens=100)
        _write_ab_pair(candidate, task_id, q_hw=0.80, requests=2, tokens=120)

    report = build_measured_report(
        plan,
        plan_path=Path("plan.json"),
        baseline_roots=[baseline],
        candidate_roots=[candidate],
        task_list=task_list,
    )

    assert report["status"] == "measured"
    assert report["evidence_level"] == "small_sample_measured"
    assert report["run_label"] == "phase2f_qor_rag_small_ab"
    assert report["formal_ab_acceptance"]["applicable"] is False
    assert report["formal_ab_acceptance"]["raw_compare_passed"] is False
    assert report["guardrails"]["execution_freeze_update_allowed"] is False
    assert report["small_sample_summary"]["candidate_success_rate"] == 1.0
    assert report["small_sample_summary"]["candidate_mean_requests_per_task"] == 2.0
    assert report["small_sample_summary"][
        "candidate_mean_prompt_tokens_per_task"
    ] == 100.0
    assert report["completion_boundary"]["may_update_execution_freeze_json"] is False


def test_finalize_small_ab_rejects_task_list_mismatch(tmp_path: Path) -> None:
    plan = build_plan(
        _triage_report(),
        triage_report_path=Path("triage.json"),
        plan_output=Path("plan.json"),
        task_list_output=tmp_path / "tasks.txt",
        max_tasks=2,
    )
    task_list = tmp_path / "tasks.txt"
    task_list.write_text("machsuite__aes_aes\nwrong_task\n", encoding="utf-8")
    baseline = tmp_path / "legacy"
    candidate = tmp_path / "generalized"
    baseline.mkdir()
    candidate.mkdir()

    with pytest.raises(ValueError, match="task list does not match"):
        build_measured_report(
            plan,
            plan_path=Path("plan.json"),
            baseline_roots=[baseline],
            candidate_roots=[candidate],
            task_list=task_list,
        )


def _write_ab_pair(
    root: Path,
    task_id: str,
    *,
    q_hw: float,
    requests: int,
    tokens: int,
) -> None:
    submission = root / "submission" / task_id / "run_report.json"
    evaluator = root / "evaluator" / task_id / "run_report.json"
    submission.parent.mkdir(parents=True, exist_ok=True)
    evaluator.parent.mkdir(parents=True, exist_ok=True)
    submission.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "run_role": "submission",
                "status": "completed",
                "llm": {
                    "token_usage": {
                        "request_count": requests,
                        "prompt_tokens": tokens - 20,
                        "completion_tokens": 20,
                        "total_tokens": tokens,
                    }
                },
                "budget": {"spent": 10},
                "optimization_metrics": {},
            }
        ),
        encoding="utf-8",
    )
    evaluator.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "run_role": "evaluator",
                "status": "completed",
                "scoring": {
                    "valid": True,
                    "score": 75.0,
                    "q_hw": q_hw,
                    "latency_ratio": q_hw / 0.75,
                },
            }
        ),
        encoding="utf-8",
    )
