"""Pure diagnostic functions — analyse synth report output.

These functions take tool results as input and return strings/dicts.
They do NOT call LLMs, modify state, or write artifacts.
"""

from __future__ import annotations

from typing import Any
from agent.analysis.synth_diagnostics import extract_ii_resource_limits


def _latency(r: Any) -> int | None:
    """Extract worst-case latency from a synthesis ToolResult."""
    if not r or not r.report:
        return None
    return r.report.latency_worst or r.report.latency_avg


def _report_latency(report: Any) -> int | None:
    """Extract worst-case latency from a synthesis report object."""
    if report is None:
        return None
    if report.latency_worst is not None:
        return report.latency_worst
    return report.latency_avg


def _report(r: Any) -> str:
    """Format a synthesis result as a concise one-line summary."""
    if not r or not r.report:
        return "no report"
    rp = r.report
    loop_text = ", ".join(
        f"{loop.get('name', '?')}(trip={loop.get('trip_count')},"
        f"lat={loop.get('latency')},II={loop.get('pipeline_ii')})"
        for loop in (getattr(rp, "loop_metrics", None) or [])
    ) or "none"
    return (
        f"Clk={rp.clock_period_ns}ns Lat={rp.latency_worst or '?'} "
        f"TopInterval={rp.interval_max or '?'} "
        f"Pipeline={getattr(rp, 'pipeline_type', None) or '?'} "
        f"Loops=[{loop_text}] "
        f"LUT={rp.resources.get('LUT','?')} FF={rp.resources.get('FF','?')} "
        f"DSP={rp.resources.get('DSP','?')} BRAM={rp.resources.get('BRAM_18K','?')}"
    )


def _diagnose(r: Any) -> str:
    """Report-driven bottleneck diagnosis from synthesis report metrics."""
    if not r or not r.report:
        return "No synth data available. Run synthesis first."

    rp = r.report
    issues: list[str] = []

    top_interval = rp.interval_max or 0
    loop_metrics = getattr(rp, "loop_metrics", None) or []
    loop_iis = [
        loop.get("pipeline_ii")
        for loop in loop_metrics
        if loop.get("pipeline_ii") is not None
    ]
    violating_loops = [ii for ii in loop_iis if ii > 1]
    if violating_loops:
        ii_resource_limits = extract_ii_resource_limits(getattr(r, "log", "") or "")
        if ii_resource_limits:
            issues.extend(
                f"Measured loop PipelineII={max(violating_loops)}>1. {limit.summary()}"
                for limit in ii_resource_limits[:3]
            )
        else:
            issues.append(
                f"Measured loop PipelineII={max(violating_loops)}>1 — classify the "
                "reported loop violation (recurrence, timing, or memory ports) before "
                "adding a matching directive."
            )
        issues.append(
            "See knowledge pattern 'Pipeline II Violation Resolution' for step-by-step "
            "II fix guidance (memory port → ARRAY_PARTITION, data dependency → restructure, "
            "timing → reduce combinational path)."
        )
    elif loop_iis:
        issues.append(
            f"Measured loop PipelineII={max(loop_iis)} is already optimal. "
            f"TopInterval={top_interval} is the function transaction interval, "
            "not evidence of a loop-II or memory-port problem."
        )
    elif top_interval > 1:
        issues.append(
            f"TopInterval={top_interval} is function-level; loop PipelineII is "
            "unavailable (the loop hierarchy may have been flattened/unrolled). "
            "Do not infer memory-port pressure from TopInterval alone."
        )

    if hasattr(rp, 'timing_slack_ns') and rp.timing_slack_ns is not None:
        slack = rp.timing_slack_ns
        if slack < 0:
            issues.append(f"Measured negative timing slack ({slack:.2f}ns).")

    if not issues:
        issues.append(
            "No evidence-backed bottleneck cause is available. Do not select a "
            "directive until report/source evidence identifies a target."
        )
    return "\n".join(f"• {i}" for i in issues)


def _resource_delta(history: list[dict]) -> str:
    """Summarize resource trend across rounds."""
    if len(history) < 2:
        return ""
    first = history[0]
    last = history[-1]
    lines = ["Resource trend (first→last):"]
    for key in ("LUT", "FF", "DSP", "BRAM_18K", "URAM"):
        fv, lv = first.get(key, 0) or 0, last.get(key, 0) or 0
        if fv > 0:
            change = (lv - fv) / fv * 100
            arrow = "↑" if change > 5 else ("↓" if change < -5 else "→")
            lines.append(f"  {key}: {fv} → {lv} ({change:+.0f}% {arrow})")
        elif lv > 0:
            lines.append(f"  {key}: 0 → {lv} (NEW)")
    lines.append(
        "Schema 11 scores the sum of each resource count divided by its "
        "device capacity; per-type changes above are diagnostics, not the "
        "area objective."
    )
    lines.append(
        "Goal: improve effective latency and/or reduce aggregate "
        "capacity-normalized resource pressure."
    )
    return "\n".join(lines)
