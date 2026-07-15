from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.core.candidate import Candidate
from llm4hls.scoring import ACCEL_CAP


KEY_PPA_METRICS = ("latency_max",)
RESOURCE_METRICS = ("lut", "ff", "dsp", "bram", "uram")


@dataclass(frozen=True)
class SelectionResult:
    status: str
    selected_candidate: Candidate
    selected_kernel: str
    baseline_metrics: dict[str, Any]
    final_metrics: dict[str, Any]
    selection_reason: str
    comparisons: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "selected_candidate": self.selected_candidate.to_dict(),
            "selected_kernel": self.selected_kernel,
            "baseline_metrics": _json_value(self.baseline_metrics),
            "final_metrics": _json_value(self.final_metrics),
            "selection_reason": self.selection_reason,
            "comparisons": _json_value(self.comparisons),
        }


class Selector:
    def select(
        self,
        *,
        baseline_candidate: Candidate,
        baseline_kernel: str,
        baseline_metrics: dict[str, Any],
        candidate_records: list[Any],
    ) -> SelectionResult:
        comparisons: list[dict[str, Any]] = []
        eligible: list[tuple[Any, dict[str, Any]]] = []
        for record in candidate_records:
            comparison = compare_to_baseline(baseline_metrics, record.metrics)
            comparison["candidate_id"] = record.candidate.candidate_id if record.candidate is not None else None
            comparison["selection_eligible"] = _eligible(record, comparison)
            comparisons.append(comparison)
            if comparison["selection_eligible"]:
                eligible.append((record, comparison))

        if not eligible:
            return SelectionResult(
                status="no_improvement",
                selected_candidate=baseline_candidate,
                selected_kernel=baseline_kernel,
                baseline_metrics=baseline_metrics,
                final_metrics=baseline_metrics,
                selection_reason="no_candidate_official_latency_acceleration_improvement",
                comparisons=comparisons,
            )

        eligible.sort(key=lambda item: _selection_key(item[0], item[1]))
        selected, selected_comparison = eligible[0]
        return SelectionResult(
            status="improved",
            selected_candidate=selected.candidate,
            selected_kernel=selected.kernel_code,
            baseline_metrics=baseline_metrics,
            final_metrics=selected.metrics,
            selection_reason=selected_comparison["reason"],
            comparisons=comparisons,
        )


def compare_to_baseline(baseline_metrics: dict[str, Any], candidate_metrics: dict[str, Any]) -> dict[str, Any]:
    deltas: dict[str, Any] = {}
    base_latency = _latency_metric(baseline_metrics)
    candidate_latency = _latency_metric(candidate_metrics)
    acceleration = _acceleration(base_latency, candidate_latency)
    ppa_norm = min(acceleration, ACCEL_CAP) / ACCEL_CAP if acceleration is not None else None
    improved = acceleration is not None and acceleration > 1.0
    regressions: list[str] = ["latency_max"] if acceleration is not None and acceleration < 1.0 else []
    for key in (*KEY_PPA_METRICS, *RESOURCE_METRICS):
        base = _number(baseline_metrics.get(key))
        cand = _number(candidate_metrics.get(key))
        if base is None or cand is None:
            deltas[key] = None
            continue
        deltas[key] = cand - base

    official_proxy = {
        "policy": "llm4hls.scoring.grade latency acceleration proxy",
        "baseline_latency": base_latency,
        "candidate_latency": candidate_latency,
        "acceleration": acceleration,
        "accel_cap": ACCEL_CAP,
        "ppa_norm": ppa_norm,
    }
    if acceleration is None:
        return {
            "deltas": deltas,
            "official_score_proxy": official_proxy,
            "strict_improvements": [],
            "regressions": regressions,
            "improved": False,
            "reason": "latency_unavailable_for_official_acceleration",
        }
    if not improved:
        return {
            "deltas": deltas,
            "official_score_proxy": official_proxy,
            "strict_improvements": [],
            "regressions": regressions,
            "improved": False,
            "reason": "no_official_latency_acceleration_improvement",
        }
    return {
        "deltas": deltas,
        "official_score_proxy": official_proxy,
        "strict_improvements": ["latency_max"],
        "regressions": [],
        "improved": True,
        "reason": "official_latency_acceleration_improved",
    }


def _eligible(record: Any, comparison: dict[str, Any]) -> bool:
    checks = record.constraint_checks or {}
    return (
        record.status == "synth_pass"
        and comparison.get("improved") is True
        and checks.get("timing_valid") is True
        and checks.get("resource_limits_valid") is True
    )


def _selection_key(record: Any, comparison: dict[str, Any]) -> tuple[Any, ...]:
    proxy = comparison.get("official_score_proxy")
    proxy = proxy if isinstance(proxy, dict) else {}
    return (
        -_none_low(proxy.get("acceleration")),
        _none_high(proxy.get("candidate_latency")),
        len(record.stage_results),
        record.candidate.candidate_id,
    )


def _latency_metric(metrics: dict[str, Any]) -> float | None:
    for key in ("latency_max", "latency_avg", "latency_min"):
        value = _number(metrics.get(key))
        if value is not None:
            return value
    return None


def _acceleration(base_latency: float | None, candidate_latency: float | None) -> float | None:
    if base_latency is None or candidate_latency is None or candidate_latency <= 0:
        return None
    return base_latency / candidate_latency


def _none_high(value: Any) -> float:
    number = _number(value)
    return float("inf") if number is None else float(number)


def _none_low(value: Any) -> float:
    number = _number(value)
    return float("-inf") if number is None else float(number)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
