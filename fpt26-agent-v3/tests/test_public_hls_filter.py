from __future__ import annotations

from tools.filter_public_hls_tasks import _classify_smoke_results


def test_filter_rejects_synth_ok_tasks_without_scoreable_metrics() -> None:
    smoke = {
        "scoreable": {
            "csim_ok": True,
            "synth_ok": True,
            "latency_worst": 128,
            "interval_max": 127,
        },
        "metric_missing": {
            "csim_ok": True,
            "synth_ok": True,
            "latency_worst": None,
            "interval_max": None,
        },
        "csim_failed": {
            "csim_ok": False,
            "synth_ok": False,
        },
    }

    passed, failed, metric_incomplete = _classify_smoke_results(
        smoke, allow_missing_score_metrics=False
    )

    assert passed == {"scoreable"}
    assert failed == {"metric_missing", "csim_failed"}
    assert metric_incomplete == {"metric_missing"}


def test_filter_legacy_mode_keeps_metric_incomplete_synth_smoke() -> None:
    smoke = {
        "metric_missing": {
            "csim_ok": True,
            "synth_ok": True,
            "latency_worst": None,
            "interval_max": None,
        },
    }

    passed, failed, metric_incomplete = _classify_smoke_results(
        smoke, allow_missing_score_metrics=True
    )

    assert passed == {"metric_missing"}
    assert failed == set()
    assert metric_incomplete == {"metric_missing"}


def test_filter_treats_old_smoke_latency_as_scoreable_when_interval_absent() -> None:
    smoke = {
        "old_smoke": {
            "csim_ok": True,
            "synth_ok": True,
            "latency_worst": 64,
        },
    }

    passed, failed, metric_incomplete = _classify_smoke_results(
        smoke, allow_missing_score_metrics=False
    )

    assert passed == {"old_smoke"}
    assert failed == set()
    assert metric_incomplete == set()
