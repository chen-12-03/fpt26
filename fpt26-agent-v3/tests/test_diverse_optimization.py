"""Regression tests for independent, measured optimization strategy lanes."""

from __future__ import annotations

import json
from types import SimpleNamespace

from agent.agents.base import AgentConfig, RunState
from agent.agents.competition import (
    DIVERSE_OPTIMIZATION_STRATEGIES,
    DiverseOptimizationStage,
)
from agent.agents.optimize import (
    _report_supported_action_violation,
    _strategy_contract_violation,
    candidate_action_summary,
)
from agent.analysis.action_contract import (
    augment_action_contract_with_source_architecture,
)
from agent.analysis.source_metadata import (
    source_reduction_parallelism_evidence,
)
from agent.prompts import build_prompt
from agent.pipeline.submission import _run_pipeline


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


_STARTER = """void stage1(int *a, int tmp[100]) {
  for (int i = 0; i < 100; ++i) {
    tmp[i] = a[i];
  }
}
void stage2(int tmp[100], int *out) {
  int sum = 0;
  for (int i = 0; i < 100; ++i) sum += tmp[i];
  *out = sum;
}
void top(int *a, int *out) {
  int tmp[100];
  stage1(a, tmp);
  stage2(tmp, out);
}
"""
_CONSERVATIVE = _STARTER.replace(
    "    tmp[i] = a[i];",
    "#pragma HLS UNROLL factor=2\n    tmp[i] = a[i];",
)
_TASK_PIPELINE = _STARTER.replace(
    "void top(int *a, int *out) {",
    "void top(int *a, int *out) {\n#pragma HLS DATAFLOW",
)
_RESTRUCTURED = """void stage1(int *a, int tmp[100]) {
  for (int i = 0; i < 100; i += 2) {
    tmp[i] = a[i];
    tmp[i + 1] = a[i + 1];
  }
}
void stage2(int tmp[100], int *out) {
  int even = 0;
  int odd = 0;
  for (int i = 0; i < 100; i += 2) {
    even += tmp[i];
    odd += tmp[i + 1];
  }
  *out = even + odd;
}
void top(int *a, int *out) {
  int tmp[100];
  stage1(a, tmp);
  stage2(tmp, out);
}
"""
_AGGRESSIVE = _CONSERVATIVE.replace("factor=2", "factor=8")
_BROKEN = _STARTER.replace("*out = sum;", "*out = missing;")


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
        if "HLS DATAFLOW" in kernel:
            report = _report(latency=45, resources=110)
        elif "factor=2" in kernel:
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
    assert payload["search_strategy"]["name"] == "task_pipeline_architecture"
    assert "task-pipeline architecture" in payload["search_strategy"]["objective"]
    assert "Do not copy another lane's action" in payload["instruction"]


def test_strategy_contracts_enforce_distinct_candidate_families() -> None:
    directive, task_pipeline, restructure = DIVERSE_OPTIMIZATION_STRATEGIES
    assert _strategy_contract_violation(
        _STARTER, _CONSERVATIVE, directive
    ) is None
    assert _strategy_contract_violation(
        _STARTER, _TASK_PIPELINE, task_pipeline
    ) is None
    assert _strategy_contract_violation(
        _STARTER, _RESTRUCTURED, restructure
    ) is None
    assert "preserve non-pragma" in _strategy_contract_violation(
        _STARTER, _RESTRUCTURED, directive
    )
    assert "must change the non-pragma architecture" in _strategy_contract_violation(
        _STARTER, _TASK_PIPELINE, restructure
    )
    assert "requires one DATAFLOW" in _strategy_contract_violation(
        _STARTER, _CONSERVATIVE, task_pipeline
    )


def test_task_pipeline_directives_form_one_coherent_action_family() -> None:
    candidate = _TASK_PIPELINE.replace(
        "void stage1(int *a, int tmp[100]) {",
        "void stage1(int *a, int tmp[100]) {\n#pragma HLS INLINE OFF",
    ).replace(
        "for (int i = 0; i < 100; ++i) {",
        "for (int i = 0; i < 100; ++i) {\n#pragma HLS PIPELINE",
        1,
    )

    action = candidate_action_summary(
        _STARTER, candidate, top_function="top"
    )

    assert action["families"] == ["TASK_PIPELINE"]


def test_source_proven_reduction_composite_passes_action_guard() -> None:
    starter = """
float top(float a[SIZE], float b[SIZE]) {
  float sum = 0;
  for (int i = 0; i < SIZE; ++i) {
    sum += a[i] * b[i];
  }
  return sum;
}
"""
    candidate = """
float top(float a[SIZE], float b[SIZE]) {
#pragma HLS ARRAY_PARTITION variable=a cyclic factor=PAR_FACTOR
#pragma HLS ARRAY_PARTITION variable=b cyclic factor=PAR_FACTOR
  float sum = 0;
  for (int i = 0; i < SIZE / PAR_FACTOR; ++i) {
#pragma HLS PIPELINE II=1
    for (int j = 0; j < PAR_FACTOR; ++j)
      sum += a[i * PAR_FACTOR + j] * b[i * PAR_FACTOR + j];
  }
  return sum;
}
"""
    evidence = source_reduction_parallelism_evidence(
        starter,
        top_function="top",
        constant_context=(
            "const int SIZE = 1024;\n#define PAR_FACTOR 32\n"
        ),
    )
    contract = augment_action_contract_with_source_architecture(
        None, evidence
    )
    action = candidate_action_summary(
        starter, candidate, top_function="top"
    )

    violation = _report_supported_action_violation(
        action,
        _report(latency=100, resources=100),
        contract,
        source_banking_evidence=[],
        source_metadata={},
    )

    assert set(action["families"]) == {
        "MEMORY_BANKING",
        "PIPELINE",
        "SOURCE_RESTRUCTURE",
    }
    assert violation is None


def test_diverse_search_measures_all_lanes_and_selects_highest_q_hw() -> None:
    responses = {
        "evidence_backed_directive": _CONSERVATIVE,
        "task_pipeline_architecture": _TASK_PIPELINE,
        "source_parallel_architecture": _RESTRUCTURED,
    }
    llm = _LaneLlm(responses)
    server = _Server()

    result = DiverseOptimizationStage(
        llm, max_candidates=3, scoring_profile="balanced"
    ).run(_state(server, llm))

    assert llm.strategies == [s["name"] for s in DIVERSE_OPTIMIZATION_STRATEGIES]
    assert len(server.csim_calls) == 3
    assert len(server.synth_calls) == 3
    assert result.kernel == _TASK_PIPELINE
    search = result.metadata["optimization_search"]
    assert search["selector"] == "highest_measured_q_hw"
    assert search["qor_rag_generalized"] is True
    assert "exact-source" in search["qor_rag_policy"]
    assert search["winner"] == "task_pipeline_architecture"
    assert [s["selected"] for s in search["strategies"]] == [False, True, False]
    decisions = {
        c.get("strategy"): c["decision"]
        for c in result.metadata["synth_candidates"]
        if not c.get("is_baseline")
    }
    assert decisions["evidence_backed_directive"] == "VALID_NOT_SELECTED"
    assert decisions["task_pipeline_architecture"] == "SELECTED"
    assert decisions["source_parallel_architecture"] == "VALID_NOT_SELECTED"


def test_lane_contract_retry_does_not_stop_other_measurements() -> None:
    responses = {
        "evidence_backed_directive": _CONSERVATIVE,
        "task_pipeline_architecture": [_CONSERVATIVE, _TASK_PIPELINE],
        "source_parallel_architecture": _RESTRUCTURED,
    }
    llm = _LaneLlm(responses)
    server = _Server()

    result = DiverseOptimizationStage(
        llm, max_candidates=3, scoring_profile="balanced"
    ).run(_state(server, llm))

    assert len(llm.strategies) == 4
    assert len(server.csim_calls) == 3
    assert len(server.synth_calls) == 3
    assert result.metadata["strategy_contract_rejections"] == 1


def test_failed_lane_does_not_stop_remaining_strategy_measurements() -> None:
    responses = {
        "evidence_backed_directive": _CONSERVATIVE,
        "task_pipeline_architecture": _TASK_PIPELINE,
        "source_parallel_architecture": [_BROKEN, _RESTRUCTURED],
    }
    llm = _LaneLlm(responses)
    server = _Server()

    result = DiverseOptimizationStage(
        llm, max_candidates=3, scoring_profile="balanced"
    ).run(_state(server, llm))

    assert len(llm.strategies) == 4
    assert len(server.csim_calls) == 4
    assert len(server.synth_calls) == 3
    assert result.kernel == _TASK_PIPELINE
    assert result.metadata["optimization_search"]["winner"] == (
        "task_pipeline_architecture"
    )


def test_strategy_contract_rejection_is_reflected_once_then_measured() -> None:
    responses = {
        "evidence_backed_directive": _CONSERVATIVE,
        "task_pipeline_architecture": [_CONSERVATIVE, _TASK_PIPELINE],
        "source_parallel_architecture": _RESTRUCTURED,
    }
    llm = _LaneLlm(responses)
    server = _Server()

    result = DiverseOptimizationStage(
        llm, max_candidates=3, scoring_profile="balanced"
    ).run(_state(server, llm))

    assert len(llm.strategies) == 4
    assert len(server.csim_calls) == 3
    assert len(server.synth_calls) == 3
    source_lane = result.metadata["optimization_search"]["strategies"][1]
    assert source_lane["strategy_contract_rejections"] == 1
    assert source_lane["strategy_contract_rejection_reasons"] == [
        "task-pipeline lane requires one DATAFLOW region"
    ]
    assert source_lane["measured_candidate"] is True


def test_submission_pipeline_honors_competition_configuration(
    monkeypatch,
) -> None:
    import agent.candidate.validator as validator

    called: dict[str, object] = {}

    def validate(state, code, *, stage, current_best=True):
        state.interface_ok = True
        return True

    def synth_gates(state, result, *, stage, current_best=True):
        state.synth_ok = True
        state.frequency_ok = True
        state.resource_ok = True
        state.best_synth_result = result
        state.last_verified_kernel = state.kernel
        return True

    def run_competition(self, state):
        called["max_candidates"] = self.max_candidates
        called["scoring_profile"] = self.scoring_profile
        return state

    monkeypatch.setattr(validator, "validate_candidate", validate)
    monkeypatch.setattr(validator, "record_synth_gates", synth_gates)
    monkeypatch.setattr(validator, "mark_fully_verified", lambda state: None)
    monkeypatch.setattr(DiverseOptimizationStage, "run", run_competition)

    baseline = SimpleNamespace(
        kind="synth",
        ok=True,
        report=_report(latency=100, resources=100),
        log="",
        phase="pass",
        elapsed_s=0.0,
        brief=lambda: "synth: PASS",
    )

    class PipelineServer:
        budget = SimpleNamespace(total=40)

        @staticmethod
        def csim(kernel):
            return SimpleNamespace(
                kind="csim",
                ok=True,
                report=None,
                log="",
                phase="pass",
                elapsed_s=0.0,
                brief=lambda: "csim: PASS",
            )

        @staticmethod
        def synth(kernel):
            return baseline

    config = AgentConfig(
        mode="optimize",
        competition=True,
        verbose=False,
        max_optimization_rounds=5,
        scoring_profile="balanced",
    )
    state = RunState(
        task=_task(),
        server=PipelineServer(),
        llm=object(),
        config=config,
        kernel=_STARTER,
    )

    _run_pipeline(
        state,
        config,
        state.task,
        state.server,
        state.llm,
    )

    assert called == {
        "max_candidates": 3,
        "scoring_profile": "balanced",
    }
