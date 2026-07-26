"""Integration tests for the fail-closed pipeline flow.

These tests verify that:
- CSIM failure prevents CoSim from running (via step_score)
- Invalid submission evidence is rejected by the evaluator
- A failing gate prevents scoring
- Budget exhaustion recovers the last verified candidate
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from agent.agents.base import AgentConfig, RunState
from agent.models import (
    AnchorEvidence,
    RunStatus,
    SubmissionEvidence,
)
from agent.errors import (
    DigestMismatchError,
    EvidenceError,
)
from llm4hls.budget import Budget, BudgetExceeded
from llm4hls.task import Task
from llm4hls.tools import ToolResult


_STARTER = '#include "top.h"\nint top(int *a) { return a[0]; }\n'
_AVAILABLE = {
    "LUT": 1_303_680, "FF": 2_607_360, "DSP": 9_024,
    "BRAM_18K": 4_032, "URAM": 960,
}


def _report(latency=100, clock_ns=5.0, resources=None):
    if resources is None:
        resources = {"LUT": 100, "FF": 100, "DSP": 1, "BRAM_18K": 0, "URAM": 0}
    return SimpleNamespace(
        latency_worst=latency, latency_avg=latency,
        interval_max=latency, clock_period_ns=clock_ns,
        resources=resources, available=dict(_AVAILABLE),
        pipeline_type="loop", loop_metrics=[],
    )


def _result(kind, ok, phase=None, report=None, cosim=None, log=""):
    r = ToolResult(
        kind=kind, ok=ok,
        phase=phase or ("pass" if ok else f"{kind}_fail"),
        return_code=0 if ok else 1, log=log, elapsed_s=0.01,
        report=report, cosim=cosim,
    )
    r.brief = lambda: f"[{kind}] {r.phase}"
    return r


class _Server:
    def __init__(self, budget, csim_fn, synth_fn, cosim_fn=None):
        self.budget = Budget(total=budget)
        self._csim = csim_fn
        self._synth = synth_fn
        self._cosim = cosim_fn
        self.calls = []
        self.transcript = []
        self.run_root = Path("/tmp/fail-closed")

    def csim(self, code):
        self.budget.charge("csim")
        self.calls.append(("csim", code))
        return self._csim(code)

    def synth(self, code):
        self.budget.charge("synth")
        self.calls.append(("synth", code))
        return self._synth(code)

    def cosim(self, code):
        self.budget.charge("cosim")
        self.calls.append(("cosim", code))
        assert self._cosim is not None
        return self._cosim(code)


def _task(tmp_path, requires_cosim=False, budget=120):
    return Task(
        dir=tmp_path, id="fail_closed_test", type="optimize",
        difficulty=1, top="top", budget=budget,
        part="xcu55c-fsvh2892-2L-e", clock_ns=5.0,
        requires_cosim=requires_cosim,
        initial_condition="", description="",
        kernel_name="top.cpp", kernel_code=_STARTER,
        headers={"top.h": "int top(int *a);\n"},
        public_tb_name="top_tb.cpp",
        public_tb_code="int main() { return 0; }\n",
    )


class TestFailClosedCsSimPreventsCoSim:
    """CSim failure must prevent CoSim from being called."""

    def test_csim_fail_in_step_score_skips_cosim(self, tmp_path: Path):
        """When hidden_csim fails, step_score returns early before reaching cosim."""
        task = _task(tmp_path, requires_cosim=True, budget=60)
        cosim_called = []

        def fake_csim_run(self, build_dir, files, top, part, clock_ns,
                          data_files=None):
            return _result("csim", False, phase="runtime_fail",
                           log="mismatch at line 42")

        def fake_synth_run(self, build_dir, files, synth_sources, top,
                           part, clock_ns):
            cosim_called.append("synth")
            return _result("synth", True, report=_report())

        def fake_cosim_run(self, build_dir, files, synth_sources,
                           tb_sources, top, part, clock_ns):
            cosim_called.append("cosim")
            return _result("cosim", True)

        server = _Server(task.budget,
                         lambda c: _result("csim", True),
                         lambda c: _result("synth", True, report=_report()),
                         lambda c: _result("cosim", True))
        config = AgentConfig(mode="baseline", output_root=str(tmp_path),
                             verbose=False, score=True)
        state = RunState(
            task=task, server=server, llm=None, config=config,
            kernel=_STARTER, safe_fallback_kernel=_STARTER,
        )
        state.csim_ok = True
        state.synth_ok = True
        state.interface_ok = True
        state.frequency_ok = True
        state.resource_ok = True

        from unittest.mock import patch as upatch
        from agent.workflow import step_score

        with upatch("llm4hls.tools.CSimTool.run", fake_csim_run):
            state = step_score(state)

        # CoSim should never have been called because hidden_csim failed
        assert "cosim" not in cosim_called
        assert state.status == "failed"


class TestFailClosedEvaluatorRejectsBadEvidence:
    """Evaluator must reject missing, damaged, or mismatched evidence."""

    def test_digest_mismatch_raises(self, tmp_path: Path):
        kernel = tmp_path / "final.cpp"
        kernel.write_text("int top() { return 1; }")
        sha = hashlib.sha256(kernel.read_bytes()).hexdigest()
        # Use a different, wrong digest
        ev = SubmissionEvidence(
            status="completed",
            kernel_sha256="a" * 64,
        )
        with pytest.raises(DigestMismatchError):
            ev.validate_against_kernel(str(kernel))

    def test_failed_submission_rejected(self):
        ev = SubmissionEvidence(
            status="failed", stop_reason="csim_failed",
        )
        with pytest.raises(EvidenceError):
            ev.require_completed()

    def test_completed_submission_with_valid_digest_accepted(self, tmp_path: Path):
        kernel = tmp_path / "final.cpp"
        kernel.write_text("int top() { return 1; }")
        sha = hashlib.sha256(kernel.read_bytes()).hexdigest()
        ev = SubmissionEvidence(status="completed", kernel_sha256=sha)
        ev.validate_against_kernel(str(kernel))
        ev.require_completed()  # should not raise


class TestValidityOnlyAnchorFallback:
    def test_candidate_gate_passes_allow_validity_only_without_qor_anchor(
        self, tmp_path: Path
    ):
        from agent.pipeline.evaluator import _candidate_validity_only_ok

        task = _task(tmp_path)
        state = RunState(
            task=task,
            server=MagicMock(),
            llm=None,
            config=AgentConfig(mode="baseline", output_root=str(tmp_path)),
            kernel=_STARTER,
            safe_fallback_kernel=_STARTER,
        )
        state.csim_ok = True
        state.synth_ok = True
        state.interface_ok = True
        state.frequency_ok = True
        state.resource_ok = True
        state.cosim_ok = True
        state.stop_reason = "anchor_invalid: candidate_self"
        state.scorecard = SimpleNamespace(gate_reason="no_valid_anchor")

        assert _candidate_validity_only_ok(
            state, AnchorEvidence(source="candidate_self", valid=True)
        )

    def test_candidate_gate_failure_still_blocks_validity_only(
        self, tmp_path: Path
    ):
        from agent.pipeline.evaluator import _candidate_validity_only_ok

        task = _task(tmp_path)
        state = RunState(
            task=task,
            server=MagicMock(),
            llm=None,
            config=AgentConfig(mode="baseline", output_root=str(tmp_path)),
            kernel=_STARTER,
            safe_fallback_kernel=_STARTER,
        )
        state.csim_ok = True
        state.synth_ok = True
        state.interface_ok = True
        state.frequency_ok = False
        state.resource_ok = True
        state.cosim_ok = True
        state.stop_reason = "anchor_invalid: candidate_self"
        state.scorecard = SimpleNamespace(gate_reason="no_valid_anchor")

        assert not _candidate_validity_only_ok(
            state, AnchorEvidence(source="candidate_self", valid=True)
        )


class TestFailClosedBudgetExhaustion:
    """Budget exhaustion must recover the last verified candidate."""

    def test_budget_exhaustion_keeps_safe_fallback(self, tmp_path: Path):
        task = _task(tmp_path, budget=3)

        def cs(code):
            raise BudgetExceeded("no credits")

        def sy(code):
            return _result("synth", True, report=_report())

        server = _Server(task.budget, cs, sy)
        config = AgentConfig(mode="auto", output_root=str(tmp_path),
                             verbose=False)
        state = RunState(
            task=task, server=server, llm=None, config=config,
            kernel=_STARTER, safe_fallback_kernel=_STARTER,
        )

        from agent.workflow import Pipeline, Step, step_csim, step_finalize

        pipeline = Pipeline(
            steps=[Step("csim", step_csim, desc="csim")],
            name="test",
        )
        state = pipeline.run(state)
        if not state.metadata.get("finalized"):
            state = step_finalize(state)

        assert state.status == "budget_exceeded"
        assert state.kernel == _STARTER
