from pathlib import Path

from scoring.run_p0_real_api_shard import (
    classify_outcome,
    discover_tasks,
    execution_source_snapshot,
    validate_evaluator,
    validate_submission,
)


def test_discovery_is_exactly_97_unique_tasks() -> None:
    tasks = discover_tasks(Path("/workspace/tasks"))

    assert len(tasks) == 97
    assert len({task.name for task in tasks}) == 97


def test_execution_source_snapshot_is_deterministic_and_content_sensitive(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    (project / "agent").mkdir(parents=True)
    (project / "scoring").mkdir()
    (project / "agent" / "main.py").write_text("VALUE = 1\n")
    (project / "scoring" / "scoring_v3.py").write_text("SCORE = 1\n")

    first = execution_source_snapshot(project)
    second = execution_source_snapshot(project)
    assert first == second
    assert first["file_count"] == 2

    (project / "agent" / "main.py").write_text("VALUE = 2\n")
    changed = execution_source_snapshot(project)
    assert changed["tree_sha256"] != first["tree_sha256"]


def test_submission_audit_rejects_hidden_access_and_incomplete_api() -> None:
    report = {
        "task_id": "probe",
        "run_role": "submission",
        "mode": "auto",
        "status": "completed",
        "task_preflight": {
            "forbidden_artifact_accesses": 1,
            "public_files_read": ["hidden/tb.cpp"],
        },
        "execution_trace": {"grading_results": [{"stage": "hidden_csim"}]},
        "grading": {"source": "hidden"},
        "model_compliance": {"compliance_proven": False},
        "llm": {
            "client": "OpenAICompatClient",
            "token_usage": {"complete": False, "request_count": 1},
        },
        "toolchain": {"version_gate_ok": False, "part_gate_ok": False},
        "gates": {},
        "final_artifact": {},
    }

    errors = validate_submission(report, "probe")

    assert "hidden_or_reference_in_public_files" in errors
    assert "submission_contains_evaluator_results" in errors
    assert "real_api_usage_incomplete" in errors
    assert "model_compliance_unproven" in errors


def test_evaluator_audit_requires_truthful_fallback_label() -> None:
    report = {
        "task_id": "official",
        "run_role": "evaluator",
        "status": "completed",
        "llm": None,
        "grading": {"source": "hidden", "is_fallback": False},
        "execution_trace": {
            "grading_results": [
                {"stage": "hidden_csim", "ok": True},
                {"stage": "candidate_synth", "ok": True},
            ]
        },
        "cosim_ok": None,
        "toolchain": {"version_gate_ok": True, "part_gate_ok": True},
        "gates": {
            "interface": {"ok": True},
            "frequency_100mhz": {"ok": True},
            "resource_capacity": {"ok": True},
            "evaluator_acceptance": {"ok": True},
        },
    }

    errors = validate_evaluator(
        report, "official", official_task=True
    )

    assert "grading_source_hidden_expected_public_fallback" in errors
    assert "official_public_fallback_not_labelled" in errors


def test_outcome_classifies_expected_no_valid_anchor() -> None:
    submission = {"status": "completed"}
    evaluator = {"status": "failed", "stop_reason": "no_valid_anchor"}

    assert classify_outcome(submission, evaluator, "") == "no_valid_anchor"


def test_pre_llm_terminal_gate_allows_exact_zero_api_usage() -> None:
    report = {
        "task_id": "clockless",
        "run_role": "submission",
        "mode": "auto",
        "status": "failed",
        "stop_reason": "candidate_clock_invalid",
        "task_preflight": {
            "forbidden_artifact_accesses": 0,
            "public_files_read": ["task.toml", "kernel.cpp", "tb.cpp"],
        },
        "execution_trace": {"grading_results": []},
        "grading": {"source": None},
        "model_compliance": {"compliance_proven": True},
        "llm": {
            "client": "OpenAICompatClient",
            "token_usage": {
                "complete": True,
                "request_count": 0,
                "response_count": 0,
                "failed_request_count": 0,
                "unreported_response_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        },
        "toolchain": {"version_gate_ok": True, "part_gate_ok": True},
        "gates": {},
    }

    assert validate_submission(report, "clockless") == []
