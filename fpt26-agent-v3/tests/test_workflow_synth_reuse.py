from types import SimpleNamespace

from agent.workflow import step_synth


def _successful_synth():
    report = SimpleNamespace(
        latency_worst=42,
        latency_avg=42,
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
    return SimpleNamespace(
        kind="synth",
        ok=True,
        report=report,
        brief=lambda: "[synth] pass",
    )


def test_step_synth_reuses_adjacent_upstream_success() -> None:
    previous = _successful_synth()

    class Server:
        def synth(self, kernel):
            raise AssertionError("duplicate synthesis should not run")

    logs = []
    state = SimpleNamespace(
        csim_ok=True,
        synth_ok=True,
        kernel="kernel",
        server=Server(),
        results=[previous],
        best_latency=None,
        task=SimpleNamespace(clock_ns=5.0, requires_cosim=False),
        metadata={},
        interface_ok=True,
        frequency_ok=False,
        resource_ok=False,
        last_verified_kernel=None,
        log=logs.append,
    )

    result = step_synth(state)

    assert result.results == [previous]
    assert result.best_latency == 42
    assert "synth: reusing upstream successful synth report" in logs


def test_step_synth_runs_when_success_is_not_immediately_upstream() -> None:
    previous = _successful_synth()
    fresh = _successful_synth()

    class Server:
        def __init__(self) -> None:
            self.calls = 0

        def synth(self, kernel):
            self.calls += 1
            return fresh

    server = Server()
    state = SimpleNamespace(
        csim_ok=True,
        synth_ok=True,
        kernel="kernel",
        server=server,
        results=[previous, SimpleNamespace(kind="csim", ok=True)],
        best_latency=None,
        task=SimpleNamespace(clock_ns=5.0, requires_cosim=False),
        metadata={},
        interface_ok=True,
        frequency_ok=False,
        resource_ok=False,
        last_verified_kernel=None,
        log=lambda message: None,
    )

    result = step_synth(state)

    assert server.calls == 1
    assert result.results[-1] is fresh
