from types import SimpleNamespace

from agent.agents.optimize import _score_candidate


def test_structural_proxy_uses_required_measured_cosim_latency() -> None:
    task = SimpleNamespace(
        id="structural_proxy",
        type="structural",
        difficulty=4,
        requires_cosim=True,
        budget=80,
        clock_ns=5.0,
    )
    report = SimpleNamespace(
        latency_worst=68,
        latency_avg=68,
        interval_max=64,
        clock_period_ns=2.796,
        resources={
            "LUT": 406,
            "FF": 231,
            "DSP": 0,
            "BRAM_18K": 0,
            "URAM": 0,
        },
        available={
            "LUT": 1_303_680,
            "FF": 2_607_360,
            "DSP": 9_024,
            "BRAM_18K": 4_032,
            "URAM": 960,
        },
        pipeline_type=None,
        loop_metrics=[],
    )

    card = _score_candidate(
        task,
        report,
        report,
        cosim_latency=97,
    )

    assert card.valid
    assert card.acceleration_source == "cosim"
    assert card.cosim_latency_used == 97
    assert card.q_hw > 0
