from types import SimpleNamespace

from agent.reporting import (
    _final_synth_info,
    _grading_synth_info,
    _reported_cosim_status,
)


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


def test_final_synth_info_uses_selected_kernel_not_score_anchor() -> None:
    state = SimpleNamespace(
        metadata={
            "best_synth_metrics": {
                "latency_worst": 515,
                "latency_avg": 515,
                "interval_max": 513,
                "clock_period_ns": 3.17,
                "resources": {"LUT": 211, "FF": 138, "DSP": 4},
                "loop_metrics": [{"pipeline_ii": 1}],
            }
        }
    )

    final = _final_synth_info(state)

    assert final["latency"] == 515
    assert final["top_interval"] == 513
    assert final["resources"]["LUT"] == 211


def test_evaluator_starter_and_candidate_synth_are_distinct() -> None:
    def result(latency: int, lut: int) -> SimpleNamespace:
        report = SimpleNamespace(
            latency_worst=latency,
            latency_avg=latency,
            interval_max=latency - 2,
            clock_period_ns=3.17,
            resources={"LUT": lut},
            loop_metrics=[],
        )
        return SimpleNamespace(ok=True, report=report)

    state = SimpleNamespace(
        metadata={
            "grading_results": [
                ("candidate_synth", result(515, 211)),
                ("starter_synth", result(1027, 156)),
            ]
        }
    )

    assert _grading_synth_info(state, "starter_synth")["latency"] == 1027
    assert _final_synth_info(state)["latency"] == 515
