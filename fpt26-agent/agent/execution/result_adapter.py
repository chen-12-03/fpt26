from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SYNTH_METRIC_KEYS = (
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


def _json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _empty_synth_metrics() -> dict[str, Any]:
    return {key: None for key in SYNTH_METRIC_KEYS}


@dataclass(frozen=True)
class UnifiedToolResult:
    stage: str
    status: str
    return_code: int | None
    elapsed_seconds: float | None
    summary: str
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    budget_before: int | None = None
    budget_after: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "return_code": self.return_code,
            "elapsed_seconds": self.elapsed_seconds,
            "summary": self.summary,
            "metrics": _json_value(self.metrics),
            "artifacts": _json_value(self.artifacts),
            "budget_before": self.budget_before,
            "budget_after": self.budget_after,
        }


def adapt_tool_result(
    stage: str,
    tool_result: Any,
    *,
    artifacts: dict[str, Any] | None = None,
    budget_before: int | None,
    budget_after: int | None,
) -> UnifiedToolResult:
    phase = getattr(tool_result, "phase", None)
    ok = bool(getattr(tool_result, "ok", False))
    status = "pass" if ok else str(phase or "failed")
    if phase == "timeout":
        status = "timeout"

    metrics: dict[str, Any] = {}
    if stage == "synth":
        metrics = _synth_metrics(getattr(tool_result, "report", None))
    elif stage == "cosim":
        metrics = _cosim_metrics(getattr(tool_result, "cosim", None))

    brief = getattr(tool_result, "brief", None)
    summary = brief() if callable(brief) else f"[{stage}] {status}"

    return UnifiedToolResult(
        stage=stage,
        status=status,
        return_code=getattr(tool_result, "return_code", None),
        elapsed_seconds=getattr(tool_result, "elapsed_s", None),
        summary=summary,
        metrics=metrics,
        artifacts=artifacts or {},
        budget_before=budget_before,
        budget_after=budget_after,
    )


def exception_result(
    stage: str,
    status: str,
    exc: BaseException,
    *,
    artifacts: dict[str, Any] | None = None,
    budget_before: int | None,
    budget_after: int | None,
) -> UnifiedToolResult:
    return UnifiedToolResult(
        stage=stage,
        status=status,
        return_code=None,
        elapsed_seconds=None,
        summary=f"{type(exc).__name__}: {exc}",
        metrics=_empty_synth_metrics() if stage == "synth" else {},
        artifacts={
            **(artifacts or {}),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        },
        budget_before=budget_before,
        budget_after=budget_after,
    )


def _synth_metrics(report: Any) -> dict[str, Any]:
    metrics = _empty_synth_metrics()
    if report is None:
        return metrics
    resources = getattr(report, "resources", None) or {}
    metrics.update(
        {
            "estimated_clock_ns": getattr(report, "clock_period_ns", None),
            "latency_min": getattr(report, "latency_best", None),
            "latency_max": getattr(report, "latency_worst", None),
            "ii_min": getattr(report, "interval_min", None),
            "ii_max": getattr(report, "interval_max", None),
            "lut": resources.get("LUT"),
            "ff": resources.get("FF"),
            "dsp": resources.get("DSP"),
            "bram": resources.get("BRAM_18K"),
            "uram": resources.get("URAM"),
        }
    )
    return metrics


def _cosim_metrics(cosim: Any) -> dict[str, Any]:
    if cosim is None:
        return {"latency_min": None, "latency_avg": None, "latency_max": None}
    return {
        "latency_min": getattr(cosim, "latency_min", None),
        "latency_avg": getattr(cosim, "latency_avg", None),
        "latency_max": getattr(cosim, "latency_max", None),
    }
