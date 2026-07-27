from __future__ import annotations

from types import SimpleNamespace

from agent.cli import parse_args
from agent.console_ui import configure, progress, strip_ansi
from agent.reporting.pretty import print_evaluation


def test_color_cli_policy() -> None:
    assert parse_args(["--task", "/tmp/task"]).color == "auto"
    assert parse_args(["--task", "/tmp/task", "--color", "always"]).color == "always"


def test_progress_is_classified_and_wrapped(monkeypatch, capsys) -> None:
    monkeypatch.setenv("FPT26_CONSOLE_WIDTH", "72")
    configure("never")
    progress("auto", "synth: [synth] pass (rc=0, 22.3s)  latency=91  top_interval=92  loops=very_long_loop_name")
    lines = capsys.readouterr().out.splitlines()
    assert "✓ SYNTH" in lines[0]
    assert "PASS" in lines[0]
    assert all(len(line) <= 72 for line in lines)


def test_forced_color_survives_a_pipe(capsys) -> None:
    configure("always")
    progress("auto", "csim: [csim] pass (rc=0, 1.0s)")
    output = capsys.readouterr().out
    assert "\x1b[" in output
    assert "CSIM" in strip_ansi(output)
    configure("auto")


def test_compact_report_does_not_overflow(monkeypatch, capsys) -> None:
    monkeypatch.setenv("FPT26_CONSOLE_WIDTH", "96")
    configure("never")
    report = SimpleNamespace(
        latency_worst=91,
        latency_avg=91,
        interval_max=92,
        clock_period_ns=1.614,
        resources={"LUT": 776, "FF": 471, "DSP": 0, "BRAM_18K": 0, "URAM": 0},
        loop_metrics=[{"name": "VITIS_LOOP_199_1", "pipeline_ii": 5}],
    )
    synth = SimpleNamespace(kind="synth", ok=True, report=report, elapsed_s=22.3)
    csim = SimpleNamespace(kind="csim", ok=True, report=None, elapsed_s=6.0)
    state = SimpleNamespace(
        task=SimpleNamespace(id="c2hlsc__des", requires_cosim=False),
        status="completed",
        stop_reason="",
        csim_ok=True,
        synth_ok=True,
        cosim_ok=False,
        scorecard=None,
        results=[csim, synth],
        metadata={
            "best_synth_metrics": {
                "latency_worst": 91,
                "interval_max": 92,
                "clock_period_ns": 1.614,
                "resources": report.resources,
                "loop_metrics": report.loop_metrics,
            }
        },
        server=SimpleNamespace(
            budget=SimpleNamespace(spent=5, total=50),
            transcript=[SimpleNamespace(n=1, kind="csim"), SimpleNamespace(n=2, kind="synth")],
        ),
        llm=None,
    )

    print_evaluation(state)

    lines = capsys.readouterr().out.splitlines()
    assert any("QOR SUMMARY" in line for line in lines)
    assert any("LUT=776" in line for line in lines)
    assert all(len(strip_ansi(line)) <= 96 for line in lines)
