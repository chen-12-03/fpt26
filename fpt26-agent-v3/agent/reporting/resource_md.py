"""Resource usage markdown report — writes a standalone ``resource_usage.md``
alongside ``run_report.json`` so humans can immediately see final area data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

RESOURCE_KEYS = ("LUT", "FF", "DSP", "BRAM_18K", "URAM")
_RESOURCE_LABELS = {
    "LUT": "LUT",
    "FF": "Flip-Flop",
    "DSP": "DSP",
    "BRAM_18K": "BRAM (18K)",
    "URAM": "URAM",
}


# ── helpers ────────────────────────────────────────────────────────────────

def _resources_from_state(state: Any) -> dict | None:
    """Extract the best final resource snapshot from *state*.

    Priority: scorecard candidate_resources > best_synth_metrics >
    synth_candidates[-1] > last synth result.
    """
    # 1. Scorecard (already graded)
    sc = getattr(state, "scorecard", None)
    if sc is not None and hasattr(sc, "candidate_resources"):
        r = sc.candidate_resources
        if r and any(r.get(k) for k in RESOURCE_KEYS):
            return dict(r)

    # 2. best_synth_metrics (metadata shortcut)
    best = state.metadata.get("best_synth_metrics") if hasattr(state, "metadata") else None
    if isinstance(best, dict):
        r = best.get("resources")
        if r and any(r.get(k) for k in RESOURCE_KEYS):
            return dict(r)

    # 3. Last synthesis result with a report
    for result in reversed(getattr(state, "results", [])):
        rpt = getattr(result, "report", None)
        if rpt is not None and hasattr(rpt, "resources"):
            r = rpt.resources
            if r and any(r.get(k) for k in RESOURCE_KEYS):
                return dict(r)

    return None


def _baseline_resources(state: Any) -> dict | None:
    """Extract the baseline/starter resource snapshot."""
    sc = getattr(state, "scorecard", None)
    if sc is not None and hasattr(sc, "baseline_resources"):
        r = sc.baseline_resources
        if r:
            return dict(r)

    # Fallback: first synth candidate marked as baseline
    candidates = state.metadata.get("synth_candidates", []) if hasattr(state, "metadata") else []
    for c in candidates:
        if isinstance(c, dict) and c.get("is_baseline"):
            r = c.get("resources")
            if r:
                return dict(r)

    # Last resort: first synth result
    for result in getattr(state, "results", []):
        if getattr(result, "kind", None) == "synth":
            rpt = getattr(result, "report", None)
            if rpt is not None and hasattr(rpt, "resources"):
                return dict(rpt.resources)

    return None


def _available_resources(state: Any) -> dict | None:
    """Extract device capacity totals."""
    # Scorecard first
    sc = getattr(state, "scorecard", None)
    if sc is not None and hasattr(sc, "available_resources"):
        r = sc.available_resources
        if r:
            return dict(r)

    # From any synthesis report
    for result in reversed(getattr(state, "results", [])):
        rpt = getattr(result, "report", None)
        if rpt is not None and hasattr(rpt, "available"):
            r = rpt.available
            if r and any(r.get(k) for k in RESOURCE_KEYS):
                return dict(r)

    return None


def _growth_by_resource(state: Any) -> dict | None:
    """Per-resource growth ratios."""
    sc = getattr(state, "scorecard", None)
    if sc is not None and hasattr(sc, "growth_by_resource"):
        g = sc.growth_by_resource
        if g:
            return dict(g)
    return None


def _best_latency(state: Any) -> int | None:
    return getattr(state, "best_latency", None)


def _final_clock_ns(state: Any) -> float | None:
    """Best final clock period."""
    candidates = state.metadata.get("synth_candidates", []) if hasattr(state, "metadata") else []
    for c in reversed(candidates):
        if isinstance(c, dict) and c.get("clock_ns"):
            return c["clock_ns"]
    res = _resources_from_state(state)
    # Try from last synth report
    for result in reversed(getattr(state, "results", [])):
        rpt = getattr(result, "report", None)
        if rpt is not None and hasattr(rpt, "clock_period_ns"):
            return rpt.clock_period_ns
    return getattr(state.task, "clock_ns", None)


# ── markdown builder ────────────────────────────────────────────────────────

def build_resource_md(state: Any) -> str:
    """Build resource usage markdown content from RunState.

    Returns a complete markdown string ready for writing to disk.
    """
    task = state.task
    final = _resources_from_state(state)
    baseline = _baseline_resources(state)
    available = _available_resources(state)
    growth = _growth_by_resource(state)
    best_lat = _best_latency(state)
    clock_ns = _final_clock_ns(state)

    # Determine status indicator
    status_icon = "✅" if state.status == "completed" else "❌"

    lines: list[str] = []
    lines.append(f"# Resource Usage — {task.id}")
    lines.append("")
    lines.append(f"**Status**: {status_icon} {state.status}  ")
    lines.append(f"**Task type**: {task.type}  ")
    lines.append(f"**Device**: {getattr(task, 'part', 'N/A')}  ")
    lines.append(f"**Target clock**: {getattr(task, 'clock_ns', 'N/A')} ns  ")
    if clock_ns is not None:
        freq = 1000.0 / clock_ns if clock_ns > 0 else 0
        lines.append(f"**Achieved clock**: {clock_ns:.3f} ns  ({freq:.1f} MHz)  ")
    lines.append(f"**Best latency**: {best_lat} cyc" if best_lat is not None else "**Best latency**: N/A")
    lines.append("")

    # ── Main resource table ─────────────────────────────────────────────
    if final is not None:
        lines.append("## Final Resource Usage")
        lines.append("")
        lines.append("| Resource | Used | Available | Utilization |")
        lines.append("|----------|------|-----------|-------------|")
        for key in RESOURCE_KEYS:
            used = final.get(key) or 0
            avail = (available or {}).get(key) or 0
            pct = f"{100.0 * used / avail:.2f}%" if avail else "N/A"
            used_s = f"{used:,}"
            avail_s = f"{avail:,}" if avail else "N/A"
            lines.append(f"| {_RESOURCE_LABELS.get(key, key)} | {used_s} | {avail_s} | {pct} |")
        lines.append("")

    # ── Resource growth from baseline ────────────────────────────────────
    if baseline is not None and final is not None and baseline != final:
        lines.append("## Resource Growth (Baseline → Final)")
        lines.append("")
        lines.append("| Resource | Baseline | Final | Δ | Growth |")
        lines.append("|----------|----------|-------|---|--------|")
        for key in RESOURCE_KEYS:
            bl = baseline.get(key) or 0
            fn = final.get(key) or 0
            delta = fn - bl
            sign = "+" if delta >= 0 else ""
            gr = (fn / bl - 1.0) * 100 if bl else float("inf")
            gr_s = f"{gr:+.1f}%" if bl and gr != float("inf") else "NEW"
            lines.append(f"| {_RESOURCE_LABELS.get(key, key)} | {bl:,} | {fn:,} | {sign}{delta:,} | {gr_s} |")
        lines.append("")

    # Scorecard growth ratios
    if growth is not None:
        lines.append("### Scorecard Growth Ratios")
        lines.append("")
        lines.append("| Resource | Multiplier |")
        lines.append("|----------|-----------|")
        for key in RESOURCE_KEYS:
            val = growth.get(key)
            if val is not None:
                lines.append(f"| {_RESOURCE_LABELS.get(key, key)} | {val:.4f}x |")
        lines.append("")

    # ── Synth candidate history ──────────────────────────────────────────
    candidates = state.metadata.get("synth_candidates", []) if hasattr(state, "metadata") else []
    if len(candidates) > 1:
        lines.append("## Candidate History")
        lines.append("")
        lines.append("| # | Latency | II | Clock | LUT | FF | DSP | BRAM | Decision |")
        lines.append("|---|---------|----|-------|-----|----|-----|------|----------|")
        for i, c in enumerate(candidates, 1):
            if not isinstance(c, dict):
                continue
            lat = c.get("latency", "?")
            ii = c.get("loop_ii") or c.get("top_interval", "?")
            clk = c.get("clock_ns", "?")
            r = c.get("resources") or {}
            decision = c.get("decision", "?")
            decision_icon = {
                "SELECTED": "🏆", "ACCEPTED": "✅",
                "BASELINE": "📊", "REJECTED": "❌",
            }.get(decision, "")
            lines.append(
                f"| {i} | {lat} | {ii} | {clk} | "
                f"{r.get('LUT', '?')} | {r.get('FF', '?')} | "
                f"{r.get('DSP', '?')} | {r.get('BRAM_18K', '?')} | "
                f"{decision_icon} {decision} |"
            )
        lines.append("")

    # ── Scoring summary ──────────────────────────────────────────────────
    sc = getattr(state, "scorecard", None)
    if sc is not None:
        lines.append("## Scoring")
        lines.append("")
        lines.append(f"- **Q_HW**: {getattr(sc, 'q_hw', 'N/A')}")
        lines.append(f"- **Q_Perf**: {getattr(sc, 'q_perf', 'N/A')}")
        lines.append(f"- **Q_Area**: {getattr(sc, 'q_area', 'N/A')}")
        lines.append(f"- **Bottleneck resource**: {getattr(sc, 'bottleneck_resource', 'N/A')}")
        lines.append(f"- **Area growth**: {getattr(sc, 'area_growth', 'N/A')}")
        lines.append(f"- **Score**: {getattr(sc, 'score', 'N/A')} / {getattr(sc, 'score_max', 'N/A')}")
        lines.append("")

    # ── Gates ─────────────────────────────────────────────────────────────
    lines.append("## Validation Gates")
    lines.append("")
    requires_cosim = getattr(task, "requires_cosim", False)
    gate_labels = [
        ("interface_ok", "Interface", False),
        ("csim_ok", "C Simulation", False),
        ("synth_ok", "Synthesis", False),
        ("frequency_ok", "Frequency (≥100 MHz)", False),
        ("resource_ok", "Resource Capacity", False),
        ("cosim_ok", "C/RTL Co-Simulation", True),
    ]
    for attr, label, is_cosim in gate_labels:
        val = getattr(state, attr, None)
        if is_cosim and not requires_cosim:
            lines.append(f"- ⬜ **{label}** — N/A (not required for this task type)")
        elif val is True:
            lines.append(f"- ✅ **{label}**")
        elif val is False:
            lines.append(f"- ❌ **{label}**")
        else:
            lines.append(f"- ⬜ **{label}**")
    lines.append("")

    # ── Token usage ──────────────────────────────────────────────────────
    llm = getattr(state, "llm", None)
    if llm is not None:
        lines.append("## Token Usage")
        lines.append("")
        model = getattr(llm, "model", None)
        if model:
            lines.append(f"- **Model**: {model}")
        token_usage = getattr(llm, "token_usage", None)
        snapshot = getattr(token_usage, "snapshot", None)
        usage = snapshot() if callable(snapshot) else None
        if isinstance(usage, dict):
            total = usage.get("total_tokens")
            prompt = usage.get("prompt_tokens")
            completion = usage.get("completion_tokens")
            requests = usage.get("request_count")
            failed = usage.get("failed_request_count", 0)
            if total is not None:
                lines.append(f"- **Total tokens**: {total:,}")
            if prompt is not None:
                lines.append(f"- **Prompt tokens**: {prompt:,}")
            if completion is not None:
                lines.append(f"- **Completion tokens**: {completion:,}")
            if requests is not None:
                lines.append(f"- **Requests**: {requests}  ")
            if failed:
                lines.append(f"- **Failed requests**: {failed}")
        lines.append("")

    # ── Budget ────────────────────────────────────────────────────────────
    budget = getattr(getattr(state, "server", None), "budget", None)
    if budget is not None:
        spent = getattr(budget, "spent", 0)
        total = getattr(budget, "total", 0)
        lines.append("## Budget")
        lines.append(f"- Spent: {spent} / {total} credits")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Generated by agent/reporting/resource_md.py*")

    return "\n".join(lines) + "\n"


def write_resource_summary_md(state: Any, output_dir: str | Path) -> Path:
    """Write ``resource_usage.md`` to *output_dir* next to ``run_report.json``.

    Args:
        state: Terminal :class:`RunState`.
        output_dir: The per-task output directory.

    Returns:
        Path to the written file.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    md_content = build_resource_md(state)
    target = out / "resource_usage.md"
    target.write_text(md_content, encoding="utf-8")
    return target
