"""Compact terminal report used by the agent CLI."""

from __future__ import annotations

import textwrap
from typing import Any

from agent.console_ui import Color, console_width, paint, strip_ansi


def _value(value: Any, suffix: str = "") -> str:
    return "N/A" if value is None else f"{value}{suffix}"


def _resources(values: dict | None) -> str:
    values = values or {}
    return "  ".join(f"{key}={values.get(key, 0)}" for key in ("LUT", "FF", "DSP", "BRAM_18K", "URAM"))


class _Panel:
    def __init__(self, title: str, status: str) -> None:
        self.width = console_width()
        status_color = Color.GREEN if status == "PASS" else Color.RED
        title_text = f" FPT26 · {title} "
        status_text = f" {status} "
        fill = max(self.width - len(title_text) - len(status_text) - 2, 1)
        print()
        print(
            paint("╭" + title_text, Color.BOLD, Color.CYAN)
            + paint("─" * fill, Color.CYAN)
            + paint(status_text, Color.BOLD, status_color)
            + paint("╮", Color.CYAN)
        )

    def section(self, title: str) -> None:
        label = f" {title.upper()} "
        print(paint("├─" + label + "─" * max(self.width - len(label) - 3, 0) + "┤", Color.CYAN))

    def row(self, text: str = "", *, color: str | None = None) -> None:
        available = self.width - 4
        lines = textwrap.wrap(
            strip_ansi(text), width=available, break_long_words=False, break_on_hyphens=False
        ) or [""]
        for line in lines:
            content = paint(line, color) if color else line
            print("│ " + content + " " * max(available - len(line), 0) + " │")

    def key(self, label: str, value: Any, *, value_color: str | None = None) -> None:
        raw_label = f"{label:<13}"
        raw_value = str(value)
        visible = raw_label + raw_value
        if len(visible) <= self.width - 4:
            print(
                "│ "
                + paint(raw_label, Color.BOLD, Color.CYAN)
                + (paint(raw_value, value_color) if value_color else raw_value)
                + " " * max(self.width - 4 - len(visible), 0)
                + " │"
            )
        else:
            self.row(visible)

    def close(self) -> None:
        print(paint("╰" + "─" * (self.width - 2) + "╯", Color.CYAN))
        print()


def _synth_entries(state: Any) -> tuple[dict | None, list[dict], dict | None]:
    from agent.reporting.metrics import _final_synth_info, _grading_synth_info, _synth_info

    structured = getattr(state, "metadata", {}).get("synth_candidates", [])
    baseline = next((dict(item) for item in structured if item.get("is_baseline") or item.get("round") == 0), None)
    candidates = [dict(item) for item in structured if not item.get("is_baseline") and item.get("round") != 0]

    graded = _grading_synth_info(state, "starter_synth")
    if graded is not None:
        baseline = dict(graded, round=0, is_baseline=True, decision="BASELINE")
    if baseline is None:
        for result in state.results:
            info = _synth_info(result)
            if getattr(result, "kind", None) == "synth" and info is not None:
                baseline = dict(info, round=0, is_baseline=True, decision="BASELINE")
                break
    return baseline, candidates, _final_synth_info(state)


def _gate_text(value: bool | None) -> str:
    if value is None:
        return "N/A"
    return "PASS" if value else "FAIL"


def print_evaluation(state: Any) -> None:
    """Print a readable run summary without fixed-width overflowing cells."""
    from agent.reporting.metrics import _compute_derived, _llm_summary, _reported_cosim_status

    derived = _compute_derived(state)
    budget = state.server.budget
    spent = getattr(budget, "spent", "?")
    total = getattr(budget, "total", "?")
    breakdown = derived["tool_breakdown"]
    passed = state.status == "completed"
    panel = _Panel("RUN COMPLETE", "PASS" if passed else "FAIL")

    panel.key("Task", state.task.id)
    panel.key("Status", state.status.upper(), value_color=Color.GREEN if passed else Color.RED)
    if getattr(state, "stop_reason", ""):
        panel.key("Reason", state.stop_reason, value_color=Color.RED)

    panel.section("Validation")
    gates = (
        ("C simulation", state.csim_ok),
        ("Synthesis", state.synth_ok),
        ("Co-simulation", _reported_cosim_status(state)),
    )
    gate_line = "   ".join(f"{name}: {_gate_text(value)}" for name, value in gates)
    panel.row(gate_line, color=Color.GREEN if passed else None)

    baseline, candidates, final = _synth_entries(state)
    if baseline or final:
        baseline = baseline or {}
        final = final or baseline
        panel.section("QoR summary")
        panel.row(f"{'Metric':<18}{'Starter':<22}{'Final best':<22}{'Change'}", color=Color.BOLD)
        metric_rows = (
            ("Latency", _value(baseline.get("latency"), " cyc"), _value(final.get("latency"), " cyc")),
            ("Top interval", _value(baseline.get("top_interval"), " cyc"), _value(final.get("top_interval"), " cyc")),
            ("Loop II", _value(baseline.get("loop_ii")), _value(final.get("loop_ii"))),
            ("Clock", _value(baseline.get("clock_ns"), " ns"), _value(final.get("clock_ns"), " ns")),
        )
        for label, starter, best in metric_rows:
            change = "=" if starter == best else f"{starter} → {best}"
            panel.row(f"{label:<18}{starter:<22}{best:<22}{change}")
        panel.row("")
        panel.key("Starter area", _resources(baseline.get("resources")))
        panel.key("Final area", _resources(final.get("resources")))

    scorecard = getattr(state, "scorecard", None)
    panel.section("Score")
    if scorecard is None:
        message = (
            "Submission acceptance passed; the formal score is produced by the evaluator."
            if passed
            else "Formal score unavailable because the submission did not pass acceptance."
        )
        panel.row(message, color=Color.DIM)
    else:
        score_max = getattr(scorecard, "score_max", getattr(state.task, "difficulty", None))
        score_text = f"{scorecard.score:.2f}" if score_max is None else f"{scorecard.score:.2f} / {score_max:.0f}"
        panel.key("Score", score_text, value_color=Color.GREEN if passed else Color.RED)
        if hasattr(scorecard, "q_hw"):
            panel.key("Q_HW", f"{scorecard.q_hw:.4f}")
        if hasattr(scorecard, "efficiency"):
            panel.key("Efficiency", f"{scorecard.efficiency:.4f}")

    synth_indices = [entry.n for entry in state.server.transcript if entry.kind == "synth"]
    if baseline or candidates:
        panel.section("Candidates")
        all_candidates: list[tuple[int | str, dict, str]] = []
        if baseline:
            final_is_baseline = bool(final) and baseline.get("latency") == final.get("latency") and baseline.get("resources") == final.get("resources")
            all_candidates.append((synth_indices[0] if synth_indices else 1, baseline, "SELECTED" if final_is_baseline else "BASELINE"))
        for index, candidate in enumerate(candidates, 1):
            call = synth_indices[index] if index < len(synth_indices) else candidate.get("round", index)
            all_candidates.append((call, candidate, candidate.get("decision", "REJECTED")))
        for call, candidate, decision in all_candidates:
            tone = Color.GREEN if decision in {"SELECTED", "ACCEPTED"} else (Color.RED if decision == "REJECTED" else Color.YELLOW)
            panel.row(
                f"#{call}  {decision:<10}  latency={_value(candidate.get('latency'), ' cyc')}  "
                f"II={_value(candidate.get('loop_ii'))}  clock={_value(candidate.get('clock_ns'), ' ns')}",
                color=tone,
            )
            panel.row(f"    {_resources(candidate.get('resources'))}", color=Color.DIM)

    panel.section("Usage")
    panel.key("Budget", f"{spent}/{total} credits ({derived['budget_utilization'] * 100:.0f}%)")
    panel.key("Elapsed", f"{derived['wall_time_seconds']:.1f}s")
    panel.key("Tool calls", f"csim={breakdown.get('csim', 0)}  synth={breakdown.get('synth', 0)}  cosim={breakdown.get('cosim', 0)}")
    llm = _llm_summary(state)
    if llm:
        panel.key("Model", llm.get("model") or llm.get("client") or "N/A")
        usage = llm.get("token_usage")
        if isinstance(usage, dict):
            panel.key("Tokens", f"{usage.get('total_tokens', 0):,} total  ({usage.get('request_count', 0)} requests)")
    panel.close()


def print_transcript(state: Any) -> None:
    """Print a compact tool-call audit; full logs live in the JSON report."""
    total = getattr(state.server.budget, "total", "?")
    for entry in state.server.transcript:
        print(f"  #{entry.n:02d}  {entry.kind.upper():<7}  spent {entry.spent}/{total}")
