from types import SimpleNamespace

from agent.reporting import _reported_cosim_status


def test_non_cosim_task_reports_na_instead_of_failure() -> None:
    state = SimpleNamespace(
        task=SimpleNamespace(requires_cosim=False),
        cosim_ok=False,
    )

    assert _reported_cosim_status(state) is None


def test_required_cosim_preserves_real_status() -> None:
    failed = SimpleNamespace(
        task=SimpleNamespace(requires_cosim=True),
        cosim_ok=False,
    )
    passed = SimpleNamespace(
        task=SimpleNamespace(requires_cosim=True),
        cosim_ok=True,
    )

    assert _reported_cosim_status(failed) is False
    assert _reported_cosim_status(passed) is True
