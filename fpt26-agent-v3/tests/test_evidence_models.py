"""Tests for SubmissionEvidence, AnchorEvidence, and related models."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.models import (
    AnchorEvidence,
    ArtifactManifest,
    CandidateEvaluation,
    FrequencyGateEvidence,
    InterfaceGateEvidence,
    ResourceGateEvidence,
    RunStatus,
    SubmissionEvidence,
)
from agent.errors import (
    DigestMismatchError,
    EvidenceError,
    MissingEvidenceError,
)


class TestSubmissionEvidence:
    def test_roundtrip_serialisation(self):
        ev = SubmissionEvidence(
            schema_version=1,
            run_id="test_run",
            task_id="test_task",
            status=RunStatus.COMPLETED.value,
            kernel_sha256="abc123",
            credits_spent=10,
            credits_total=40,
            model="qwen3-coder-plus",
            interface_ok=True,
            csim_ok=True,
            synth_ok=True,
            frequency_ok=True,
            resource_ok=True,
            scoring_profile="balanced",
        )
        data = ev.to_dict()
        restored = SubmissionEvidence.from_dict(data)
        assert restored.run_id == "test_run"
        assert restored.task_id == "test_task"
        assert restored.status == "completed"
        assert restored.credits_spent == 10
        assert restored.credits_total == 40
        assert restored.scoring_profile == "balanced"

    def test_from_dict_tolerates_missing_fields(self):
        ev = SubmissionEvidence.from_dict({})
        assert ev.run_id == ""
        assert ev.credits_spent == 0
        assert ev.scoring_profile == "balanced"

    def test_validate_against_kernel_matches(self, tmp_path: Path):
        kernel = tmp_path / "kernel.cpp"
        kernel.write_text("int top() { return 0; }")
        sha = hashlib.sha256(kernel.read_bytes()).hexdigest()
        ev = SubmissionEvidence(kernel_sha256=sha, status="completed")
        ev.validate_against_kernel(str(kernel))  # should not raise

    def test_validate_against_kernel_mismatch_raises(self, tmp_path: Path):
        kernel = tmp_path / "kernel.cpp"
        kernel.write_text("int top() { return 0; }")
        ev = SubmissionEvidence(kernel_sha256="deadbeef", status="completed")
        with pytest.raises(DigestMismatchError):
            ev.validate_against_kernel(str(kernel))

    def test_require_completed_rejects_failed(self):
        ev = SubmissionEvidence(status="failed", stop_reason="csim_failed")
        with pytest.raises(EvidenceError):
            ev.require_completed()

    def test_require_completed_rejects_missing_digest(self):
        ev = SubmissionEvidence(status="completed", kernel_sha256="")
        with pytest.raises(MissingEvidenceError):
            ev.require_completed()

    def test_require_completed_accepts_valid(self):
        ev = SubmissionEvidence(status="completed", kernel_sha256="abc")
        ev.require_completed()  # should not raise

    def test_from_run_state(self):
        from agent.agents.base import AgentConfig, RunState
        from llm4hls.budget import Budget
        from llm4hls.task import Task
        from llm4hls.tools import ToolResult

        task = Task(
            dir=Path("/tmp"),
            id="test_task",
            type="optimize",
            difficulty=1,
            top="top",
            budget=40,
            part="xcu55c-fsvh2892-2L-e",
            clock_ns=5.0,
            requires_cosim=False,
            initial_condition="",
            description="",
            kernel_name="top.cpp",
            kernel_code="int top() { return 0; }",
            headers={},
            public_tb_name="tb.cpp",
            public_tb_code="int main() { return 0; }",
        )

        class _Server:
            budget = Budget(total=40)
            transcript = []

        state = RunState(
            task=task,
            server=_Server(),
            llm=None,
            config=AgentConfig(output_root="/tmp"),
            kernel=task.kernel_code,
            safe_fallback_kernel=task.kernel_code,
        )
        state.status = "completed"
        state.csim_ok = True
        state.synth_ok = True
        state.results = [
            ToolResult("csim", True, "pass", 0, "", 1.5),
        ]

        ev = SubmissionEvidence.from_run_state(state, run_id="r1")
        assert ev.task_id == "test_task"
        assert ev.status == "completed"
        assert ev.credits_spent == 0  # budget was never charged
        assert ev.csim_ok is True
        assert ev.kernel_sha256


class TestAnchorEvidence:
    def test_valid_anchor_passes_all_gates(self):
        ev = AnchorEvidence(
            source="starter",
            valid=True,
            csim_ok=True,
            synth_ok=True,
            interface_ok=True,
            frequency=FrequencyGateEvidence(ok=True, frequency_mhz=200.0),
            resource=ResourceGateEvidence(
                ok=True,
                resources={"LUT": 100},
                available={"LUT": 1000, "FF": 1000, "DSP": 100, "BRAM_18K": 100, "URAM": 10},
            ),
            latency=100,
            ii=1,
        )
        assert ev.passes_all_required_gates

    def test_missing_csim_fails_gates(self):
        ev = AnchorEvidence(
            source="starter", valid=True, csim_ok=False,
            synth_ok=True, interface_ok=True,
            frequency=FrequencyGateEvidence(ok=True),
            resource=ResourceGateEvidence(
                ok=True, resources={},
                available={"LUT": 1000, "FF": 1000, "DSP": 100, "BRAM_18K": 100, "URAM": 10},
            ),
        )
        assert not ev.passes_all_required_gates

    def test_missing_latency_fails_gates(self):
        ev = AnchorEvidence(
            source="starter", valid=True,
            csim_ok=True, synth_ok=True, interface_ok=True,
            frequency=FrequencyGateEvidence(ok=True),
            resource=ResourceGateEvidence(
                ok=True, resources={},
                available={"LUT": 1000, "FF": 1000, "DSP": 100, "BRAM_18K": 100, "URAM": 10},
            ),
            latency=None,
        )
        assert not ev.passes_all_required_gates

    def test_frequency_fail_fails_gates(self):
        ev = AnchorEvidence(
            source="starter", valid=True,
            csim_ok=True, synth_ok=True, interface_ok=True,
            frequency=FrequencyGateEvidence(ok=False, reason="too slow"),
            resource=ResourceGateEvidence(
                ok=True, resources={},
                available={"LUT": 1000, "FF": 1000, "DSP": 100, "BRAM_18K": 100, "URAM": 10},
            ),
            latency=100, ii=1,
        )
        assert not ev.passes_all_required_gates

    def test_roundtrip_serialisation(self):
        ev = AnchorEvidence(
            source="starter", valid=True,
            source_sha256="abc",
            csim_ok=True, synth_ok=True, interface_ok=True,
            frequency=FrequencyGateEvidence(ok=True, frequency_mhz=200.0),
            resource=ResourceGateEvidence(
                ok=True,
                resources={"LUT": 100, "FF": 200},
                available={"LUT": 1000, "FF": 1000, "DSP": 100, "BRAM_18K": 100, "URAM": 10},
            ),
            latency=200, ii=2, clock_ns=5.0,
            resources={"LUT": 100, "FF": 200},
            available={"LUT": 1000, "FF": 2000, "DSP": 100, "BRAM_18K": 100, "URAM": 10},
        )
        data = ev.to_dict()
        restored = AnchorEvidence.from_dict(data)
        assert restored.source == "starter"
        assert restored.valid
        assert restored.latency == 200
        assert restored.passes_all_required_gates


class TestArtifactManifest:
    def test_from_path(self, tmp_path: Path):
        f = tmp_path / "artifact.txt"
        f.write_text("hello")
        manifest = ArtifactManifest.from_path(str(f), role="kernel")
        assert manifest.role == "kernel"
        assert len(manifest.sha256) == 64
        assert manifest.path == str(f)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            ArtifactManifest.from_path("/nonexistent/path", role="kernel")


class TestCandidateEvaluation:
    def test_default_is_not_accepted(self):
        ev = CandidateEvaluation(source_sha256="abc")
        assert not ev.accepted
        assert ev.csim.value == "not_run"

    def test_to_dict(self):
        ev = CandidateEvaluation(
            source_sha256="abc",
            interface=InterfaceGateEvidence(ok=True),
            csim="pass",
            synth="pass",
            accepted=True,
            stage="baseline",
        )
        d = ev.to_dict()
        assert d["accepted"] is True
        assert d["csim"] == "pass"
