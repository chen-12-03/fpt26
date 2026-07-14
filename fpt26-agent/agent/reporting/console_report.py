from __future__ import annotations

from typing import Any

from agent.competition_agent import AgentRunResult


def render_console_report(
    result: AgentRunResult,
    mode: str,
    scoring: dict[str, Any] | None = None,
    report: dict[str, Any] | None = None,
) -> str:
    context = result.task_context
    lines = [
        f"=== Task {context.task_id} [{context.task_type}] ===",
        f"    mode: {mode}",
        f"    target: {context.target_part} @ {context.requested_clock_ns} ns",
        _budget_line(result.budget),
        f"    initial condition: {result.initial_condition.condition}",
        "",
        "--- metered tool transcript ---",
    ]
    transcript = result.budget.get("transcript", []) if isinstance(result.budget, dict) else []
    if transcript:
        total = result.budget.get("total") if isinstance(result.budget, dict) else None
        for entry in transcript:
            spent = entry.get("spent")
            detail = entry.get("detail")
            number = entry.get("n")
            suffix = f"   [spent {spent}/{total}]" if spent is not None and total is not None else ""
            lines.append(f"  #{number:<2} {detail}{suffix}")
    else:
        lines.append("  no metered tool calls recorded")
    lines.append(f"  {_budget_summary(result.budget)}")
    lines.extend(
        [
            "",
            "--- agent result ---",
            f"  status                 : {result.status}",
            f"  selected candidate     : {result.selected_candidate_id}",
            f"  stop reason            : {result.stop_reason}",
            f"  repair                 : {result.repair_status}",
            f"  optimization           : {result.optimization_status}",
            f"  structural repair      : {result.structural_repair_status}",
            f"  final kernel sha256    : {result.final_kernel_sha256}",
            f"  run directory          : {result.run_directory}",
            f"  run manifest           : {result.run_manifest_path}",
        ]
    )
    if result.llm_usage:
        lines.append(f"  llm tokens             : {_llm_token_summary(result.llm_usage)}")
    lines.extend(["", "--- stage results ---"])
    for stage in result.stage_results:
        lines.append(f"  {stage.stage:<6} {stage.status:<14} {stage.summary}")
    if report is not None:
        paths = report.get("paths", {}) if isinstance(report.get("paths"), dict) else {}
        ppa = report.get("ppa", {}) if isinstance(report.get("ppa"), dict) else {}
        lines.extend(
            [
                "",
                "--- experimental report ---",
                f"  report json            : {paths.get('report_json')}",
                f"  report text            : {paths.get('report_txt')}",
                f"  ppa                    : clk={ppa.get('estimated_clock_ns')}ns latency={ppa.get('latency_max')} II={ppa.get('ii_max')}",
            ]
        )
    if scoring is not None:
        lines.extend(["", "--- official scorecard (hidden grading, uncharged) ---"])
        rendered = scoring.get("rendered")
        if isinstance(rendered, str) and rendered:
            lines.append(rendered)
        else:
            lines.append(f"  score: {scoring.get('score')}")
        paths = scoring.get("paths")
        if isinstance(paths, dict):
            lines.append(f"  scorecard json         : {paths.get('scorecard_json')}")
            lines.append(f"  scorecard text         : {paths.get('scorecard_txt')}")
    return "\n".join(lines)


def _budget_line(budget: dict[str, Any]) -> str:
    if not isinstance(budget, dict):
        return "    budget: unknown"
    total = budget.get("total")
    spent = budget.get("spent")
    remaining = budget.get("remaining")
    return f"    budget: {spent}/{total} credits spent, {remaining} remaining"


def _budget_summary(budget: dict[str, Any]) -> str:
    if not isinstance(budget, dict):
        return "budget summary unavailable"
    counts: dict[str, int] = {}
    for call in budget.get("calls", []) or []:
        kind = call.get("kind")
        if isinstance(kind, str):
            counts[kind] = counts.get(kind, 0) + 1
    breakdown = ", ".join(f"{kind}x{count}" for kind, count in sorted(counts.items())) or "none"
    return f"budget {budget.get('spent')}/{budget.get('total')} credits spent ({breakdown})"


def _llm_token_summary(llm_usage: dict[str, Any]) -> str:
    total = llm_usage.get("total_tokens")
    attempts = llm_usage.get("attempt_count")
    unknown = llm_usage.get("unknown_usage_count")
    return f"total={total}, attempts={attempts}, unknown_usage={unknown}"
