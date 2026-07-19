from types import SimpleNamespace

from agent.agents.repair import RepairAgent


def _result(kind, ok, brief, *, log="", phase="run"):
    return SimpleNamespace(
        kind=kind,
        ok=ok,
        log=log,
        phase=phase,
        report=None,
        brief=lambda: brief,
    )


def test_repair_reuses_adjacent_pipeline_csim_failure() -> None:
    failed = _result(
        "csim",
        False,
        "[csim] runtime_fail",
        log="projection mismatch",
    )
    passed = _result("csim", True, "[csim] pass")
    synthesized = _result("synth", True, "[synth] pass")
    synthesized.report = SimpleNamespace(
        latency_worst=10,
        latency_avg=10,
        clock_period_ns=5.0,
        resources={"LUT": 1, "FF": 1, "DSP": 0, "BRAM_18K": 0, "URAM": 0},
        available={
            "LUT": 100,
            "FF": 100,
            "DSP": 100,
            "BRAM_18K": 100,
            "URAM": 100,
        },
    )

    class Llm:
        def complete(self, system, prompt):
            return "int projection() { return 1; }"

    class Server:
        def __init__(self) -> None:
            self.csim_kernels = []
            self.synth_kernels = []

        def csim(self, kernel):
            self.csim_kernels.append(kernel)
            return passed

        def synth(self, kernel):
            self.synth_kernels.append(kernel)
            return synthesized

    task = SimpleNamespace(
        id="projection_bugfix",
        description="repair projection",
        top="projection",
        headers={},
        kernel_name="projection.cpp",
        requires_cosim=False,
        clock_ns=5.0,
    )
    server = Server()
    logs = []
    starter = "int projection() { return 0; }"
    state = SimpleNamespace(
        task=task,
        server=server,
        kernel=starter,
        results=[failed],
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
        log=logs.append,
    )

    result = RepairAgent(Llm(), max_attempts=3).run(state)

    assert result.csim_ok is True
    assert result.synth_ok is True
    assert server.csim_kernels == ["int projection() { return 1; }\n"]
    assert server.synth_kernels == ["int projection() { return 1; }\n"]
    assert len(result.results) == 3
    assert "repair: reusing pipeline csim failure" in logs
