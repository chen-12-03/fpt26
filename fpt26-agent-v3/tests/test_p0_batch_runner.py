from pathlib import Path

import pytest

from scoring.run_p0_real_api_shard import (
    EXPECTED_TASK_COUNT,
    _summary,
    build_evaluator_command,
    classify_outcome,
    discover_tasks,
    execution_source_snapshot,
    load_excluded_task_ids,
    submission_requires_evaluator,
    validate_evaluator,
    validate_submission,
)


def test_discovery_is_exactly_expected_unique_tasks() -> None:
    task_root = Path("/workspace/tasks")
    if not task_root.exists():
        pytest.skip("task corpus is only mounted at /workspace/tasks in Docker")

    tasks = discover_tasks(task_root)

    assert len(tasks) == EXPECTED_TASK_COUNT
    assert len({task.name for task in tasks}) == EXPECTED_TASK_COUNT


def test_discovery_can_explicitly_quarantine_metric_incomplete_tasks(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "generated"
    official = tmp_path / "official"
    generated.mkdir()
    official.mkdir()
    excluded = {
        "amd_accel__metric_missing_a",
        "amd_intro__metric_missing_b",
    }
    generated_names = [
        *sorted(excluded),
        *[f"generated_{index:03d}" for index in range(194)],
    ]
    for name in generated_names:
        task_dir = generated / name
        task_dir.mkdir()
        (task_dir / "task.toml").write_text("task_id = \"x\"\n")
    for index in range(3):
        task_dir = official / f"official_{index}"
        task_dir.mkdir()
        (task_dir / "task.toml").write_text("task_id = \"x\"\n")

    tasks = discover_tasks(tmp_path, excluded_task_ids=excluded)

    assert len(tasks) == EXPECTED_TASK_COUNT - len(excluded)
    assert not ({task.name for task in tasks} & excluded)


def test_discovery_supports_direct_track_a_150_corpus(tmp_path: Path) -> None:
    task_root = tmp_path / "track_a_150"
    task_root.mkdir()
    for index in range(150):
        task_dir = task_root / f"track_a_task_{index:03d}"
        task_dir.mkdir()
        (task_dir / "task.toml").write_text("task_id = \"x\"\n")

    tasks = discover_tasks(task_root)

    assert len(tasks) == 150
    assert len({task.name for task in tasks}) == 150


def test_exclusion_loader_accepts_offline_triage_report(tmp_path: Path) -> None:
    path = tmp_path / "triage.json"
    path.write_text(
        """
{
  "full199_failures": {
    "public_hls_metric_completeness": {
      "metric_incomplete_task_ids": [
        "amd_accel__a",
        "amd_intro__b"
      ]
    }
  }
}
""".lstrip(),
        encoding="utf-8",
    )

    assert load_excluded_task_ids(path) == {"amd_accel__a", "amd_intro__b"}


def test_exclusion_loader_accepts_public_hls_validated_manifest(
    tmp_path: Path,
) -> None:
    path = tmp_path / "public_hls_validated_tasks_manifest.json"
    path.write_text(
        """
{
  "scoreable_gate": {
    "allow_missing_score_metrics": false,
    "metric_incomplete_task_ids": [
      "amd_accel__metric_missing_a",
      "amd_intro__metric_missing_b"
    ]
  }
}
""".lstrip(),
        encoding="utf-8",
    )

    assert load_excluded_task_ids(path) == {
        "amd_accel__metric_missing_a",
        "amd_intro__metric_missing_b",
    }


def test_exclusion_loader_rejects_duplicate_task_ids(tmp_path: Path) -> None:
    path = tmp_path / "excluded.json"
    path.write_text(
        '["amd_accel__a", "amd_accel__a"]\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="duplicate excluded task IDs"):
        load_excluded_task_ids(path)


def test_discovery_rejects_unknown_excluded_task_id(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    official = tmp_path / "official"
    generated.mkdir()
    official.mkdir()
    for index in range(196):
        task_dir = generated / f"generated_{index:03d}"
        task_dir.mkdir()
        (task_dir / "task.toml").write_text("task_id = \"x\"\n")
    for index in range(3):
        task_dir = official / f"official_{index}"
        task_dir.mkdir()
        (task_dir / "task.toml").write_text("task_id = \"x\"\n")

    with pytest.raises(RuntimeError, match="outside the corpus"):
        discover_tasks(tmp_path, excluded_task_ids={"missing_task"})


def test_summary_records_quarantine_without_full199_claim() -> None:
    quarantine = {
        "enabled": True,
        "source": "tasks/generated/public_hls_validated_tasks_manifest.json",
        "excluded_task_count": 27,
        "excluded_task_ids": ["public_metric_missing"],
        "effective_task_count": EXPECTED_TASK_COUNT - 27,
        "original_expected_task_count": EXPECTED_TASK_COUNT,
    }

    summary = _summary(
        shard_index=0,
        shard_count=1,
        selected_count=EXPECTED_TASK_COUNT - 27,
        started=0.0,
        records=[],
        source_start={"tree_sha256": "same"},
        source_current={"tree_sha256": "same"},
        quarantine=quarantine,
    )

    assert summary["purpose"] == "p0_split_role_real_api_vitis_acceptance"
    assert summary["task_quarantine"] == quarantine
    assert "full199" not in summary["purpose"]


def test_formal_evaluator_command_always_links_submission_evidence() -> None:
    command = build_evaluator_command(
        task_dir=Path("/workspace/tasks/official/projection_bugfix"),
        final_kernel=Path("/workspace/runs/final.cpp"),
        submission_evidence=Path("/workspace/runs/submission_evidence.json"),
        output_root=Path("/workspace/runs/evaluator"),
    )

    evidence_index = command.index("--submission-evidence")
    assert command[evidence_index + 1].endswith("submission_evidence.json")
    assert command[command.index("--run-role") + 1] == "evaluator"


def test_official_fresh_launcher_links_submission_evidence() -> None:
    launcher = (
        Path(__file__).resolve().parents[1]
        / "run-p0-official-fresh.sh"
    ).read_text(encoding="utf-8")

    assert "--submission-evidence" in launcher
    assert "submission_evidence.json" in launcher


def test_only_completed_submission_requires_evaluator(
    tmp_path: Path,
) -> None:
    final_kernel = tmp_path / "final.cpp"
    final_kernel.write_text("void top() {}\n")

    assert submission_requires_evaluator(
        {"status": "completed"}, final_kernel
    )
    assert not submission_requires_evaluator(
        {"status": "failed", "stop_reason": "interface_failed"},
        final_kernel,
    )
    assert not submission_requires_evaluator(
        {"status": "completed"}, tmp_path / "missing.cpp"
    )


def test_execution_source_snapshot_is_deterministic_and_content_sensitive(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    (project / "agent").mkdir(parents=True)
    (project / "agent" / "knowledge_assets").mkdir()
    (project / "agent" / "knowledge_assets" / "nested").mkdir()
    (project / "scoring").mkdir()
    (project / "agent" / "main.py").write_text("VALUE = 1\n")
    (project / "agent" / "knowledge_assets" / "seeds.json").write_text(
        '{"entries":[]}\n'
    )
    (project / "agent" / "knowledge_assets" / "nested" / "case.json").write_text(
        '{"id":"nested"}\n'
    )
    (project / "scoring" / "scoring_v3.py").write_text("SCORE = 1\n")

    first = execution_source_snapshot(project)
    second = execution_source_snapshot(project)
    assert first == second
    assert first["file_count"] == 4

    (project / "agent" / "main.py").write_text("VALUE = 2\n")
    changed = execution_source_snapshot(project)
    assert changed["tree_sha256"] != first["tree_sha256"]

    (project / "agent" / "main.py").write_text("VALUE = 1\n")
    (project / "agent" / "knowledge_assets" / "seeds.json").write_text(
        '{"entries":[{"id":"changed"}]}\n'
    )
    changed_asset = execution_source_snapshot(project)
    assert changed_asset["tree_sha256"] != first["tree_sha256"]

    (project / "agent" / "knowledge_assets" / "seeds.json").write_text(
        '{"entries":[]}\n'
    )
    (project / "agent" / "knowledge_assets" / "nested" / "case.json").write_text(
        '{"id":"changed-nested"}\n'
    )
    changed_nested_asset = execution_source_snapshot(project)
    assert changed_nested_asset["tree_sha256"] != first["tree_sha256"]


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
    assert "public_fallback_not_labelled" in errors


def test_evaluator_audit_allows_public_only_generated_fallback() -> None:
    report = {
        "task_id": "public_generated",
        "run_role": "evaluator",
        "status": "completed",
        "llm": None,
        "grading": {"source": "public_fallback", "is_fallback": True},
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
        report,
        "public_generated",
        official_task=False,
        expected_grading_source="public_fallback",
    )

    assert errors == []


def test_evaluator_audit_rejects_legacy_generated_fallback() -> None:
    report = {
        "task_id": "legacy_generated",
        "run_role": "evaluator",
        "status": "completed",
        "llm": None,
        "grading": {"source": "public_fallback", "is_fallback": True},
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
        report,
        "legacy_generated",
        official_task=False,
        expected_grading_source="hidden",
    )

    assert "grading_source_public_fallback_expected_hidden" in errors
    assert "generated_hidden_grading_mislabelled_fallback" in errors


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
