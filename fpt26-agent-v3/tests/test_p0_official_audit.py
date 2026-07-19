from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scoring.audit_p0_official import OFFICIAL_TASKS, audit
from scoring.run_p0_real_api_shard import execution_source_snapshot


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report), encoding="utf-8")


def _submission(
    task_id: str, final_path: Path, *, requires_cosim: bool
) -> dict:
    digest = _sha256(final_path)
    cosim = (
        {
            "stage": "accepted",
            "ok": True,
            "phase": "pass",
            "source_sha256": digest,
            "latency_max": 97,
        }
        if requires_cosim
        else None
    )
    return {
        "task_id": task_id,
        "run_role": "submission",
        "mode": "auto",
        "status": "completed",
        "stop_reason": "",
        "cosim_ok": True if requires_cosim else None,
        "task_preflight": {
            "forbidden_artifact_accesses": 0,
            "public_files_read": ["task.toml", "kernel.cpp", "kernel_tb.cpp"],
        },
        "execution_trace": {"grading_results": []},
        "grading": {"source": None},
        "model_compliance": {"compliance_proven": True},
        "llm": {
            "client": "OpenAICompatClient",
            "token_usage": {
                "complete": True,
                "request_count": 1,
                "response_count": 1,
                "failed_request_count": 0,
                "unreported_response_count": 0,
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        },
        "toolchain": {"version_gate_ok": True, "part_gate_ok": True},
        "gates": {
            "interface": {"ok": True},
            "frequency_100mhz": {
                "ok": True,
                "candidate_clock_ns": 5.0,
                "frequency_mhz": 200.0,
            },
            "resource_capacity": {"ok": True},
            "required_cosim": cosim,
            "public_acceptance": {"ok": True},
        },
        "final_hardware": {"cosim": cosim},
        "final_artifact": {
            "path": str(final_path),
            "sha256": digest,
            "fully_verified": True,
        },
        "budget": {"spent": 1, "total": 20},
        "tool_call_count": 3,
    }


def _evaluator(
    task_id: str, final_path: Path, *, requires_cosim: bool
) -> dict:
    digest = _sha256(final_path)
    cosim = (
        {
            "stage": "evaluator_hidden_cosim",
            "ok": True,
            "phase": "pass",
            "source_sha256": digest,
            "latency_max": 97,
        }
        if requires_cosim
        else None
    )
    trace = [
        {"stage": "hidden_csim", "ok": True},
        {"stage": "candidate_synth", "ok": True},
    ]
    if requires_cosim:
        trace.append({"stage": "hidden_cosim", "ok": True})
    return {
        "task_id": task_id,
        "run_role": "evaluator",
        "status": "completed",
        "stop_reason": "",
        "llm": None,
        "grading": {"source": "public_fallback", "is_fallback": True},
        "execution_trace": {"grading_results": trace},
        "cosim_ok": True if requires_cosim else None,
        "toolchain": {"version_gate_ok": True, "part_gate_ok": True},
        "gates": {
            "interface": {"ok": True},
            "frequency_100mhz": {"ok": True},
            "resource_capacity": {"ok": True},
            "required_cosim": cosim,
            "evaluator_acceptance": {"ok": True},
        },
        "final_hardware": {"cosim": cosim},
        "final_artifact": {
            "path": str(final_path),
            "sha256": digest,
            "fully_verified": True,
        },
        "scoring": {"score": 75.0},
    }


def _run_root(tmp_path: Path) -> Path:
    root = tmp_path / "official"
    source = execution_source_snapshot()
    _write_report(root / "execution-source-start.json", source)
    _write_report(root / "execution-source-end.json", source)
    for task_id in OFFICIAL_TASKS:
        submission_final = (
            root / task_id / "submission" / task_id / "final_kernel.cpp"
        )
        evaluator_final = (
            root / task_id / "evaluator" / task_id / "final_kernel.cpp"
        )
        submission_final.parent.mkdir(parents=True)
        evaluator_final.parent.mkdir(parents=True)
        submission_final.write_text(f"void {task_id}() {{}}\n")
        evaluator_final.write_bytes(submission_final.read_bytes())
        requires_cosim = task_id == "residual_stream_deadlock"
        _write_report(
            submission_final.parent / "run_report.json",
            _submission(
                task_id, submission_final, requires_cosim=requires_cosim
            ),
        )
        _write_report(
            evaluator_final.parent / "run_report.json",
            _evaluator(
                task_id, evaluator_final, requires_cosim=requires_cosim
            ),
        )
    return root


def test_official_audit_accepts_independently_linked_evidence(
    tmp_path: Path,
) -> None:
    result = audit(_run_root(tmp_path))

    assert result["acceptance_ok"] is True
    assert result["minimum_frequency_mhz"] == 200.0


def test_official_audit_recomputes_frequency_instead_of_trusting_ok(
    tmp_path: Path,
) -> None:
    root = _run_root(tmp_path)
    path = (
        root
        / "projection_bugfix"
        / "submission"
        / "projection_bugfix"
        / "run_report.json"
    )
    report = json.loads(path.read_text())
    report["gates"]["frequency_100mhz"].update(
        {
            "ok": True,
            "candidate_clock_ns": 10.01,
            "frequency_mhz": 100.0,
        }
    )
    _write_report(path, report)

    result = audit(root)

    assert result["acceptance_ok"] is False
    assert (
        "projection_bugfix:frequency_evidence_invalid"
        in result["errors"]
    )


def test_official_audit_rejects_kernel_or_cosim_hash_drift(
    tmp_path: Path,
) -> None:
    root = _run_root(tmp_path)
    evaluator_final = (
        root
        / "dotProduct_optimize"
        / "evaluator"
        / "dotProduct_optimize"
        / "final_kernel.cpp"
    )
    evaluator_final.write_text("void different() {}\n")
    residual_report_path = (
        root
        / "residual_stream_deadlock"
        / "submission"
        / "residual_stream_deadlock"
        / "run_report.json"
    )
    residual_report = json.loads(residual_report_path.read_text())
    residual_report["final_hardware"]["cosim"]["source_sha256"] = "0" * 64
    _write_report(residual_report_path, residual_report)

    result = audit(root)

    assert result["acceptance_ok"] is False
    assert (
        "dotProduct_optimize:evaluator_final_kernel_hash_mismatch"
        in result["errors"]
    )
    assert (
        "dotProduct_optimize:submission_evaluator_kernel_hash_mismatch"
        in result["errors"]
    )
    assert (
        "residual_stream_deadlock:"
        "residual_submission_cosim_kernel_mismatch"
        in result["errors"]
    )


def test_official_audit_rejects_execution_source_drift(
    tmp_path: Path,
) -> None:
    root = _run_root(tmp_path)
    path = root / "execution-source-end.json"
    source = json.loads(path.read_text())
    source["tree_sha256"] = "f" * 64
    _write_report(path, source)

    result = audit(root)

    assert result["acceptance_ok"] is False
    assert "execution_source_changed_during_official_run" in result["errors"]
