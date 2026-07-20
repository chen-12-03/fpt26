"""Tests that runner.py tool calls enforce security validation.

These tests verify that identifier injection, dangerous paths, and
Tcl metacharacters are rejected BEFORE a subprocess is launched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.errors import SecurityError
from agent.integrations.vitis import SecureToolExecutor

_VALID_FILES = {"top.cpp": "int top() { return 0; }", "top.h": "int top();"}


def _executor(ws: Path) -> SecureToolExecutor:
    return SecureToolExecutor(workspace_root=ws)


class TestToolParameterValidation:
    """Security validation via SecureToolExecutor._validate."""

    def test_valid_params_pass(self, tmp_path: Path):
        ex = _executor(tmp_path)
        ex._validate(tmp_path / "build", _VALID_FILES, "top",
                     "xcu55c-fsvh2892-2L-e", 5.0, kind="csim")

    @pytest.mark.parametrize("bad_top", [
        "top; rm -rf /",
        "top$(whoami)",
        "a`ls`",
    ])
    def test_rejects_dangerous_top_identifier(self, tmp_path: Path, bad_top: str):
        ex = _executor(tmp_path)
        with pytest.raises(SecurityError):
            ex._validate(tmp_path / "build", _VALID_FILES, bad_top,
                         "xcu55c-fsvh2892-2L-e", 5.0, kind="csim")

    @pytest.mark.parametrize("bad_name", [
        "a;.cpp",
        "a$(whoami).cpp",
        "a`ls`.cpp",
    ])
    def test_rejects_dangerous_filename(self, tmp_path: Path, bad_name: str):
        ex = _executor(tmp_path)
        with pytest.raises(SecurityError):
            ex._validate(tmp_path / "build", {bad_name: "int top() { return 0; }"},
                         "top", "xcu55c-fsvh2892-2L-e", 5.0, kind="csim")

    def test_rejects_non_positive_clock(self, tmp_path: Path):
        ex = _executor(tmp_path)
        with pytest.raises(SecurityError):
            ex._validate(tmp_path / "build", _VALID_FILES, "top",
                         "xcu55c-fsvh2892-2L-e", -1.0, kind="csim")

    def test_rejects_nan_clock(self, tmp_path: Path):
        ex = _executor(tmp_path)
        with pytest.raises(SecurityError):
            ex._validate(tmp_path / "build", _VALID_FILES, "top",
                         "xcu55c-fsvh2892-2L-e", float("nan"), kind="csim")

    def test_build_dir_outside_workspace_rejected(self, tmp_path: Path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        outside = tmp_path / "outside_build"
        ex = _executor(ws)
        with pytest.raises(SecurityError):
            ex._validate(outside, _VALID_FILES, "top",
                         "xcu55c-fsvh2892-2L-e", 5.0, kind="csim")


class TestToolServerEnvSanitisation:
    """Verify that the clean env is constructed and used by SecureToolExecutor."""

    def test_clean_env_strips_secrets(self):
        """Executor subprocess env should not contain LLM secrets."""
        import os
        from agent.integrations.vitis import _get_clean_env as _gce

        os.environ["FPT26_LLM_API_KEY"] = "test-sk-secret"
        os.environ["OPENROUTER_API_KEY"] = "test-router-secret"
        try:
            import agent.integrations.vitis as _iv
            _iv._clean_env_cache = None
            clean = _gce()
            assert "FPT26_LLM_API_KEY" not in clean
            assert "OPENROUTER_API_KEY" not in clean
            assert "PATH" in clean
        finally:
            del os.environ["FPT26_LLM_API_KEY"]
            del os.environ["OPENROUTER_API_KEY"]
            _iv._clean_env_cache = None


class TestReportingBackwardCompat:
    """Verify that existing imports from agent.reporting still work."""

    def test_write_run_report_importable(self):
        from agent.reporting import write_run_report
        assert callable(write_run_report)

    def test_print_evaluation_importable(self):
        from agent.reporting import print_evaluation
        assert callable(print_evaluation)

    def test_write_failure_report_importable(self):
        from agent.reporting import write_failure_report
        assert callable(write_failure_report)

    def test_new_modules_importable(self):
        from agent.reporting import (
            collect_reports,
            REPORT_SCHEMA_VERSION,
            write_json_report,
            print_scorecard,
        )
        assert callable(collect_reports)
        assert isinstance(REPORT_SCHEMA_VERSION, int)
        assert callable(write_json_report)
        assert callable(print_scorecard)

    def test_semi_private_exports_still_work(self):
        from agent.reporting import (
            _attempts_to_pass,
            _compute_derived,
            _final_synth_info,
            _reported_cosim_status,
        )
        assert callable(_attempts_to_pass)
        assert callable(_compute_derived)
        assert callable(_final_synth_info)
        assert callable(_reported_cosim_status)


class TestEvalV3Aggregation:
    """Verify eval.py uses V3 fields."""

    def test_aggregate_uses_score_not_difficulty(self, tmp_path: Path):
        """aggregate() should use score/score_max, not task_difficulty."""
        from agent.eval import aggregate

        reports = [
            {
                "task_id": "test_task",
                "task_type": "optimize",
                "status": "completed",
                "task_difficulty": 5,
                "scoring": {
                    "schema_version": 10,
                    "score": 85.0,
                    "score_max": 100.0,
                    "valid": True,
                },
                "budget": {"spent": 10, "total": 40},
                "evaluation": {"wall_time_seconds": 30.0},
            }
        ]
        result = aggregate(reports)
        # score_max should be 100, not task_difficulty * X
        assert result["total_max"] == 100.0

    def test_v3_aggregate_via_cli_flag(self, tmp_path: Path):
        """--aggregate-v3 flag should work."""
        from agent.eval import parse_args

        args = parse_args(["--output-root", str(tmp_path), "--aggregate-v3"])
        assert args.aggregate_v3 is True

    def test_compat_flag_present(self):
        from agent.eval import parse_args

        args = parse_args(["--output-root", "/tmp", "--compat"])
        assert args.compat is True
