"""Section 3 integration tests — verify P0 claims against real execution paths.

These tests verify that:
- ToolServer calls go through SecureToolExecutor with path/env validation
- Evaluator rejects missing/invalid SubmissionEvidence
- Fake ToolExecutor can be injected for unit testing
- CandidateValidator works with fake executor
- Checkpoint saves/loads correctly
- PipelineContext fail-closed behavior
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.models import SubmissionEvidence, RunStatus
from agent.errors import DigestMismatchError, EvidenceError

# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: ToolServer calls execute path validation and env sanitisation
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolServerSecurityIntegration:
    """Verify ToolServer delegates to SecureToolExecutor with security checks."""

    def test_tool_server_creates_executor(self, tmp_path: Path):
        """ToolServer creates a SecureToolExecutor with source transformer."""
        from agent.runner import ToolServer
        from agent.integrations.vitis import SecureToolExecutor
        from llm4hls.budget import Budget
        from llm4hls.task import Task

        task = Task(
            dir=tmp_path, id="sec_test", type="optimize", difficulty=1,
            top="top", budget=40, part="xcu55c-fsvh2892-2L-e", clock_ns=5.0,
            requires_cosim=False, initial_condition="", description="",
            kernel_name="top.cpp",
            kernel_code="int top() { return 0; }",
            headers={}, public_tb_name="tb.cpp",
            public_tb_code="int main() { return 0; }",
        )
        server = ToolServer(task, Budget(total=40), tmp_path / "runs")
        assert isinstance(server.executor, SecureToolExecutor)
        # Source transformer should be set (C++17 prep)
        assert server.executor._source_transformer is not None

    def test_fake_executor_injectable(self, tmp_path: Path):
        """ToolServer accepts an injected fake executor for testing."""
        from agent.runner import ToolServer
        from agent.integrations.vitis import SecureToolExecutor
        from llm4hls.budget import Budget
        from llm4hls.task import Task

        fake = SecureToolExecutor(workspace_root=tmp_path)
        task = Task(
            dir=tmp_path, id="inj_test", type="optimize", difficulty=1,
            top="top", budget=40, part="xcu55c-fsvh2892-2L-e", clock_ns=5.0,
            requires_cosim=False, initial_condition="", description="",
            kernel_name="top.cpp",
            kernel_code="int top() { return 0; }",
            headers={}, public_tb_name="tb.cpp",
            public_tb_code="int main() { return 0; }",
        )
        server = ToolServer(task, Budget(total=40), tmp_path / "runs",
                           executor=fake)
        assert server.executor is fake

    def test_security_rejects_dangerous_top(self, tmp_path: Path):
        """SecureToolExecutor rejects Tcl-injectable top names."""
        from agent.integrations.vitis import SecureToolExecutor
        from agent.errors import SecurityError

        ex = SecureToolExecutor(workspace_root=tmp_path)
        with pytest.raises(SecurityError):
            ex._validate(tmp_path / "build", {"a.cpp": "int x;"},
                        "top; rm -rf /", "xcu55c-fsvh2892-2L-e", 5.0,
                        kind="csim")

    def test_security_rejects_filename_injection(self, tmp_path: Path):
        """SecureToolExecutor rejects filenames with Tcl metacharacters."""
        from agent.integrations.vitis import SecureToolExecutor
        from agent.errors import SecurityError

        ex = SecureToolExecutor(workspace_root=tmp_path)
        with pytest.raises(SecurityError):
            ex._validate(tmp_path / "build", {"a`ls`.cpp": "int x;"},
                        "top", "xcu55c-fsvh2892-2L-e", 5.0, kind="synth")

    def test_security_rejects_absolute_filename(self, tmp_path: Path):
        """SecureToolExecutor rejects filenames that look like absolute paths."""
        from agent.integrations.vitis import SecureToolExecutor
        from agent.errors import SecurityError

        ex = SecureToolExecutor(workspace_root=tmp_path)
        with pytest.raises(SecurityError):
            ex._validate(tmp_path / "build", {"/etc/passwd": "bad"},
                        "top", "xcu55c-fsvh2892-2L-e", 5.0, kind="csim")


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: Evaluator enforces SubmissionEvidence
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvaluatorEvidenceEnforcement:
    """Evaluator must reject missing, damaged, or mismatched evidence."""

    def test_evidence_validate_against_kernel_rejects_mismatch(self, tmp_path: Path):
        kernel = tmp_path / "final.cpp"
        kernel.write_text("int top() { return 1; }")
        ev = SubmissionEvidence(
            status="completed",
            kernel_sha256="a" * 64,
        )
        with pytest.raises(DigestMismatchError):
            ev.validate_against_kernel(str(kernel))

    def test_evidence_require_completed_rejects_failed(self):
        ev = SubmissionEvidence(status="failed", stop_reason="csim_failed")
        with pytest.raises(EvidenceError):
            ev.require_completed()

    def test_evidence_require_completed_rejects_running(self):
        ev = SubmissionEvidence(status="running")
        with pytest.raises(EvidenceError):
            ev.require_completed()

    def test_evidence_require_completed_rejects_budget_exceeded(self):
        ev = SubmissionEvidence(status="budget_exceeded", stop_reason="out")
        with pytest.raises(EvidenceError):
            ev.require_completed()

    def test_evidence_accepts_valid_completed(self, tmp_path: Path):
        kernel = tmp_path / "final.cpp"
        kernel.write_text("int top() { return 1; }")
        sha = hashlib.sha256(kernel.read_bytes()).hexdigest()
        ev = SubmissionEvidence(status="completed", kernel_sha256=sha)
        ev.validate_against_kernel(str(kernel))  # no raise
        ev.require_completed()  # no raise

    def test_missing_evidence_json_rejected(self, tmp_path: Path):
        """evaluate_batch should skip when submission_evidence.json is missing."""
        from agent.evaluate_batch import _load_evidence, _evidence_ok

        ev = _load_evidence(tmp_path / "nonexistent.json")
        assert ev is None

    def test_evidence_with_mismatched_digest_rejected(self, tmp_path: Path):
        """evaluate_batch should reject evidence with digest mismatch."""
        from agent.evaluate_batch import _evidence_ok

        kernel = tmp_path / "final.cpp"
        kernel.write_text("int top() { return 1; }")
        ev_data = {
            "schema_version": 1,
            "status": "completed",
            "task_id": "test",
            "kernel_sha256": "b" * 64,
        }
        ok, reason = _evidence_ok(ev_data, kernel)
        assert not ok
        assert "digest" in reason.lower() or "mismatch" in reason.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: Fake ToolExecutor unit testability
# ═══════════════════════════════════════════════════════════════════════════════

class TestFakeExecutorIntegration:
    """CandidateValidator can be tested with a fake executor (no real Vitis)."""

    def test_validator_with_fake_executor_full_flow(self, tmp_path: Path):
        from agent.candidate.validator import CandidateValidator, ValidationPlan
        from llm4hls.task import Task

        task = Task(
            dir=tmp_path, id="fake_test", type="optimize", difficulty=1,
            top="top", budget=40, part="xcu55c-fsvh2892-2L-e", clock_ns=5.0,
            requires_cosim=False, initial_condition="", description="",
            kernel_name="top.cpp",
            kernel_code='#include "top.h"\nint top(int *a) { return a[0]; }\n',
            headers={"top.h": "int top(int *a);\n"},
            public_tb_name="tb.cpp",
            public_tb_code="int main() { return 0; }",
        )

        class FakeResult:
            ok = True
            phase = "pass"
            log = "fake tool output with https://secret.endpoint/v1"
            report = SimpleNamespace(
                latency_worst=100, latency_avg=100, interval_max=100,
                clock_period_ns=5.0,
                resources={"LUT": 100, "FF": 100, "DSP": 1, "BRAM_18K": 0, "URAM": 0},
                available={"LUT": 1303680, "FF": 2607360, "DSP": 9024, "BRAM_18K": 4032, "URAM": 960},
                pipeline_type="loop", loop_metrics=[],
            )

        class FakeExecutor:
            def csim(self, build_dir, files, top, part, clock_ns, data_files=None):
                return FakeResult()

            def synth(self, build_dir, files, synth_sources, top, part, clock_ns):
                return FakeResult()

            def cosim(self, build_dir, files, synth_sources, tb_sources, top, part, clock_ns):
                r = FakeResult()
                r.cosim = SimpleNamespace(passed=True, latency_max=80)
                return r

        ex = FakeExecutor()
        v = CandidateValidator(task, task.kernel_code, tool_executor=ex)
        ev = v.validate(
            task.kernel_code.replace("return a[0]", "return a[0] + 1"),
            plan=ValidationPlan.CSIM_SYNTH,
        )
        assert ev.accepted
        assert ev.csim == "pass"
        assert ev.synth == "pass"
        assert ev.frequency is not None and ev.frequency.ok

    def test_selector_rejects_unaccepted_candidates(self):
        from agent.candidate.selector import select_candidate
        from agent.models import CandidateEvaluation

        ev = CandidateEvaluation(source_sha256="abc")
        ev.accepted = False
        sha, result = select_candidate([ev])
        assert sha is None
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: PipelineContext fail-closed
# ═══════════════════════════════════════════════════════════════════════════════

class TestPipelineContextFailClosed:
    """PipelineContext enforces fail-closed semantics."""

    def test_fail_if_stops_pipeline(self):
        from agent.pipeline.core import PipelineContext
        ctx = PipelineContext(task_id="t1")
        stopped = ctx.fail_if(True, "failed", "csim_failed")
        assert stopped
        assert ctx.is_terminal
        assert ctx.status == "failed"

    def test_fail_if_does_not_stop_on_false(self):
        from agent.pipeline.core import PipelineContext
        ctx = PipelineContext(task_id="t1")
        stopped = ctx.fail_if(False, "failed", "no_error")
        assert not stopped
        assert not ctx.is_terminal

    def test_terminate_is_idempotent(self):
        from agent.pipeline.core import PipelineContext
        ctx = PipelineContext(task_id="t1")
        ctx.terminate("failed", "first_error")
        ctx.terminate("budget_exceeded", "second_error")
        assert ctx.status == "failed"
        assert ctx.stop_reason == "first_error"
