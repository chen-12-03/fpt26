"""Run reports must preserve tool phases, codes, logs, and artifact locations."""

import json
from types import SimpleNamespace

from agent.reporting import write_run_report
from llm4hls.tools import ToolResult


def test_run_report_persists_metered_and_grading_failure_evidence(tmp_path) -> None:
    metered = ToolResult(
        "csim",
        False,
        "runtime_fail",
        7,
        "public mismatch at index 3",
        1.25,
    )
    hidden = ToolResult(
        "csim",
        False,
        "runtime_fail",
        9,
        "hidden mismatch at index 5",
        2.5,
    )
    server = SimpleNamespace(
        budget=SimpleNamespace(total=20, spent=1),
        run_root=tmp_path / "trace_task/agent",
        transcript=[
            SimpleNamespace(
                n=1,
                kind="csim",
                phase="runtime_fail",
                spent=1,
                detail=metered.brief(),
            )
        ],
    )
    state = SimpleNamespace(
        task=SimpleNamespace(
            id="trace_task",
            type="repair",
            difficulty=2,
            requires_cosim=False,
        ),
        config=SimpleNamespace(
            output_root=str(tmp_path), mode="baseline", competition=False
        ),
        server=server,
        results=[metered],
        metadata={"grading_results": [("hidden_csim", hidden)]},
        llm=None,
        scorecard=None,
        ref_scorecard=None,
        status="failed",
        stop_reason="hidden_csim_fail",
        csim_ok=False,
        synth_ok=False,
        cosim_ok=False,
        best_latency=None,
    )

    report = json.loads(write_run_report(state).read_text())
    trace = report["execution_trace"]

    assert report["tool_call_count"] == 1
    assert report["evaluation"]["csim_attempts"] == 1
    assert trace["transcript"] == [
        {
            "artifact_dir": str(tmp_path / "trace_task/agent/csim_1"),
            "detail": metered.brief(),
            "kind": "csim",
            "n": 1,
            "phase": "runtime_fail",
            "spent": 1,
        }
    ]
    assert trace["metered_results"][0]["return_code"] == 7
    assert trace["metered_results"][0]["log"] == "public mismatch at index 3"
    assert trace["grading_results"][0]["stage"] == "hidden_csim"
    assert trace["grading_results"][0]["return_code"] == 9
    assert trace["grading_results"][0]["log"] == "hidden mismatch at index 5"
    assert trace["grading_results"][0]["artifact_dir"].endswith(
        "trace_task/grade/grade_csim"
    )
