from pathlib import Path

import pytest

from scoring.run_p0_real_api_shard import (
    EXPECTED_TASK_COUNT,
    TRACK_A_150_TOOL_TIMEOUT_DEFAULTS_S,
    _summary,
    build_evaluator_command,
    build_submission_command,
    classify_outcome,
    discover_tasks,
    execution_source_snapshot,
    load_excluded_task_ids,
    pair_task_roots,
    resolve_cli_task_roots,
    resolve_llm_run_contract,
    resolve_tool_timeout_policy,
    submission_requires_evaluator,
    validate_evaluator,
    validate_submission,
)


def test_track_a_150_uses_scoped_tool_timeout_defaults(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for env_name in (
        "LLM4HLS_CSIM_TIMEOUT_S",
        "LLM4HLS_SYNTH_TIMEOUT_S",
        "LLM4HLS_COSIM_TIMEOUT_S",
    ):
        monkeypatch.delenv(env_name, raising=False)

    policy = resolve_tool_timeout_policy(tmp_path / "track_a_150")

    assert policy is not None
    assert policy["scope"] == "track_a_150"
    assert policy["task_root_kind"] == "track_a_150"
    assert policy["source"] == "track_a_150_runner_defaults"
    assert policy["values_s"] == TRACK_A_150_TOOL_TIMEOUT_DEFAULTS_S
    assert policy["env_overrides"] == {
        "LLM4HLS_CSIM_TIMEOUT_S": "30.0",
        "LLM4HLS_SYNTH_TIMEOUT_S": "180.0",
        "LLM4HLS_COSIM_TIMEOUT_S": "240.0",
    }


def test_tool_timeout_policy_does_not_affect_other_corpora(
    tmp_path: Path,
) -> None:
    assert resolve_tool_timeout_policy(tmp_path / "generated") is None


@pytest.mark.parametrize(
    "task_root",
    [
        Path("/workspace/tasks/track_a_150_v2"),
        Path("/workspace/releases/track_a_150_v2_20260910/public_agent"),
        Path("/workspace/releases/track_a_150_v2_20260910/evaluator_private"),
    ],
)
def test_track_a_150_v2_and_release_roots_use_scoped_timeouts(
    task_root: Path,
) -> None:
    policy = resolve_tool_timeout_policy(task_root)

    assert policy is not None
    assert policy["scope"] == "track_a_150"
    assert policy["task_root_kind"] == task_root.name


def test_track_a_150_tool_timeout_allows_explicit_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LLM4HLS_SYNTH_TIMEOUT_S", "210")

    policy = resolve_tool_timeout_policy(tmp_path / "track_a_150")

    assert policy is not None
    assert policy["source"] == "environment_override"
    assert policy["values_s"]["synth"] == 210.0
    assert policy["explicit_override_names"] == [
        "LLM4HLS_SYNTH_TIMEOUT_S"
    ]


def test_track_a_150_tool_timeout_rejects_non_finite_value(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LLM4HLS_COSIM_TIMEOUT_S", "nan")

    with pytest.raises(RuntimeError, match="must be positive"):
        resolve_tool_timeout_policy(tmp_path / "track_a_150")


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
        *[f"generated_{index:03d}" for index in range(195)],
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


def test_discovery_supports_direct_track_a_150_v2_corpus(tmp_path: Path) -> None:
    task_root = tmp_path / "track_a_150_v2"
    task_root.mkdir()
    for index in range(150):
        task_dir = task_root / f"track_a_task_{index:03d}"
        task_dir.mkdir()
        (task_dir / "task.toml").write_text("task_id = \"x\"\n")

    tasks = discover_tasks(task_root)

    assert len(tasks) == 150


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
    for index in range(197):
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


def test_openrouter_contract_is_explicit_and_contains_no_credential(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("FPT26_LLM_TEMPERATURE", "0.2")
    monkeypatch.setenv("FPT26_LLM_MAX_TOKENS", "8192")

    contract = resolve_llm_run_contract(
        "openrouter", "qwen/qwen3-coder"
    )

    assert contract == {
        "backend": "openrouter",
        "expected_client": "OpenRouterClient",
        "model": "qwen/qwen3-coder",
        "temperature": 0.2,
        "max_tokens": 8192,
        "provider": "openrouter",
        "api_origin": "https://openrouter.ai",
    }
    assert "test-secret" not in str(contract)


def test_openrouter_contract_rejects_missing_key_or_non_openrouter_endpoint(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="credential missing"):
        resolve_llm_run_contract("openrouter", "qwen/qwen3-coder")

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://example.invalid/v1")
    with pytest.raises(RuntimeError, match="must use https://openrouter.ai"):
        resolve_llm_run_contract("openrouter", "qwen/qwen3-coder")


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


def _write_split_task(root: Path, task_id: str, kernel: str = "void top() {}\n") -> Path:
    task_dir = root / task_id
    task_dir.mkdir(parents=True)
    (task_dir / "task.toml").write_text(
        f'''task_id = "{task_id}"
task_type = "repair"
difficulty = 2
top = "top"
kernel_file = "kernel.cpp"
header_files = []
public_tb = "tb.cpp"
requires_cosim = false
initial_condition = "invalid"

[budget]
max_tool_calls = 10

[target]
part = "xcu55c-fsvh2892-2L-e"
clock_ns = 5.0
minimum_frequency_mhz = 100.0
''',
        encoding="utf-8",
    )
    (task_dir / "kernel.cpp").write_text(kernel, encoding="utf-8")
    (task_dir / "tb.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    return task_dir


def test_split_task_roots_pair_only_matching_public_contracts(tmp_path: Path) -> None:
    public_root = tmp_path / "public"
    evaluator_root = tmp_path / "evaluator"
    public_task = _write_split_task(public_root, "ta2_cr_001")
    evaluator_task = _write_split_task(evaluator_root, "ta2_cr_001")
    (evaluator_task / "hidden").mkdir()
    (evaluator_task / "reference").mkdir()

    assert pair_task_roots(public_root, evaluator_root) == [
        (public_task.resolve(), evaluator_task.resolve())
    ]


def test_split_task_roots_reject_public_input_drift(tmp_path: Path) -> None:
    public_root = tmp_path / "public"
    evaluator_root = tmp_path / "evaluator"
    _write_split_task(public_root, "ta2_cr_001")
    evaluator_task = _write_split_task(
        evaluator_root, "ta2_cr_001", kernel="void top() { int x = 1; }\n"
    )
    (evaluator_task / "hidden").mkdir()
    (evaluator_task / "reference").mkdir()

    with pytest.raises(RuntimeError, match="public task contract differs"):
        pair_task_roots(public_root, evaluator_root)


def test_cli_task_roots_require_combined_or_complete_split_pair(tmp_path: Path) -> None:
    combined = tmp_path / "combined"
    public = tmp_path / "public"
    evaluator = tmp_path / "evaluator"

    assert resolve_cli_task_roots(combined, None, None) == (
        combined.resolve(), combined.resolve()
    )
    assert resolve_cli_task_roots(None, public, evaluator) == (
        public.resolve(), evaluator.resolve()
    )
    with pytest.raises(RuntimeError, match="provide --task-root"):
        resolve_cli_task_roots(None, public, None)
    with pytest.raises(RuntimeError, match="cannot be combined"):
        resolve_cli_task_roots(combined, public, evaluator)


@pytest.mark.parametrize(
    ("competition", "expected"),
    [(False, False), (True, True)],
)
def test_submission_command_preserves_competition_mode(
    competition: bool,
    expected: bool,
) -> None:
    command = build_submission_command(
        task_dir=Path("/workspace/tasks/generated/task_001"),
        backend="custom",
        output_root=Path("/workspace/runs/submission"),
        competition=competition,
    )

    assert ("--competition" in command) is expected
    assert command[command.index("--run-role") + 1] == "submission"


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


def test_submission_audit_locks_openrouter_client_and_model() -> None:
    report = {
        "task_id": "clockless",
        "run_role": "submission",
        "mode": "auto",
        "status": "failed",
        "task_preflight": {
            "forbidden_artifact_accesses": 0,
            "public_files_read": ["task.toml", "kernel.cpp", "tb.cpp"],
        },
        "execution_trace": {"grading_results": []},
        "grading": {"source": None},
        "model_compliance": {"compliance_proven": True},
        "llm": {
            "client": "OpenRouterClient",
            "model": "qwen/qwen3-coder",
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

    assert validate_submission(
        report,
        "clockless",
        expected_client="OpenRouterClient",
        expected_model="qwen/qwen3-coder",
    ) == []

    errors = validate_submission(
        report,
        "clockless",
        expected_client="OpenAICompatClient",
        expected_model="different/model",
    )
    assert "real_custom_api_client_missing" in errors
    assert "llm_model_mismatch" in errors


def _clean_submission_report(**overrides):
    """A submission report whose only remaining signal is the one under test."""
    report = {
        "task_id": "t",
        "run_role": "submission",
        "mode": "auto",
        "status": "failed",
        "task_preflight": {
            "forbidden_artifact_accesses": 0,
            "public_files_read": [],
        },
        "execution_trace": {"grading_results": []},
        "grading": None,
        "model_compliance": {"compliance_proven": True},
        "llm": {
            "client": "OpenAICompatClient",
            "model": "qwen3.6-27b",
            "token_usage": {
                "complete": True,
                "request_count": 2,
                "response_count": 2,
                "failed_request_count": 0,
                "unreported_response_count": 0,
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        },
        "toolchain": {
            "version_gate_ok": True,
            "part_gate_ok": True,
            "required_part": "xcu55c-fsvh2892-2L-e",
            "observed_parts": ["xcu55c-fsvh2892-2L-e"],
        },
        "gates": {},
        "final_artifact": {},
    }
    report.update(overrides)
    return report


def test_submission_audit_is_clean_for_a_failed_attempt_on_the_pinned_part() -> None:
    assert validate_submission(_clean_submission_report(), "t") == []


def test_submission_audit_reports_api_failures_apart_from_accounting() -> None:
    """A failed request is an infrastructure fault, not a bookkeeping gap."""
    report = _clean_submission_report()
    report["llm"]["token_usage"].update(
        {"request_count": 3, "response_count": 2, "failed_request_count": 1}
    )

    errors = validate_submission(report, "t")

    assert errors == ["api_requests_failed"]


def test_submission_audit_flags_a_different_part_when_one_was_observed() -> None:
    report = _clean_submission_report(
        toolchain={
            "version_gate_ok": True,
            "part_gate_ok": False,
            "required_part": "xcu55c-fsvh2892-2L-e",
            "observed_parts": ["xczu7ev-ffvc1156-2-e"],
        }
    )

    assert "u55c_part_gate_failed" in validate_submission(report, "t")


def test_submission_audit_treats_an_unobserved_part_as_unproven() -> None:
    """No tool reached the driver: there is no evidence to contradict."""
    report = _clean_submission_report(
        toolchain={
            "version_gate_ok": True,
            "part_gate_ok": False,
            "required_part": "xcu55c-fsvh2892-2L-e",
            "observed_parts": [],
        }
    )

    assert "u55c_part_gate_failed" not in validate_submission(report, "t")


def _clean_evaluator_report(**overrides):
    report = {
        "task_id": "t",
        "run_role": "evaluator",
        "status": "failed",
        "llm": None,
        "grading": {"source": "hidden", "is_fallback": False},
        "execution_trace": {
            "grading_results": [
                {"stage": "hidden_csim", "ok": False},
                {"stage": "candidate_synth", "ok": False},
            ]
        },
        "cosim_ok": None,
        "toolchain": {
            "version_gate_ok": True,
            "observed_parts": ["xcu55c-fsvh2892-2L-e"],
            "required_part": "xcu55c-fsvh2892-2L-e",
        },
        "gates": {},
    }
    report.update(overrides)
    return report


def test_evaluator_audit_accepts_a_candidate_that_failed_hidden_grading() -> None:
    """Grading a candidate and rejecting it is a result, not a missing record."""
    assert (
        validate_evaluator(_clean_evaluator_report(), "t", official_task=False)
        == []
    )


def test_evaluator_audit_flags_a_grading_stage_that_never_ran() -> None:
    report = _clean_evaluator_report()
    report["execution_trace"]["grading_results"] = [
        {"stage": "candidate_synth", "ok": False}
    ]

    assert "hidden_csim_missing" in validate_evaluator(
        report, "t", official_task=False
    )


def test_evaluator_audit_flags_a_hidden_cosim_that_was_never_run() -> None:
    report = _clean_evaluator_report(cosim_ok=False)
    report["execution_trace"]["grading_results"] = [
        {"stage": "hidden_csim", "ok": True},
        {"stage": "candidate_synth", "ok": True},
    ]

    assert "hidden_cosim_missing" in validate_evaluator(
        report, "t", official_task=False
    )
