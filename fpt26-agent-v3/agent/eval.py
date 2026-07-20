#!/usr/bin/env python3
"""Cross-run evaluation tool for FPT26 agent v3.

Reads ``run_report.json`` files from an output root and produces a
comparison table with per-task and aggregate metrics.

Usage::

    python -m agent.eval                          # reads from default runs/
    python -m agent.eval --output-root runs/v2    # specific output dir
    python -m agent.eval --json                   # machine-readable output
    python -m agent.eval --detail                 # per-metric breakdown per task

Scoring formula reference (from llm4hls/scoring.py)::

    score = difficulty × (0.5×correct + 0.2×synthesizable + 0.3×ppa_norm)
    ppa_norm = min(Acceleration, 8.0) / 8.0
    max_score = difficulty × 1.0
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def find_reports(root: Path) -> list[Path]:
    """Find all run_report.json files under root, sorted by task id."""
    reports = sorted(root.rglob("run_report.json"))
    if not reports:
        print(f"No run_report.json files found under {root}", file=sys.stderr)
        sys.exit(1)
    return reports


def load_reports(paths: list[Path]) -> list[dict[str, Any]]:
    """Load and return all reports, skipping unreadable files."""
    reports: list[dict[str, Any]] = []
    for p in paths:
        try:
            reports.append(json.loads(p.read_text()))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  [warn] skipping {p}: {exc}", file=sys.stderr)
    return reports


def aggregate(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate metrics across all tasks (legacy compat wrapper).

    Delegates to ``agent.reporting.aggregate.collect_reports`` via in-memory
    reports.  For direct root-disk scanning use the V3 aggregator directly.
    """
    from agent.reporting.aggregate import RunSummary, _is_v3_report, _extract_v3_task

    summary = RunSummary()
    seen: set[str] = set()

    for idx, r in enumerate(reports):
        path = f"<memory-{idx}>"
        sc = r.get("scoring") or {}
        if _is_v3_report(sc):
            try:
                task = _extract_v3_task(r, path)
            except ValueError:
                continue
        else:
            # Legacy report: extract basic fields
            from agent.reporting.aggregate import TaskAggregate
            task = TaskAggregate(
                task_id=str(r.get("task_id", "")),
                task_type=str(r.get("task_type", "")),
                status=str(r.get("status", "")),
                score=float(sc.get("score", 0)),
                score_max=100.0,
                score_pct=round(float(sc.get("score", 0)) / 100.0 * 100.0, 1),
                report_path=path,
            )

        if task.task_id and task.task_id in seen:
            continue
        if task.task_id:
            seen.add(task.task_id)

        summary.tasks.append(task)
        summary.task_count += 1
        status = task.status
        if status == "completed":
            summary.completed += 1
        elif status == "budget_exceeded":
            summary.budget_exceeded += 1
        elif status == "infrastructure_error":
            summary.infra_error += 1
        else:
            summary.failed += 1

        summary.total_score += task.score
        summary.total_score_max += task.score_max
        summary.total_spent += task.credits_spent
        summary.total_budget += task.credits_total
        summary.total_wall_s += task.wall_time_s
        summary.total_grading_s += task.grading_time_s

    return {
        "task_count": summary.task_count,
        "total_score": round(summary.total_score, 3),
        "total_max": summary.total_score_max,
        "score_pct": round(summary.score_pct, 1),
        "total_spent": summary.total_spent,
        "total_budget": summary.total_budget,
        "budget_utilization": round(summary.budget_utilization_pct, 1),
        "total_wall_seconds": round(summary.total_wall_s, 0),
        "functional_pass_rate": summary.functional_pass_rate,
        "optimization_rate": f"{summary.completed}/{summary.task_count}",
        "budget_efficiency": (
            round(summary.total_score / max(summary.total_spent, 1), 4)
        ),
        "errors": summary.errors,
    }


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def _bar(value: float, max_val: float, width: int = 20) -> str:
    """ASCII progress bar."""
    if max_val <= 0:
        return ""
    filled = int(value / max_val * width)
    return "█" * filled + "░" * (width - filled)


def print_table(reports: list[dict[str, Any]], agg: dict[str, Any]) -> None:
    """Pretty-print a per-task comparison table."""
    header = f"{'Task':<28} {'Type':<10} {'Score':>8} {'Max':>5} {'%':>6} {'Accel':>7} {'Budget':>10} {'Wall':>7} {'Tools(c/sim/cos)':>16}"
    sep = "─" * len(header)

    print(f"\n{sep}")
    print(f"  FPT26 Agent v2 — Evaluation Summary ({agg['task_count']} tasks)")
    print(sep)
    print(header)
    print(sep)

    for r in reports:
        task_id = r["task_id"]
        task_type = r.get("task_type", "?")
        sc = r.get("scoring", {})
        ev = r.get("evaluation", {})
        b = r.get("budget", {})
        breakdown = ev.get("tool_breakdown", {})

        score = sc.get("score", 0)
        score_max = r.get("task_difficulty", 0)
        score_pct = sc.get("score_pct", 0)
        accel = sc.get("acceleration")
        accel_str = f"{accel:.1f}x" if accel and accel > 0 else "—"
        budget_str = f"{b.get('spent','?')}/{b.get('total','?')}"
        wall = f"{ev.get('wall_time_seconds', 0):.0f}s"
        tools = f"{breakdown.get('csim',0)}/{breakdown.get('synth',0)}/{breakdown.get('cosim',0)}"

        # Score bar (visual)
        bar = _bar(score_pct, 100, 10)
        print(f"  {task_id:<28} {task_type:<10} {score:>8.3f} {score_max:>5} {score_pct:>5.1f} {accel_str:>7} {budget_str:>10} {wall:>7} {tools:>16} {bar}")

    print(sep)
    print(f"  {'TOTAL / AVG':<28} {'':<10} {agg['total_score']:>8.3f} {agg['total_max']:>5} {agg['score_pct']:>5.1f}% {'':>7} {agg['total_spent']}/{agg['total_budget']:<9} {agg['total_wall_seconds']:.0f}s")
    print(f"  Budget efficiency: {agg['budget_efficiency']:.4f} score/credit  |  Functional pass: {agg['functional_pass_rate']}  |  Optimized: {agg['optimization_rate']}")
    print(sep)


def print_detail(reports: list[dict[str, Any]]) -> None:
    """Print per-task detailed evaluation metrics."""
    for r in reports:
        ev = r.get("evaluation", {})
        sc = r.get("scoring", {})
        print(f"\n── {r['task_id']} ({r.get('task_type','?')}, mode={r.get('mode','?')}) ──")
        print(f"  Status:         {r.get('status','?')}")
        print(f"  Score:          {sc.get('score',0):.3f} / {r.get('task_difficulty',0)}  ({sc.get('score_pct', 0):.1f}%)")
        print(f"  Acceleration:   {sc.get('acceleration', '—')}x  (is_opt={sc.get('is_opt', False)})")
        print(f"  Latency:        {sc.get('baseline_latency', '?')} → {sc.get('candidate_latency', '?')} cycles")
        print(f"  Functional:     {'PASS' if sc.get('functional_pass') else 'FAIL'}")
        print(f"  Synth:          {'PASS' if sc.get('synth_pass') else 'FAIL'}")
        print(f"  Budget:         {ev.get('budget_utilization', 0)*100:.0f}% used ({ev.get('budget_efficiency', '—')} score/credit)")
        print(f"  Wall time:      {ev.get('wall_time_seconds', '?')}s")
        print(f"  Tool breakdown: csim={ev.get('tool_breakdown',{}).get('csim','?')}  synth={ev.get('tool_breakdown',{}).get('synth','?')}  cosim={ev.get('tool_breakdown',{}).get('cosim','?')}")
        print(f"  Repair:         {ev.get('csim_attempts','?')} csim attempts to pass")
        if ev.get('cosim_attempts', 0):
            print(f"  Struct repair:  {ev.get('cosim_attempts')} cosim attempts to pass")
        if ev.get('resource_growth'):
            rg = ev['resource_growth']
            print(f"  Resource growth: LUT={rg.get('LUT','?')}x  FF={rg.get('FF','?')}x  DSP={rg.get('DSP','?')}x")
        if ev.get('resource_efficiency') is not None:
            print(f"  Speed/area:     {ev['resource_efficiency']:.3f} (accel / max_area_growth)")
        if ev.get('baseline_resources'):
            br = ev['baseline_resources']
            print(f"  Baseline res:   LUT={br.get('LUT','?')} FF={br.get('FF','?')} DSP={br.get('DSP','?')}")
        if ev.get('candidate_resources'):
            cr = ev['candidate_resources']
            print(f"  Candidate res:  LUT={cr.get('LUT','?')} FF={cr.get('FF','?')} DSP={cr.get('DSP','?')}")


def print_json(reports: list[dict[str, Any]], agg: dict[str, Any]) -> None:
    """Output aggregate + per-task reports as JSON."""
    output = {"aggregate": agg, "tasks": reports}
    print(json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="FPT26 Agent V3 — cross-run evaluation tool"
    )
    p.add_argument(
        "--output-root", type=Path, default=Path("runs"),
        help="Root directory containing run_report.json files (default: runs/)",
    )
    p.add_argument(
        "--json", action="store_true",
        help="Output machine-readable JSON",
    )
    p.add_argument(
        "--detail", action="store_true",
        help="Show per-metric breakdown for each task",
    )
    p.add_argument(
        "--compat", action="store_true",
        help="Include legacy (pre-V3) run_report.json files in aggregation",
    )
    p.add_argument(
        "--aggregate-v3", action="store_true",
        help="Use V3 aggregator (collect_reports) directly from disk",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # ── V3 direct-disk aggregation ───────────────────────────────────────
    if args.aggregate_v3:
        from agent.reporting.aggregate import collect_reports

        try:
            summary = collect_reports(
                args.output_root, compat_legacy=args.compat
            )
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        if args.json:
            output = {
                "aggregate": {
                    "task_count": summary.task_count,
                    "completed": summary.completed,
                    "failed": summary.failed,
                    "budget_exceeded": summary.budget_exceeded,
                    "infra_error": summary.infra_error,
                    "total_score": round(summary.total_score, 3),
                    "score_pct": round(summary.score_pct, 1),
                    "total_spent": summary.total_spent,
                    "total_budget": summary.total_budget,
                    "budget_utilization_pct": round(summary.budget_utilization_pct, 1),
                    "budget_efficiency": (
                        round(summary.total_score / max(summary.total_spent, 1), 4)
                    ),
                    "total_wall_s": round(summary.total_wall_s, 0),
                    "errors": summary.errors,
                },
                "tasks": [t.__dict__ for t in summary.tasks],
            }
            print(json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False))
        else:
            _print_v3_summary(summary)
        return 0

    # ── Legacy in-memory aggregation ─────────────────────────────────────
    report_paths = find_reports(args.output_root)
    reports = load_reports(report_paths)

    if not reports:
        print("No valid reports loaded.", file=sys.stderr)
        return 1

    agg = aggregate(reports)

    if args.json:
        print_json(reports, agg)
    else:
        print_table(reports, agg)
        if args.detail:
            print_detail(reports)

    return 0


def _print_v3_summary(summary: Any) -> None:
    """Print a V3-aware summary to stdout."""
    print(f"\n{'='*80}")
    print(f"  FPT26 Agent V3 — Evaluation Summary ({summary.task_count} tasks)")
    print(f"{'='*80}")
    print(f"  Completed:     {summary.completed}")
    print(f"  Failed:        {summary.failed}")
    print(f"  Budget Exceed: {summary.budget_exceeded}")
    print(f"  Infra Error:   {summary.infra_error}")
    print(f"  Total Score:   {summary.total_score:.2f} / {summary.total_score_max:.0f} "
          f"({summary.score_pct:.1f}%)")
    print(f"  Credits:       {summary.total_spent} / {summary.total_budget} "
          f"({summary.budget_utilization_pct:.0f}%)")
    print(f"  Wall Time:     {summary.total_wall_s:.0f}s")
    print(f"  Grading Time:  {summary.total_grading_s:.0f}s")
    if summary.errors:
        print(f"\n  Warnings ({len(summary.errors)}):")
        for e in summary.errors[:10]:
            print(f"    - {e}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    sys.exit(main())
