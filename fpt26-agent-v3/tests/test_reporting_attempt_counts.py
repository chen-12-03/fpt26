"""Attempt metrics must count actual tool calls, including all-failure runs."""

from types import SimpleNamespace

from agent.reporting import _attempts_to_pass, _compute_derived


def _result(kind: str, ok: bool) -> SimpleNamespace:
    return SimpleNamespace(kind=kind, ok=ok, elapsed_s=0.0)


def test_empty_results_have_zero_attempts() -> None:
    assert _attempts_to_pass([], "csim") == 0


def test_single_failure_is_one_attempt_not_two() -> None:
    assert _attempts_to_pass([_result("csim", False)], "csim") == 1


def test_counts_through_first_pass_and_ignores_other_tool_kinds() -> None:
    results = [
        _result("synth", True),
        _result("csim", False),
        _result("csim", False),
        _result("csim", True),
        _result("csim", False),
    ]

    assert _attempts_to_pass(results, "csim") == 3


def test_all_failures_count_every_real_call() -> None:
    results = [_result("cosim", False), _result("cosim", False)]

    assert _attempts_to_pass(results, "cosim") == 2


def test_derived_metrics_match_transcript_call_counts_for_failed_run() -> None:
    state = SimpleNamespace(
        results=[_result("csim", False)],
        server=SimpleNamespace(budget=SimpleNamespace(spent=1, total=20)),
        scorecard=None,
    )

    metrics = _compute_derived(state)

    assert metrics["tool_breakdown"] == {"csim": 1}
    assert metrics["csim_attempts"] == 1
    assert metrics["cosim_attempts"] == 0
