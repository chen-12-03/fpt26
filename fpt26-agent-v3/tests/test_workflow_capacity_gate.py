from types import SimpleNamespace

import agent.workflow as workflow


_CAPACITY = {
    "LUT": 200,
    "FF": 200,
    "DSP": 10,
    "BRAM_18K": 10,
    "URAM": 10,
}


def _report(*, lut: int, available: dict | None) -> SimpleNamespace:
    return SimpleNamespace(
        latency_worst=100,
        latency_avg=100,
        interval_max=1,
        clock_period_ns=5.0,
        resources={
            "LUT": lut,
            "FF": 100,
            "DSP": 2,
            "BRAM_18K": 0,
            "URAM": 0,
        },
        available=available,
    )


def _state(tmp_path) -> SimpleNamespace:
    task = SimpleNamespace(
        id="capacity_integration",
        type="optimize",
        difficulty=3,
        requires_cosim=False,
        budget=40,
        clock_ns=5.0,
        kernel_name="top.cpp",
        kernel_code="void top() {}\n",
        reference_code=None,
        headers={},
        hidden_tb_code="int main() { return 0; }\n",
        hidden_tb_name="top_tb.cpp",
        top="top",
        part="xcu55c-fsvh2892-2L-e",
        assemble=lambda kernel, tb, tb_name: {
            "top.cpp": kernel,
            tb_name: tb,
        },
    )
    return SimpleNamespace(
        config=SimpleNamespace(score=True, output_root=str(tmp_path)),
        task=task,
        kernel="void top() {}\n",
        server=SimpleNamespace(budget=SimpleNamespace(spent=0)),
        scorecard=None,
        log=lambda message: None,
    )


def _run_score(monkeypatch, tmp_path, candidate, baseline):
    synth_results = iter(
        [
            SimpleNamespace(ok=True, report=candidate),
            SimpleNamespace(ok=True, report=baseline),
        ]
    )

    class FakeCSimTool:
        def run(self, *args, **kwargs):
            return SimpleNamespace(ok=True, report=None)

    class FakeSynthTool:
        def run(self, *args, **kwargs):
            return next(synth_results)

    monkeypatch.setattr(workflow, "CSimTool", FakeCSimTool)
    monkeypatch.setattr(workflow, "SynthTool", FakeSynthTool)
    return workflow.step_score(_state(tmp_path)).scorecard


def test_step_score_propagates_capacity_and_rejects_overflow(
    monkeypatch, tmp_path
) -> None:
    card = _run_score(
        monkeypatch,
        tmp_path,
        _report(lut=201, available=dict(_CAPACITY)),
        _report(lut=100, available=dict(_CAPACITY)),
    )

    assert not card.valid
    assert card.gate_reason == "resource_capacity_exceeded"
    assert card.available_resources == _CAPACITY
    assert card.resource_capacity_pass is False


def test_step_score_fails_closed_when_anchor_capacity_is_missing(
    monkeypatch, tmp_path
) -> None:
    card = _run_score(
        monkeypatch,
        tmp_path,
        _report(lut=100, available=dict(_CAPACITY)),
        _report(lut=100, available=None),
    )

    assert not card.valid
    assert card.gate_reason == "required_metric_missing"
    assert card.available_resources == {}
