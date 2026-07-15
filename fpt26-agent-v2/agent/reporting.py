"""Run reporting with derived evaluation metrics.

Writes a detailed run summary to ``runs/<task_id>/run_report.json``
and prints a console-friendly scorecard.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.agents.base import RunState


# ---------------------------------------------------------------------------
# Derived metrics
# ---------------------------------------------------------------------------


def _tool_breakdown(results: list) -> dict[str, int]:
    """Count tool calls by kind (csim / synth / cosim)."""
    breakdown: dict[str, int] = {}
    for r in results:
        kind = getattr(r, "kind", "unknown")
        breakdown[kind] = breakdown.get(kind, 0) + 1
    return breakdown


def _attempts_to_pass(results: list, kind: str = "csim") -> int:
    """Count how many *failed* attempts before the first success."""
    fails = 0
    for r in results:
        k = getattr(r, "kind", "")
        if k != kind:
            continue
        if getattr(r, "ok", False):
            return fails
        fails += 1
    return fails


def _wall_time(results: list) -> float:
    """Total wall-clock seconds across all tool calls."""
    return sum(getattr(r, "elapsed_s", 0.0) for r in results)


def _resource_growth(candidate: dict, baseline: dict) -> dict[str, float] | None:
    """Compute resource growth ratios (candidate / baseline)."""
    if not candidate or not baseline:
        return None
    growth: dict[str, float] = {}
    for key in ("LUT", "FF", "DSP", "BRAM_18K"):
        base = baseline.get(key, 0)
        cand = candidate.get(key, 0)
        if base and base > 0:
            growth[key] = round(cand / base, 2)
        elif cand > 0:
            growth[key] = float("inf")
        else:
            growth[key] = 1.0
    return growth


def _compute_derived(state: RunState) -> dict[str, Any]:
    """Compute all derived evaluation metrics from the run state."""
    results = state.results
    breakdown = _tool_breakdown(results)
    total_spent = getattr(state.server.budget, "spent", 0)
    total_budget = getattr(state.server.budget, "total", 1)

    metrics: dict[str, Any] = {
        "tool_breakdown": breakdown,
        "wall_time_seconds": round(_wall_time(results), 1),
        "csim_attempts": _attempts_to_pass(results, "csim") + 1,
        "cosim_attempts": _attempts_to_pass(results, "cosim") + 1 if breakdown.get("cosim", 0) > 0 else 0,
        "budget_utilization": round(total_spent / max(total_budget, 1), 3),
        "budget_efficiency": None,
        "resource_growth": None,
        "resource_efficiency": None,
    }

    # Budget efficiency: score points per credit spent
    if state.scorecard is not None and total_spent > 0:
        sc = state.scorecard
        if sc.score > 0:
            metrics["budget_efficiency"] = round(sc.score / max(metrics["budget_utilization"], 0.001), 3)

    # Resource efficiency: acceleration per unit area growth
    if state.scorecard is not None:
        sc = state.scorecard
        cand_rep = sc.candidate_report
        base_rep = sc.baseline_report
        if cand_rep is not None and base_rep is not None:
            cand_r = cand_rep.resources if hasattr(cand_rep, "resources") else {}
            base_r = base_rep.resources if hasattr(base_rep, "resources") else {}
            growth = _resource_growth(cand_r, base_r)
            metrics["resource_growth"] = growth
            metrics["baseline_resources"] = base_r
            metrics["candidate_resources"] = cand_r

            if growth and sc.acceleration and sc.acceleration > 0:
                # Use max LUT/FF growth as primary area cost
                max_growth = max(
                    growth.get("LUT", 1.0),
                    growth.get("FF", 1.0),
                    growth.get("DSP", 1.0),
                )
                if max_growth > 0:
                    metrics["resource_efficiency"] = round(
                        sc.acceleration / max(max_growth, 1.0), 3
                    )

    return metrics


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------


def write_run_report(state: RunState) -> Path:
    """Write a JSON run report with derived evaluation metrics to output dir."""
    out_dir = Path(state.config.output_root) / state.task.id
    out_dir.mkdir(parents=True, exist_ok=True)

    derived = _compute_derived(state)

    report: dict[str, Any] = {
        "task_id": state.task.id,
        "task_type": state.task.type,
        "task_difficulty": state.task.difficulty,
        "mode": state.config.mode,
        "competition": state.config.competition,
        "status": state.status,
        "csim_ok": state.csim_ok,
        "synth_ok": state.synth_ok,
        "cosim_ok": state.cosim_ok,
        "best_latency": state.best_latency,
        "stop_reason": state.stop_reason,
        "tool_call_count": len(state.results),
        "budget": {
            "total": getattr(state.server.budget, "total", None),
            "spent": getattr(state.server.budget, "spent", None),
        },
        # Derived metrics
        "evaluation": derived,
    }

    if state.scorecard is not None:
        sc = state.scorecard
        report["scoring"] = {
            "score": sc.score,
            "score_max": sc.difficulty,  # theoretical max = difficulty × 1.0
            "score_pct": round(sc.score / max(sc.difficulty, 1) * 100, 1),
            "functional_pass": sc.functional_pass,
            "synth_pass": sc.synth_pass,
            "cosim_pass": sc.cosim_pass,
            "baseline_latency": sc.baseline_latency,
            "candidate_latency": sc.candidate_latency,
            "acceleration": sc.acceleration,
            "is_opt": sc.is_opt,
        }

    report_path = out_dir / "run_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report_path


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------


def print_evaluation(state: RunState) -> None:
    """Print a structured evaluation summary to stdout."""
    derived = _compute_derived(state)
    breakdown = derived["tool_breakdown"]

    print(f"\n{'='*60}")
    print(f"  Evaluation: {state.task.id}  [{state.config.mode}]")
    print(f"{'='*60}")

    # Gates
    gates = [
        ("csim", state.csim_ok),
        ("synth", state.synth_ok),
        ("cosim", state.cosim_ok),
    ]
    gate_str = "  ".join(f"{n}={('PASS' if v else 'FAIL')}" for n, v in gates)
    print(f"  Gates:        {gate_str}")

    # Budget
    budget = state.server.budget
    total = getattr(budget, "total", "?")
    spent = getattr(budget, "spent", "?")
    print(f"  Budget:       {spent}/{total} credits ({derived['budget_utilization']*100:.0f}%)")
    print(f"  Wall time:    {derived['wall_time_seconds']:.0f}s")
    print(f"  Tools:        csim={breakdown.get('csim',0)}  synth={breakdown.get('synth',0)}  cosim={breakdown.get('cosim',0)}")

    # Score
    if state.scorecard is not None:
        sc = state.scorecard
        score_pct = round(sc.score / max(sc.difficulty, 1) * 100, 1)
        print(f"  Score:        {sc.score:.3f} / {sc.difficulty} ({score_pct}%)")
        if sc.acceleration is not None:
            print(f"  Acceleration: {sc.acceleration:.2f}x  (baseline={sc.baseline_latency} → candidate={sc.candidate_latency} cyc)")
        if derived["budget_efficiency"] is not None:
            print(f"  Score/credit: {derived['budget_efficiency']:.3f}")
        if derived["resource_efficiency"] is not None:
            print(f"  Speed/area:   {derived['resource_efficiency']:.3f}  (growth={derived['resource_growth']})")

    # Repair stats
    if derived["csim_attempts"] > 1:
        print(f"  Repair:       {derived['csim_attempts']} csim attempts to pass")
    if derived.get("cosim_attempts", 0) > 1:
        print(f"  Struct repair:{derived['cosim_attempts']} cosim attempts to pass")

    print(f"{'='*60}\n")


def print_transcript(state: RunState) -> None:
    """Print the metered tool transcript to stdout."""
    server = state.server
    total = getattr(server.budget, "total", "?")
    print(f"\n=== Tool Transcript ({len(server.transcript)} calls) ===")
    for entry in server.transcript:
        print(f"  #{entry.n:<2} {entry.detail}   [spent {entry.spent}/{total}]")
    summary = getattr(server.budget, "summary", None)
    if callable(summary):
        print(f"  {summary()}")
