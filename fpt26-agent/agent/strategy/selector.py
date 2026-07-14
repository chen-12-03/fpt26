from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.core.candidate import Candidate


KEY_PPA_METRICS = ("latency_max", "ii_max", "estimated_clock_ns")
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
                selection_reason="no_candidate_strictly_improved_key_ppa_metric",
                comparisons=comparisons,
            )

        eligible.sort(key=lambda item: _selection_key(item[0]))
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
    strict_improvements: list[str] = []
    regressions: list[str] = []
    for key in (*KEY_PPA_METRICS, *RESOURCE_METRICS):
        base = _number(baseline_metrics.get(key))
        cand = _number(candidate_metrics.get(key))
        if base is None or cand is None:
            deltas[key] = None
            continue
        delta = cand - base
        deltas[key] = delta
        if key in KEY_PPA_METRICS and cand < base:
            strict_improvements.append(key)
        if key in {"latency_max", "ii_max"} and cand > base:
            regressions.append(key)

    if not strict_improvements:
        return {
            "deltas": deltas,
            "strict_improvements": [],
            "regressions": regressions,
            "improved": False,
            "reason": "no_strict_key_ppa_improvement",
        }
    if regressions:
        return {
            "deltas": deltas,
            "strict_improvements": strict_improvements,
            "regressions": regressions,
            "improved": False,
            "reason": "latency_or_ii_regressed",
        }
    return {
        "deltas": deltas,
        "strict_improvements": strict_improvements,
        "regressions": [],
        "improved": True,
        "reason": "strict_key_ppa_improvement:" + ",".join(strict_improvements),
    }


def _eligible(record: Any, comparison: dict[str, Any]) -> bool:
    checks = record.constraint_checks or {}
    return (
        record.status == "synth_pass"
        and comparison.get("improved") is True
        and checks.get("timing_valid") is True
        and checks.get("resource_limits_valid") is True
    )


def _selection_key(record: Any) -> tuple[Any, ...]:
    metrics = record.metrics
    return (
        _none_high(metrics.get("latency_max")),
        _none_high(metrics.get("ii_max")),
        _none_high(metrics.get("estimated_clock_ns")),
        _resource_sum(metrics),
        len(record.stage_results),
        record.candidate.candidate_id,
    )


def _resource_sum(metrics: dict[str, Any]) -> float:
    weights = {"lut": 1.0, "ff": 0.25, "dsp": 64.0, "bram": 64.0, "uram": 128.0}
    total = 0.0
    for key, weight in weights.items():
        value = _number(metrics.get(key))
        if value is not None:
            total += value * weight
    return total


def _none_high(value: Any) -> float:
    number = _number(value)
    return float("inf") if number is None else float(number)


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
