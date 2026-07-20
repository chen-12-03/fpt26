"""Tests for candidate/validator, candidate/selector, candidate/checkpoint,
and pipeline/core modules."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent.candidate.validator import CandidateValidator, ValidationPlan
from agent.candidate.selector import select_candidate, select_anchor
from agent.candidate.checkpoint import (
    save_checkpoint,
    load_checkpoint,
    checkpoint_digest_matches,
)
from agent.pipeline.core import PipelineContext, PipelinePhase, StopReason, RunStatus
from agent.models import CandidateEvaluation

# ── Fixtures ──────────────────────────────────────────────────────────────────

_STARTER = '#include "top.h"\nint top(int *a) { return a[0]; }\n'
_FIXED = '#include "top.h"\nint top(int *a) { return a[0] + 1; }\n'
_BROKEN_SIG = '#include "top.h"\nlong top(int *a) { return a[0]; }\n'

_AVAILABLE = {
    "LUT": 1_303_680, "FF": 2_607_360, "DSP": 9_024,
    "BRAM_18K": 4_032, "URAM": 960,
}


def _synth_report(latency=100, clock_ns=5.0):
    return SimpleNamespace(
        latency_worst=latency, latency_avg=latency,
        interval_max=latency, clock_period_ns=clock_ns,
        resources={"LUT": 100, "FF": 100, "DSP": 1, "BRAM_18K": 0, "URAM": 0},
        available=dict(_AVAILABLE),
        pipeline_type="loop",
        loop_metrics=[],
    )


def _task():
    from llm4hls.task import Task
    return Task(
        dir=Path("/tmp"), id="test", type="optimize", difficulty=1,
        top="top", budget=40, part="xcu55c-fsvh2892-2L-e", clock_ns=5.0,
        requires_cosim=False, initial_condition="", description="",
        kernel_name="top.cpp", kernel_code=_STARTER,
        headers={"top.h": "int top(int *a);\n"},
        public_tb_name="top_tb.cpp",
        public_tb_code="int main() { return 0; }\n",
    )


def _fake_executor(*, csim_ok=True, synth_ok=True, cosim_ok=True):
    """Return a fake tool executor for testing."""

    class _FakeResult:
        def __init__(self, ok, report=None, cosim=None):
            self.ok = ok
            self.report = report
            self.cosim = cosim
            self.phase = "pass" if ok else "fail"
            self.log = ""

    class _FakeExecutor:
        def csim(self, build_dir, files, top, part, clock_ns, data_files=None):
            return _FakeResult(csim_ok)

        def synth(self, build_dir, files, synth_sources, top, part, clock_ns):
            return _FakeResult(synth_ok, report=_synth_report() if synth_ok else None)

        def cosim(self, build_dir, files, synth_sources, tb_sources, top, part, clock_ns):
            return _FakeResult(
                cosim_ok,
                report=_synth_report() if cosim_ok else None,
                cosim=SimpleNamespace(passed=cosim_ok, latency_max=80) if cosim_ok else None,
            )

    return _FakeExecutor()


# ── CandidateValidator tests ─────────────────────────────────────────────────

class TestCandidateValidator:
    def test_csim_only_plan_passes_valid_code(self):
        task = _task()
        ex = _fake_executor()
        v = CandidateValidator(task, _STARTER, tool_executor=ex)
        ev = v.validate(_FIXED, plan=ValidationPlan.CSIM_ONLY)
        assert ev.accepted
        assert ev.interface.ok

    def test_csim_only_rejects_broken_interface(self):
        task = _task()
        ex = _fake_executor()
        v = CandidateValidator(task, _STARTER, tool_executor=ex)
        ev = v.validate(_BROKEN_SIG, plan=ValidationPlan.CSIM_ONLY)
        assert not ev.accepted
        assert not ev.interface.ok

    def test_csim_synth_plan_passes(self):
        task = _task()
        ex = _fake_executor()
        v = CandidateValidator(task, _STARTER, tool_executor=ex)
        ev = v.validate(_FIXED, plan=ValidationPlan.CSIM_SYNTH)
        assert ev.accepted
        assert ev.csim == "pass"
        assert ev.synth == "pass"
        assert ev.frequency is not None and ev.frequency.ok
        assert ev.resource is not None and ev.resource.ok

    def test_csim_synth_fails_on_csim_failure(self):
        task = _task()
        ex = _fake_executor(csim_ok=False)
        v = CandidateValidator(task, _STARTER, tool_executor=ex)
        ev = v.validate(_FIXED, plan=ValidationPlan.CSIM_SYNTH)
        assert not ev.accepted
        assert ev.csim == "fail"
        # Synth must not be called when CSim fails
        assert ev.synth == "not_run"

    def test_csim_synth_fails_on_synth_failure(self):
        task = _task()
        ex = _fake_executor(synth_ok=False)
        v = CandidateValidator(task, _STARTER, tool_executor=ex)
        ev = v.validate(_FIXED, plan=ValidationPlan.CSIM_SYNTH)
        assert not ev.accepted
        assert ev.synth == "fail"

    def test_full_plan_runs_cosim_for_structural(self):
        task = _task()
        task.requires_cosim = True
        ex = _fake_executor(cosim_ok=True)
        v = CandidateValidator(task, _STARTER, tool_executor=ex)
        ev = v.validate(_FIXED, plan=ValidationPlan.FULL, build_dir=Path("/tmp"))
        assert ev.accepted

    def test_full_plan_skips_cosim_for_non_structural(self):
        task = _task()  # requires_cosim=False
        ex = _fake_executor()
        v = CandidateValidator(task, _STARTER, tool_executor=ex)
        ev = v.validate(_FIXED, plan=ValidationPlan.FULL)
        assert ev.accepted

    def test_frequency_failure_blocks_acceptance(self):
        task = _task()
        ex = _fake_executor()
        v = CandidateValidator(task, _STARTER, tool_executor=ex)

        # Override frequency gate by patching agent.validation
        import agent.validation as _av
        orig = _av.frequency_gate

        def _freq_fail(report, target):
            return SimpleNamespace(ok=False, reason="too_slow", target_clock_ns=5.0,
                                   candidate_clock_ns=None, frequency_mhz=None)
        _av.frequency_gate = _freq_fail
        try:
            ev = v.validate(_FIXED, plan=ValidationPlan.CSIM_SYNTH)
            assert not ev.accepted
            assert ev.frequency is not None and not ev.frequency.ok
        finally:
            _av.frequency_gate = orig


# ── Selector tests ───────────────────────────────────────────────────────────

class TestSelector:
    def test_selects_only_accepted(self):
        ev1 = CandidateEvaluation(source_sha256="a")
        ev1.accepted = True
        ev2 = CandidateEvaluation(source_sha256="b")
        ev2.accepted = False
        sha, ev = select_candidate([ev1, ev2])
        assert sha == "a"

    def test_returns_none_when_none_accepted(self):
        ev1 = CandidateEvaluation(source_sha256="a")
        sha, ev = select_candidate([ev1])
        assert sha is None

    def test_select_anchor_prefers_starter(self):
        from agent.models import InterfaceGateEvidence, FrequencyGateEvidence, ResourceGateEvidence

        se = CandidateEvaluation(source_sha256="s")
        se.accepted = True
        se.csim = "pass"
        se.synth = "pass"
        se.interface = InterfaceGateEvidence(ok=True, reason="passed")
        se.synth_latency = 100
        se.synth_ii = 1
        se.synth_clock_ns = 5.0
        se.frequency = FrequencyGateEvidence(ok=True, reason="passed", frequency_mhz=200.0)
        se.resource = ResourceGateEvidence(
            ok=True, reason="passed",
            resources={"LUT": 100},
            available=dict(_AVAILABLE),
        )

        anchor = select_anchor(se, None)
        assert anchor.source == "starter"
        assert anchor.valid


# ── Checkpoint tests ─────────────────────────────────────────────────────────

class TestCheckpoint:
    def test_save_and_load_roundtrip(self, tmp_path: Path):
        ev = CandidateEvaluation(source_sha256="abc")
        ev.accepted = True
        ev.stage = "baseline"
        ev.csim = "pass"
        ev.synth = "pass"
        ev.synth_latency = 100
        ev.synth_ii = 1
        ev.synth_clock_ns = 5.0
        ev.synth_resources = {"LUT": 100}

        kernel = "int top() { return 42; }"
        save_checkpoint(kernel, ev, checkpoint_dir=tmp_path, task_id="test")

        result = load_checkpoint(tmp_path, task_id="test")
        assert result is not None
        loaded_kernel, loaded_ev = result
        assert loaded_kernel == kernel
        assert loaded_ev.accepted
        assert loaded_ev.synth_latency == 100

    def test_rejects_unaccepted(self, tmp_path: Path):
        ev = CandidateEvaluation(source_sha256="abc")
        ev.accepted = False
        with pytest.raises(ValueError, match="unaccepted"):
            save_checkpoint("code", ev, checkpoint_dir=tmp_path, task_id="x")

    def test_load_returns_none_for_missing(self, tmp_path: Path):
        assert load_checkpoint(tmp_path) is None

    def test_digest_mismatch_returns_none(self, tmp_path: Path):
        ev = CandidateEvaluation(source_sha256="abc")
        ev.accepted = True
        save_checkpoint("original", ev, checkpoint_dir=tmp_path, task_id="x")

        # Tamper with the file
        cp = tmp_path / "verified_checkpoint.json"
        data = json.loads(cp.read_text())
        data["kernel"] = "tampered"
        cp.write_text(json.dumps(data))

        assert load_checkpoint(tmp_path) is None

    def test_digest_matches(self, tmp_path: Path):
        ev = CandidateEvaluation(source_sha256="abc")
        ev.accepted = True
        save_checkpoint("hello world", ev, checkpoint_dir=tmp_path, task_id="x")
        assert checkpoint_digest_matches("hello world", tmp_path)
        assert not checkpoint_digest_matches("different", tmp_path)


# ── PipelineContext tests ────────────────────────────────────────────────────

class TestPipelineContext:
    def test_initial_state_is_running(self):
        ctx = PipelineContext(task_id="t1")
        assert ctx.status == "running"
        assert not ctx.is_terminal

    def test_terminate_sets_terminal(self):
        ctx = PipelineContext()
        ctx.terminate("failed", "csim_failed")
        assert ctx.is_terminal
        assert ctx.status == "failed"
        assert ctx.stop_reason == "csim_failed"

    def test_fail_if_returns_true_on_condition(self):
        ctx = PipelineContext()
        result = ctx.fail_if(True, "failed", "test_failure")
        assert result is True
        assert ctx.is_terminal

    def test_fail_if_returns_false_no_condition(self):
        ctx = PipelineContext()
        result = ctx.fail_if(False, "failed", "no")
        assert result is False
        assert not ctx.is_terminal

    def test_terminate_is_idempotent(self):
        ctx = PipelineContext()
        ctx.terminate("failed", "first")
        ctx.terminate("budget_exceeded", "second")
        assert ctx.stop_reason == "first"  # first wins

    def test_elapsed_s_increases(self):
        import time
        ctx = PipelineContext(started_at=time.monotonic() - 2.0)
        assert ctx.elapsed_s >= 1.9

    def test_to_dict(self):
        ctx = PipelineContext(task_id="t1", run_role="submission", mode="auto")
        ctx.terminate("completed", "")
        d = ctx.to_dict()
        assert d["task_id"] == "t1"
        assert d["status"] == "completed"
