from types import SimpleNamespace

from agent.agents.base import AgentConfig
from agent.agents.structural import StructuralRepairAgent
from agent.workflow import build_pipeline, step_cosim


def test_structural_pipeline_runs_synth_before_required_cosim() -> None:
    task = SimpleNamespace(
        id="deadlock",
        type="structural",
        requires_cosim=True,
    )
    server = SimpleNamespace(budget=SimpleNamespace(total=80))

    pipeline = build_pipeline(
        config=AgentConfig(mode="structural"),
        task=task,
        server=server,
        llm=object(),
    )

    names = [step.name for step in pipeline.steps]
    assert names[:4] == ["init", "csim", "synth", "cosim"]


def test_step_cosim_propagates_embedded_synth_report() -> None:
    report = SimpleNamespace(latency_worst=135, latency_avg=135)
    cosim_result = SimpleNamespace(
        kind="cosim",
        ok=False,
        report=report,
        brief=lambda: "[cosim] timeout",
    )

    class Server:
        def cosim(self, kernel):
            return cosim_result

    state = SimpleNamespace(
        task=SimpleNamespace(requires_cosim=True),
        server=Server(),
        kernel="kernel",
        results=[],
        synth_ok=False,
        cosim_ok=False,
        best_latency=None,
        log=lambda message: None,
    )

    result = step_cosim(state)

    assert result.results == [cosim_result]
    assert result.synth_ok is True
    assert result.cosim_ok is False
    assert result.best_latency == 135


def test_step_cosim_fails_closed_when_result_payload_is_missing() -> None:
    result_without_payload = SimpleNamespace(
        kind="cosim",
        ok=True,
        report=None,
        cosim=None,
        brief=lambda: "[cosim] incomplete",
    )

    state = SimpleNamespace(
        task=SimpleNamespace(requires_cosim=True),
        server=SimpleNamespace(cosim=lambda kernel: result_without_payload),
        kernel="kernel",
        results=[],
        synth_ok=True,
        cosim_ok=True,
        best_latency=None,
        log=lambda message: None,
    )

    result = step_cosim(state)

    assert result.cosim_ok is False


def test_structural_repair_propagates_candidate_synth_latency() -> None:
    available = {
        "LUT": 100_000,
        "FF": 200_000,
        "DSP": 1_000,
        "BRAM_18K": 1_000,
        "URAM": 100,
    }
    baseline_report = SimpleNamespace(latency_worst=135, latency_avg=135)
    candidate_report = SimpleNamespace(
        latency_worst=68,
        latency_avg=68,
        clock_period_ns=5.0,
        resources={"LUT": 100, "FF": 100, "DSP": 1, "BRAM_18K": 0, "URAM": 0},
        available=available,
    )
    failed = SimpleNamespace(
        kind="cosim",
        ok=False,
        report=baseline_report,
        log="deadlock",
        brief=lambda: "[cosim] timeout",
    )
    passed_csim = SimpleNamespace(
        kind="cosim",
        ok=True,
        report=candidate_report,
        cosim=SimpleNamespace(passed=True),
        log="",
        brief=lambda: "[cosim] pass",
    )
    passed_csim_check = SimpleNamespace(
        kind="csim",
        ok=True,
        report=None,
        log="",
        brief=lambda: "[csim] pass",
    )

    class Llm:
        def complete(self, system, prompt):
            return "void top() { int fixed = 1; }"

    class Server:
        def csim(self, kernel):
            return passed_csim_check

        def synth(self, kernel):
            return SimpleNamespace(
                kind="synth",
                ok=True,
                report=candidate_report,
                log="",
                brief=lambda: "[synth] pass",
            )

        def cosim(self, kernel):
            return passed_csim

    state = SimpleNamespace(
        task=SimpleNamespace(
            id="deadlock",
            description="stream repair",
            top="top",
            headers={},
            kernel_name="top.cpp",
            requires_cosim=True,
            clock_ns=5.0,
        ),
        server=Server(),
        kernel="void top() {}",
        results=[failed],
        synth_ok=True,
        cosim_ok=False,
        best_latency=135,
        status="running",
        metadata={},
        interface_ok=True,
        csim_ok=True,
        frequency_ok=True,
        resource_ok=True,
        last_verified_kernel=None,
        log=lambda message: None,
    )

    result = StructuralRepairAgent(Llm(), max_attempts=2).run(state)

    assert result.cosim_ok is True
    assert result.synth_ok is True
    assert result.best_latency == 68
