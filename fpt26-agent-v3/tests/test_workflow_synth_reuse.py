from types import SimpleNamespace

from agent.workflow import step_synth


def _successful_synth():
    report = SimpleNamespace(latency_worst=42, latency_avg=42)
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
        log=lambda message: None,
    )

    result = step_synth(state)

    assert server.calls == 1
    assert result.results[-1] is fresh
