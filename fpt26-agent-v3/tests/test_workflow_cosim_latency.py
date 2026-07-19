import json
from types import SimpleNamespace

import agent.workflow as workflow
from agent.reporting import write_run_report


_CAPACITY = {
    "LUT": 1303680,
    "FF": 2607360,
    "DSP": 9024,
    "BRAM_18K": 4032,
    "URAM": 960,
}


def _report(*, latency: int, interval: int, lut: int, ff: int) -> SimpleNamespace:
    return SimpleNamespace(
        latency_worst=latency,
        latency_avg=latency,
        interval_max=interval,
        clock_period_ns=2.796,
        resources={
            "LUT": lut,
            "FF": ff,
            "DSP": 0,
            "BRAM_18K": 0,
            "URAM": 0,
        },
        available=dict(_CAPACITY),
    )


def _state(tmp_path) -> SimpleNamespace:
    task = SimpleNamespace(
        id="measured_cosim",
        type="structural",
        difficulty=4,
        requires_cosim=True,
        budget=80,
        clock_ns=5.0,
        kernel_name="residual.cpp",
        kernel_code="void residual() {}\n",
        reference_code=None,
        headers={},
        hidden_tb_code="int main() { return 0; }\n",
        hidden_tb_name="residual_tb.cpp",
        top="residual",
        part="xcu55c-fsvh2892-2L-e",
        assemble=lambda kernel, tb, tb_name: {
            "residual.cpp": kernel,
            tb_name: tb,
        },
    )
    config = SimpleNamespace(
        score=True,
        output_root=str(tmp_path),
        mode="structural",
        competition=False,
    )
    return SimpleNamespace(
        config=config,
        task=task,
        kernel="void residual() {}\n",
        server=SimpleNamespace(budget=SimpleNamespace(spent=0, total=80)),
        scorecard=None,
        ref_scorecard=None,
        log=lambda message: None,
        results=[],
        llm=None,
        status="completed",
        csim_ok=True,
        synth_ok=True,
        cosim_ok=True,
        best_latency=68,
        stop_reason="",
        metadata={},
    )


def _run_score(monkeypatch, tmp_path, measured_latency):
    candidate = _report(latency=68, interval=64, lut=406, ff=231)
    baseline = _report(latency=135, interval=136, lut=539, ff=248)
    synth_results = iter(
        [
            SimpleNamespace(ok=True, report=candidate),
            SimpleNamespace(ok=True, report=baseline),
        ]
    )

    class FakeCSimTool:
        def run(self, *args, **kwargs):
            return SimpleNamespace(ok=True, report=None)

    class FakeCoSimTool:
        def run(self, *args, **kwargs):
            cosim = (
                SimpleNamespace(passed=True, latency_max=measured_latency)
                if measured_latency is not None
                else SimpleNamespace(passed=True, latency_max=None)
            )
            return SimpleNamespace(ok=True, report=candidate, cosim=cosim)

    class FakeSynthTool:
        def run(self, *args, **kwargs):
            return next(synth_results)

    monkeypatch.setattr(workflow, "CSimTool", FakeCSimTool)
    monkeypatch.setattr(workflow, "CoSimTool", FakeCoSimTool)
    monkeypatch.setattr(workflow, "SynthTool", FakeSynthTool)
    return workflow.step_score(_state(tmp_path))


def test_step_score_uses_measured_rtl_latency_not_cosim_synth_estimate(
    monkeypatch, tmp_path
) -> None:
    state = _run_score(monkeypatch, tmp_path, measured_latency=97)
    card = state.scorecard

    assert card.valid
    assert card.acceleration_source == "cosim"
    assert card.cosim_latency_used == 97
    assert card.latency_ratio == 1.39
    assert card.latency_ratio != round(135 / 68, 2)


def test_step_score_fails_closed_when_passed_cosim_has_no_measured_latency(
    monkeypatch, tmp_path
) -> None:
    state = _run_score(monkeypatch, tmp_path, measured_latency=None)

    assert state.scorecard is None
    assert state.status == "failed"
    assert state.stop_reason == "required_cosim_report_missing"


def test_run_report_audits_measured_cosim_source(monkeypatch, tmp_path) -> None:
    state = _run_score(monkeypatch, tmp_path, measured_latency=97)

    report = json.loads(write_run_report(state).read_text())

    assert report["scoring"]["acceleration_source"] == "cosim"
    assert report["scoring"]["cosim_latency_used"] == 97
