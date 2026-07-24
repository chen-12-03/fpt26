from __future__ import annotations

import json
from types import SimpleNamespace

from agent.analysis.issue_classifier import IssueClassification
from agent.analysis.log_normalizer import LogNormalizer, NormalizedLog
from agent.agents.optimize import OptimizeAgent
from agent.agents.repair import RepairAgent
from agent.agents.optimization.feedback import (
    OptimizationFailure,
    build_synth_failure,
    merge_optimization_failure,
)
from agent.prompts import build_repair_prompt


def _task(**overrides):
    values = {
        "id": "structured_context",
        "description": "Repair or optimize from measured evidence.",
        "type": "optimize",
        "difficulty": 3,
        "top": "top",
        "headers": {"top.h": "void top(int a[64]);"},
        "kernel_name": "top.cpp",
        "requires_cosim": False,
        "clock_ns": 5.0,
        "budget": 40,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _normalized(**overrides) -> NormalizedLog:
    values = {
        "stage": "synth",
        "status": "compile_error",
        "log_paths": ["<tool log>"],
        "error_summary": "top.cpp:17: error: unsupported call in loop compute",
        "warnings": [],
        "key_lines": [
            "top.cpp:17: error: unsupported call in loop compute",
            "ERROR: [HLS 200-1715] Synthesis failed for function top",
        ],
        "truncated": False,
        "missing_logs": False,
    }
    values.update(overrides)
    return NormalizedLog(**values)


def test_repair_prompt_contains_structured_issue_and_previous_attempt() -> None:
    issue = IssueClassification(
        condition="synth_failure",
        issue_category="synth_failure",
        stage="synth",
        confidence="high",
        evidence=["top.cpp:17: error: unsupported call"],
        recommended_action="repair_synthesizability",
    )

    prompt = build_repair_prompt(
        _task(),
        '#include "top.h"\nvoid top(int a[64]) { a[0] = 1; }\n',
        _normalized(),
        issue,
        attempt_feedback={
            "attempt": 2,
            "phase": "compile_error",
            "previous_attempt": {
                "attempt": 1,
                "candidate_diff": "@@ -1 +1 @@\n-a[0] = 1;\n+a[0] = helper();",
                "result": {
                    "stage": "synth",
                    "phase": "compile_error",
                    "summary": "helper is not synthesizable",
                },
            },
        },
    )
    payload = json.loads(prompt)
    evidence = payload["repair_evidence"]

    assert evidence["failure_stage"] == "synth"
    assert evidence["category"] == "synth_failure"
    assert evidence["confidence"] == "high"
    assert evidence["key_lines"][0].startswith("top.cpp:17:")
    assert evidence["suspected_source_location"] == "top.cpp:17"
    assert evidence["recommended_action"] == "repair_synthesizability"
    assert evidence["previous_attempt"]["candidate_diff"].startswith("@@")
    assert evidence["previous_attempt"]["result"]["summary"] == (
        "helper is not synthesizable"
    )


def test_repair_prompt_degrades_for_missing_or_partial_issue_fields() -> None:
    source = "void top(int a[64]) { a[0] = 1; }\n"

    missing_issue = json.loads(
        build_repair_prompt(_task(), source, _normalized(key_lines=[]), None)
    )["repair_evidence"]
    assert missing_issue["category"] == "unknown"
    assert missing_issue["confidence"] == "unknown"
    assert missing_issue["key_lines"] == []

    partial_issue = SimpleNamespace(
        issue_category="new_unregistered_failure",
        stage=None,
        recommended_action=None,
    )
    partial = json.loads(
        build_repair_prompt(_task(), source, _normalized(), partial_issue)
    )["repair_evidence"]
    assert partial["category"] == "new_unregistered_failure"
    assert partial["confidence"] == "unknown"
    assert partial["recommended_action"] == "inspect_failure_evidence"


def test_repair_context_is_bounded_unicode_safe_and_preserves_basename() -> None:
    raw = (
        b"\xff/tmp/private-build/src/top.cpp:42:9: error: "
        + b"x" * 20_000
        + b"\n"
        + b"error: FPT26_LLM_API_KEY=sk-do-not-leak-123456789\n"
        + b"ERROR: [HLS 200-1715] synthesis failed\n" * 100
    )
    normalized = LogNormalizer(
        max_line_chars=160, max_key_lines=12, max_warnings=4
    ).normalize("synth", "compile_error", raw)
    prompt = build_repair_prompt(
        _task(),
        "void top(int a[64]) { a[0] = 1; }\n",
        normalized,
        None,
    )
    evidence = json.loads(prompt)["repair_evidence"]
    encoded = json.dumps(evidence, ensure_ascii=False).encode(
        "utf-8", errors="strict"
    )

    assert len(encoded) <= 7_000
    assert "/tmp/private-build" not in prompt
    assert "sk-do-not-leak" not in prompt
    assert "top.cpp:42" in prompt
    assert evidence["truncated"] is True
    assert len(evidence["key_lines"]) <= 12


def test_optimization_failure_is_serializable_bounded_and_aggregated() -> None:
    result = SimpleNamespace(
        kind="synth",
        phase="compile_error",
        log=(
            "/workspace/build/top.cpp:8: error: unsupported recursion in loop compute\n"
            "ERROR: [HLS 200-1715] Synthesis failed"
        ),
    )
    best = "void top(int a[64]) { for (int i=0; i<64; ++i) a[i]++; }\n"
    candidate = best.replace(
        "for (", "#pragma HLS UNROLL factor=8\nfor ("
    )

    first = build_synth_failure(
        result, best, candidate, candidate_fingerprint="fp-a"
    )
    history = merge_optimization_failure([], first, max_entries=3)
    repeated = build_synth_failure(
        result,
        best,
        candidate.replace("factor=8", "factor=4"),
        candidate_fingerprint="fp-b",
    )
    history = merge_optimization_failure(history, repeated, max_entries=3)

    assert isinstance(history[-1], OptimizationFailure)
    assert history[-1].failure_category == "synth_failure"
    assert history[-1].repetition_count == 2
    assert history[-1].candidate_fingerprint == "fp-b"
    assert history[-1].candidate_action_diff_summary
    assert history[-1].implicated["pragmas"] == [
        "#pragma HLS UNROLL factor=4"
    ]
    assert "reduce factor" in history[-1].recommended_next_constraint.lower()
    serialized = history[-1].to_dict()
    assert serialized["candidate_action_diff_summary"]
    assert "failed_candidate_diff" not in serialized
    assert len(serialized["candidate_fingerprint"]) <= 64
    json.dumps(serialized, sort_keys=True)

    for index in range(6):
        distinct = OptimizationFailure(
            stage="synth",
            phase="compile_error",
            failure_category=f"distinct_{index}",
            error_summary=f"error {index}",
            key_diagnostic_lines=[f"error {index}"],
            candidate_fingerprint=f"fp-{index + 10}",
            candidate_action_diff_summary=f"diff {index}",
            implicated={"pragmas": [], "loops": [], "arrays": []},
            recommended_next_constraint="avoid pattern",
            repetition_count=1,
        )
        history = merge_optimization_failure(history, distinct, max_entries=3)
    assert len(history) == 3


def test_synth_failure_reaches_next_prompt_without_extra_llm_or_tools() -> None:
    starter_report = SimpleNamespace(
        latency_worst=100,
        interval_max=100,
        clock_period_ns=5.0,
        resources={
            "LUT": 200,
            "FF": 100,
            "DSP": 0,
            "BRAM_18K": 0,
            "URAM": 0,
        },
        loop_metrics=[],
    )
    starter = "void top(int a[64]) { for (int i=0; i<64; ++i) a[i]++; }\n"
    failed = starter.replace(
        "for (", "#pragma HLS UNROLL factor=8\nfor ("
    )

    class Llm:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system, prompt):
            self.calls += 1
            if self.calls == 1:
                metadata = json.loads(
                    json.loads(prompt)["source_design_metadata"]
                )
                assert metadata["loops"][0]["trip_count"] == 64
                assert metadata["arrays"][0]["name"] == "a"
                return failed
            payload = json.loads(prompt)
            feedback = payload["previous_candidate_feedback"]
            assert feedback["status"].startswith("REJECTED_BY_SYNTH")
            assert feedback["failure_category"] == "synth_failure"
            assert feedback["repetition_count"] == 1
            assert "do not repeat" in payload["instruction"].lower()
            return starter

    class Server:
        def __init__(self) -> None:
            self.csim_calls = 0
            self.synth_calls = 0

        def csim(self, kernel):
            self.csim_calls += 1
            return SimpleNamespace(
                kind="csim", ok=True, phase="pass", report=None, log=""
            )

        def synth(self, kernel):
            self.synth_calls += 1
            return SimpleNamespace(
                kind="synth",
                ok=False,
                phase="compile_error",
                report=None,
                log="top.cpp:2: error: unsupported unrolled loop",
            )

    llm = Llm()
    server = Server()
    state = SimpleNamespace(
        task=_task(),
        server=server,
        kernel=starter,
        best_latency=100,
        results=[
            SimpleNamespace(
                kind="synth",
                ok=True,
                phase="pass",
                report=starter_report,
                log="",
            )
        ],
        metadata={},
        log=lambda message: None,
    )

    result = OptimizeAgent(llm, max_rounds=2).run(state)

    assert result.kernel == starter
    assert llm.calls == 2
    assert server.csim_calls == 1
    assert server.synth_calls == 1
    assert len(result.metadata["optimization_failures"]) == 1
    assert result.metadata["optimization_failures"][0]["repetition_count"] == 1


def test_repair_agent_reflects_previous_attempt_without_extra_llm_call() -> None:
    starter = "void top(int a[64]) { a[0] = 0; }\n"
    bad = "void top(int a[64]) { a[0] = helper(); }\n"
    corrected = "void top(int a[64]) { a[0] = 1; }\n"

    def result(kind, ok, phase, log="", report=None):
        return SimpleNamespace(
            kind=kind,
            ok=ok,
            phase=phase,
            log=log,
            report=report,
            brief=lambda: f"[{kind}] {phase}",
        )

    initial = result(
        "csim", False, "runtime_fail", "top.cpp:1: mismatch: expected 1"
    )
    synth_report = SimpleNamespace(
        latency_worst=10,
        latency_avg=10,
        clock_period_ns=5.0,
        resources={
            "LUT": 1,
            "FF": 1,
            "DSP": 0,
            "BRAM_18K": 0,
            "URAM": 0,
        },
        available={
            "LUT": 100,
            "FF": 100,
            "DSP": 100,
            "BRAM_18K": 100,
            "URAM": 100,
        },
    )

    class Llm:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system, prompt):
            self.calls += 1
            if self.calls == 1:
                return bad
            evidence = json.loads(prompt)["repair_evidence"]
            assert evidence["previous_attempt"]["attempt"] == 1
            assert "helper()" in evidence["previous_attempt"]["candidate_diff"]
            assert evidence["previous_attempt"]["result"]["phase"] == (
                "runtime_fail"
            )
            return corrected

    class Server:
        def __init__(self) -> None:
            self.csim_calls = 0
            self.synth_calls = 0

        def csim(self, kernel):
            self.csim_calls += 1
            if "helper()" in kernel:
                return result(
                    "csim",
                    False,
                    "runtime_fail",
                    "top.cpp:1: mismatch: helper returned wrong value",
                )
            return result("csim", True, "pass")

        def synth(self, kernel):
            self.synth_calls += 1
            return result("synth", True, "pass", report=synth_report)

    llm = Llm()
    server = Server()
    state = SimpleNamespace(
        task=_task(),
        server=server,
        kernel=starter,
        results=[initial],
        csim_ok=False,
        synth_ok=False,
        status="running",
        stop_reason="",
        metadata={},
        interface_ok=False,
        frequency_ok=False,
        resource_ok=False,
        cosim_ok=False,
        best_latency=None,
        last_verified_kernel=None,
        log=lambda message: None,
    )

    repaired = RepairAgent(llm, max_attempts=2).run(state)

    assert repaired.kernel == corrected
    assert llm.calls == 2
    assert server.csim_calls == 2
    assert server.synth_calls == 1
