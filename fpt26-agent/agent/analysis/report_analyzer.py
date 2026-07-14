from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.core.task_context import TaskContext
from agent.execution.result_adapter import UnifiedToolResult


PPA_KEYS = (
    "estimated_clock_ns",
    "latency_min",
    "latency_max",
    "ii_min",
    "ii_max",
    "lut",
    "ff",
    "dsp",
    "bram",
    "uram",
)


@dataclass(frozen=True)
class ReportAnalysis:
    estimated_clock_ns: float | None
    latency_min: int | None
    latency_max: int | None
    ii_min: int | None
    ii_max: int | None
    lut: int | None
    ff: int | None
    dsp: int | None
    bram: int | None
    uram: int | None
    timing_valid: bool | None
    resource_limits_valid: bool | None
    bottleneck_hints: list[str]
    constraint_checks: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimated_clock_ns": self.estimated_clock_ns,
            "latency_min": self.latency_min,
            "latency_max": self.latency_max,
            "ii_min": self.ii_min,
            "ii_max": self.ii_max,
            "lut": self.lut,
            "ff": self.ff,
            "dsp": self.dsp,
            "bram": self.bram,
            "uram": self.uram,
            "timing_valid": self.timing_valid,
            "resource_limits_valid": self.resource_limits_valid,
            "bottleneck_hints": list(self.bottleneck_hints),
            "constraint_checks": _json_value(self.constraint_checks),
        }

    @property
    def metrics(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in PPA_KEYS}


class ReportAnalyzer:
    def analyze(
        self,
        synth_result: UnifiedToolResult,
        task_context: TaskContext,
        *,
        kernel_code: str | None = None,
    ) -> ReportAnalysis:
        metrics = synth_result.metrics or {}
        normalized = {key: _number(metrics.get(key)) for key in PPA_KEYS}
        effective_clock_limit = _effective_clock_limit(task_context.requested_clock_ns)
        timing_valid = _timing_valid(normalized["estimated_clock_ns"], effective_clock_limit)
        resource_limits_valid, resource_checks = _resource_checks(normalized, task_context.resource_limits)
        bottleneck_hints = _bottleneck_hints(normalized, resource_checks, kernel_code)

        return ReportAnalysis(
            estimated_clock_ns=_float_or_none(normalized["estimated_clock_ns"]),
            latency_min=_int_or_none(normalized["latency_min"]),
            latency_max=_int_or_none(normalized["latency_max"]),
            ii_min=_int_or_none(normalized["ii_min"]),
            ii_max=_int_or_none(normalized["ii_max"]),
            lut=_int_or_none(normalized["lut"]),
            ff=_int_or_none(normalized["ff"]),
            dsp=_int_or_none(normalized["dsp"]),
            bram=_int_or_none(normalized["bram"]),
            uram=_int_or_none(normalized["uram"]),
            timing_valid=timing_valid,
            resource_limits_valid=resource_limits_valid,
            bottleneck_hints=bottleneck_hints,
            constraint_checks={
                "requested_clock_ns": task_context.requested_clock_ns,
                "competition_clock_limit_ns": 10.0,
                "effective_clock_limit_ns": effective_clock_limit,
                "task_timing_valid": _timing_valid(normalized["estimated_clock_ns"], task_context.requested_clock_ns),
                "competition_timing_valid": _timing_valid(normalized["estimated_clock_ns"], 10.0),
                "timing_valid": timing_valid,
                "resource_limits": task_context.resource_limits,
                "resource_checks": resource_checks,
                "resource_limits_valid": resource_limits_valid,
            },
        )


def _effective_clock_limit(requested_clock_ns: float | None) -> float:
    if requested_clock_ns is None:
        return 10.0
    return min(float(requested_clock_ns), 10.0)


def _timing_valid(clock_ns: float | int | None, limit_ns: float | None) -> bool | None:
    if clock_ns is None or limit_ns is None:
        return None
    return float(clock_ns) <= float(limit_ns)


def _resource_checks(
    metrics: dict[str, float | int | None],
    limits: dict[str, Any] | None,
) -> tuple[bool | None, dict[str, Any]]:
    if not limits:
        return True, {}
    checks: dict[str, Any] = {}
    missing = False
    failed = False
    for limit_key, metric_key in (
        ("max_lut", "lut"),
        ("max_ff", "ff"),
        ("max_dsp", "dsp"),
        ("max_bram", "bram"),
        ("max_uram", "uram"),
    ):
        limit = limits.get(limit_key)
        if limit is None:
            checks[metric_key] = {"limit": None, "value": metrics.get(metric_key), "valid": None}
            continue
        value = metrics.get(metric_key)
        if value is None:
            valid = None
            missing = True
        else:
            valid = float(value) <= float(limit)
            failed = failed or not valid
        checks[metric_key] = {"limit": limit, "value": value, "valid": valid}
    if failed:
        return False, checks
    if missing:
        return None, checks
    return True, checks


def _bottleneck_hints(
    metrics: dict[str, float | int | None],
    resource_checks: dict[str, Any],
    kernel_code: str | None,
) -> list[str]:
    hints: list[str] = []
    ii_max = metrics.get("ii_max")
    if ii_max is not None and float(ii_max) > 1:
        hints.append("high_ii")
    if kernel_code is not None and "for" in kernel_code and "#pragma HLS PIPELINE" not in kernel_code:
        hints.append("unpipelined_loop")
    if _has_resource_headroom(resource_checks):
        hints.append("resource_headroom")
    return hints


def _has_resource_headroom(resource_checks: dict[str, Any]) -> bool:
    if not resource_checks:
        return False
    checked = False
    for data in resource_checks.values():
        limit = data.get("limit") if isinstance(data, dict) else None
        value = data.get("value") if isinstance(data, dict) else None
        if limit is None or value is None:
            continue
        checked = True
        if float(value) > float(limit) * 0.7:
            return False
    return checked


def _number(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _int_or_none(value: float | int | None) -> int | None:
    return int(value) if value is not None else None


def _float_or_none(value: float | int | None) -> float | None:
    return float(value) if value is not None else None


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
