"""Regression tests for independent, measured optimization strategy lanes."""

from __future__ import annotations

import json
from types import SimpleNamespace

from agent.agents.base import AgentConfig, RunState
from agent.agents.competition import (
    DIVERSE_OPTIMIZATION_STRATEGIES,
    DiverseOptimizationStage,
)
from agent.agents.optimize import _strategy_contract_violation
from agent.prompts import build_prompt


_AVAILABLE = {
    "LUT": 100_000,
    "FF": 200_000,
    "DSP": 1_000,
    "BRAM_18K": 1_000,
    "URAM": 100,
}


def _report(*, latency: int, resources: int) -> SimpleNamespace:
    return SimpleNamespace(
        latency_worst=latency,
        latency_avg=latency,
        interval_max=latency,
        clock_period_ns=5.0,
        resources={
            "LUT": resources,
            "FF": resources,
            "DSP": max(1, resources // 50),
            "BRAM_18K": 0,
            "URAM": 0,
        },
        available=dict(_AVAILABLE),
        pipeline_type="loop",
        loop_metrics=[
            {
                "name": "reduce",
                "trip_count": latency,
                "latency": latency,
                "pipeline_ii": 1,
            }
        ],
    )


_STARTER = """int top(int *a) {
  int sum = 0;
  for (int i = 0; i < 100; ++i) {
    sum += a[i];
  }
  return sum;
}
"""
_CONSERVATIVE = _STARTER.replace(
    "    sum += a[i];",
    "#pragma HLS UNROLL factor=2\n    sum += a[i];",
)
_RESTRUCTURED = """int top(int *a) {
  int even = 0;
  int odd = 0;
  for (int i = 0; i < 100; i += 2) {
    even += a[i];
    odd += a[i + 1];
  }
  return even + odd;
}
"""
_AGGRESSIVE = _CONSERVATIVE.replace("factor=2", "factor=8")
_BROKEN = _STARTER.replace("return sum;", "return missing;")


def _task() -> SimpleNamespace:
    return SimpleNamespace(
        id="diverse_probe",
        type="optimize",
        difficulty=1,
        requires_cosim=False,
        budget=40,
        clock_ns=5.0,
        description="Reduce an integer vector.",
        headers={},
        top="top",
        kernel_name="top.cpp",
    )


class _LaneLlm:
    def __init__(self, responses: dict[str, str | list[str]]) -> None:
        self.responses = responses
        self.strategies: list[str] = []

    def complete(self, system: str, prompt: str) -> str:
        payload = json.loads(prompt)
        strategy = payload["search_strategy"]["name"]
        self.strategies.append(strategy)
        assert "hard independent-lane contract" in payload["instruction"]
        response = self.responses[strategy]
        if isinstance(response, list):
            return response.pop(0)
        return response


class _Server:
    def __init__(self) -> None:
        self.csim_calls: list[str] = []
        self.synth_calls: list[str] = []

    def csim(self, kernel: str) -> SimpleNamespace:
        self.csim_calls.append(kernel)
        ok = "missing" not in kernel
        return SimpleNamespace(
            kind="csim", ok=ok, report=None,
            log="" if ok else "undeclared identifier missing",
            phase="pass" if ok else "compile_error", elapsed_s=0.0,
        )

    def synth(self, kernel: str) -> SimpleNamespace:
        self.synth_calls.append(kernel)
        if "factor=2" in kernel:
            report = _report(latency=50, resources=200)
        elif "factor=8" in kernel:
            report = _report(latency=20, resources=1_000)
        elif "int even" in kernel:
            report = _report(latency=60, resources=105)
        else:
            raise AssertionError("unexpected synthesis candidate")
        return SimpleNamespace(
            kind="synth", ok=True, report=report, log="", elapsed_s=0.0
        )


def _state(server: _Server, llm: _LaneLlm) -> RunState:
    baseline = SimpleNamespace(
        kind="synth", ok=True, report=_report(latency=100, resources=100),
        log="", elapsed_s=0.0,
    )
    return RunState(
        task=_task(),
        server=server,
        llm=llm,
        config=AgentConfig(
            mode="optimize", competition=True, verbose=False,
            max_optimization_rounds=3, scoring_profile="balanced",
        ),
        kernel=_STARTER,
        results=[baseline],
        csim_ok=True,
        synth_ok=True,
        best_latency=100,
    )


def test_strategy_prompt_is_explicit_and_mutually_constrained() -> None:
    strategy = DIVERSE_OPTIMIZATION_STRATEGIES[1]
    prompt = build_prompt(
        _task(), _STARTER,
        csim_result="PASS", synth_result="PASS",
        search_strategy=strategy,
    )
    payload = json.loads(prompt)
    assert payload["search_strategy"]["name"] == "source_reduction_restructure"
    assert "source-level reduction" in payload["search_strategy"]["objective"]
    assert "Do not copy another lane's action" in payload["instruction"]


def test_strategy_contracts_enforce_distinct_candidate_families() -> None:
    conservative, restructure, speed = DIVERSE_OPTIMIZATION_STRATEGIES
    assert _strategy_contract_violation(
        _STARTER, _CONSERVATIVE, conservative
    ) is None
    assert _strategy_contract_violation(
        _STARTER, _RESTRUCTURED, restructure
    ) is None
    assert _strategy_contract_violation(_STARTER, _AGGRESSIVE, speed) is None
    banked_speed = _AGGRESSIVE.replace(
        "  for (int i = 0;",
        "#pragma HLS ARRAY_PARTITION variable=a cyclic factor=8 dim=1\n"
        "  for (int i = 0;",
    )
    assert _strategy_contract_violation(_STARTER, banked_speed, speed) is None
    assert "preserve non-pragma" in _strategy_contract_violation(
        _STARTER, _RESTRUCTURED, conservative
    )
    assert "cannot add HLS pragmas" in _strategy_contract_violation(
        _STARTER, _CONSERVATIVE, restructure
    )
    assert "factor<=2" in _strategy_contract_violation(
        _STARTER, _CONSERVATIVE, speed
    )


def test_diverse_search_measures_all_lanes_and_selects_highest_q_hw() -> None:
    responses = {
        "conservative_loop_parallelism": _CONSERVATIVE,
        "source_reduction_restructure": _RESTRUCTURED,
        "speed_first_parallel_architecture": _AGGRESSIVE,
    }
    llm = _LaneLlm(responses)
    server = _Server()

    result = DiverseOptimizationStage(
        llm, max_candidates=3, scoring_profile="balanced"
    ).run(_state(server, llm))

    assert llm.strategies == [s["name"] for s in DIVERSE_OPTIMIZATION_STRATEGIES]
    assert len(server.csim_calls) == 3
    assert len(server.synth_calls) == 3
    # The aggressive candidate has the lowest cycles, but its area explosion
    # loses Q_HW.  The source-level rewrite must win the measured selection.
    assert result.kernel == _RESTRUCTURED
    search = result.metadata["optimization_search"]
    assert search["selector"] == "highest_measured_q_hw"
    assert search["qor_rag_generalized"] is True
    assert "exact-source" in search["qor_rag_policy"]
    assert search["winner"] == "source_reduction_restructure"
    assert [s["selected"] for s in search["strategies"]] == [False, True, False]
    decisions = {
        c.get("strategy"): c["decision"]
        for c in result.metadata["synth_candidates"]
        if not c.get("is_baseline")
    }
    assert decisions["conservative_loop_parallelism"] == "VALID_NOT_SELECTED"
    assert decisions["source_reduction_restructure"] == "SELECTED"
    assert decisions["speed_first_parallel_architecture"] == "REJECTED"


def test_cross_strategy_duplicate_skips_tools_but_not_other_llm_lanes() -> None:
    responses = {
        "conservative_loop_parallelism": _CONSERVATIVE,
        "source_reduction_restructure": _RESTRUCTURED,
        # A source rewrite is also structurally admissible in the speed-first
        # lane, so this duplicate reaches the shared semantic de-duplicator.
        "speed_first_parallel_architecture": [_RESTRUCTURED, _AGGRESSIVE],
    }
    llm = _LaneLlm(responses)
    server = _Server()

    result = DiverseOptimizationStage(
        llm, max_candidates=3, scoring_profile="balanced"
    ).run(_state(server, llm))

    assert len(llm.strategies) == 4
    assert len(server.csim_calls) == 3
    assert len(server.synth_calls) == 3
    assert result.metadata["cross_strategy_duplicate_skips"] == 1


def test_failed_lane_does_not_stop_remaining_strategy_measurements() -> None:
    responses = {
        "conservative_loop_parallelism": _CONSERVATIVE,
        "source_reduction_restructure": [_BROKEN, _RESTRUCTURED],
        "speed_first_parallel_architecture": _AGGRESSIVE,
    }
    llm = _LaneLlm(responses)
    server = _Server()

    result = DiverseOptimizationStage(
        llm, max_candidates=3, scoring_profile="balanced"
    ).run(_state(server, llm))

    assert len(llm.strategies) == 4
    assert len(server.csim_calls) == 4
    assert len(server.synth_calls) == 3
    assert result.kernel == _RESTRUCTURED
    assert result.metadata["optimization_search"]["winner"] == (
        "source_reduction_restructure"
    )


def test_strategy_contract_rejection_is_reflected_once_then_measured() -> None:
    responses = {
        "conservative_loop_parallelism": _CONSERVATIVE,
        "source_reduction_restructure": _RESTRUCTURED,
        "speed_first_parallel_architecture": [_CONSERVATIVE, _AGGRESSIVE],
    }
    llm = _LaneLlm(responses)
    server = _Server()

    result = DiverseOptimizationStage(
        llm, max_candidates=3, scoring_profile="balanced"
    ).run(_state(server, llm))

    assert len(llm.strategies) == 4
    assert len(server.csim_calls) == 3
    assert len(server.synth_calls) == 3
    speed = result.metadata["optimization_search"]["strategies"][2]
    assert speed["strategy_contract_rejections"] == 1
    assert speed["strategy_contract_rejection_reasons"] == [
        "speed-first lane cannot reuse conservative factor<=2"
    ]
    assert speed["measured_candidate"] is True
