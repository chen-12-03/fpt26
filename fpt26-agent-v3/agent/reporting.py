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
        score_val = sc.score if hasattr(sc, 'score') else 0
        if score_val > 0:
            metrics["budget_efficiency"] = round(score_val / max(metrics["budget_utilization"], 0.001), 3)

    # Resource efficiency: acceleration per unit area growth
    if state.scorecard is not None:
        sc = state.scorecard
        is_v3 = hasattr(sc, 'schema_version') and getattr(sc, 'schema_version', 0) >= 5
        if is_v3 and sc.valid:
            # V3 scorecard: use latency_ratio and area_growth
            metrics["resource_growth"] = sc.growth_by_resource
            metrics["baseline_resources"] = sc.baseline_resources
            metrics["candidate_resources"] = sc.candidate_resources
            if sc.latency_ratio > 0 and sc.area_growth > 0:
                metrics["resource_efficiency"] = round(
                    sc.latency_ratio / max(sc.area_growth, 1.0), 3
                )
        elif not is_v3:
            # Legacy scorecard fields
            cand_rep = getattr(sc, 'candidate_report', None)
            base_rep = getattr(sc, 'baseline_report', None)
            if cand_rep is not None and base_rep is not None:
                cand_r = cand_rep.resources if hasattr(cand_rep, "resources") else {}
                base_r = base_rep.resources if hasattr(base_rep, "resources") else {}
                growth = _resource_growth(cand_r, base_r)
                metrics["resource_growth"] = growth
                metrics["baseline_resources"] = base_r
                metrics["candidate_resources"] = cand_r

                accel = getattr(sc, 'acceleration', None)
                if growth and accel and accel > 0:
                    max_growth = max(
                        growth.get("LUT", 1.0),
                        growth.get("FF", 1.0),
                        growth.get("DSP", 1.0),
                    )
                    if max_growth > 0:
                        metrics["resource_efficiency"] = round(
                            accel / max(max_growth, 1.0), 3
                        )

    return metrics


def _llm_summary(state: RunState) -> dict[str, Any] | None:
    """Return non-sensitive LLM configuration and exact token accounting."""
    client = state.llm
    if client is None:
        return None

    summary: dict[str, Any] = {
        "client": type(client).__name__,
        "model": getattr(client, "model", None),
        "temperature": getattr(client, "temperature", None),
        "max_tokens": getattr(client, "max_tokens", None),
    }
    token_usage = getattr(client, "token_usage", None)
    snapshot = getattr(token_usage, "snapshot", None)
    summary["token_usage"] = snapshot() if callable(snapshot) else None
    return summary


def _reported_cosim_status(state: RunState) -> bool | None:
    """Return N/A for tasks whose validity does not require RTL co-sim."""
    if not state.task.requires_cosim:
        return None
    return state.cosim_ok


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
        "cosim_ok": _reported_cosim_status(state),
        "best_latency": state.best_latency,
        "stop_reason": state.stop_reason,
        "tool_call_count": len(state.results),
        "budget": {
            "total": getattr(state.server.budget, "total", None),
            "spent": getattr(state.server.budget, "spent", None),
        },
        # Derived metrics
        "evaluation": derived,
        "llm": _llm_summary(state),
    }

    if state.scorecard is not None:
        sc = state.scorecard
        # Support both V3 (scoring_v3) and legacy (llm4hls) scorecard formats
        is_v3 = hasattr(sc, 'schema_version') and getattr(sc, 'schema_version', 0) >= 5
        if is_v3:
            report["scoring"] = {
                "schema_version": sc.schema_version,
                "score": sc.score,
                "score_max": sc.score_max,
                "score_pct": round(sc.score / max(sc.score_max, 1) * 100, 1),
                "valid": sc.valid,
                "gate_reason": sc.gate_reason,
                "csim_pass": sc.csim_pass,
                "synth_pass": sc.synth_pass,
                "cosim_pass": sc.cosim_pass,
                "anchor_source": sc.anchor_source,
                "latency_ratio": sc.latency_ratio,
                "performance_ratio": getattr(sc, "performance_ratio", sc.latency_ratio),
                "area_growth": sc.area_growth,
                "area_ratio": getattr(
                    sc, "area_ratio", 1.0 / max(sc.area_growth, 1e-9)
                ),
                "bottleneck_resource": sc.bottleneck_resource,
                "q_perf": sc.q_perf,
                "q_area": sc.q_area,
                "hardware_ratio": getattr(sc, "hardware_ratio", None),
                "q_hw": sc.q_hw,
                "efficiency": sc.efficiency,
                "growth_by_resource": sc.growth_by_resource,
                "baseline_resources": sc.baseline_resources,
                "candidate_resources": sc.candidate_resources,
                "cost_spent": sc.cost_spent,
                "cost_limit": sc.cost_limit,
                "wall_time_s": sc.wall_time_s,
                "time_limit_s": sc.time_limit_s,
            }
        else:
            report["scoring"] = {
                "score": sc.score,
                "score_max": getattr(sc, 'difficulty', 1),
                "score_pct": round(sc.score / max(getattr(sc, 'difficulty', 1), 1) * 100, 1),
                "functional_pass": getattr(sc, 'functional_pass', None),
                "synth_pass": getattr(sc, 'synth_pass', None),
                "cosim_pass": getattr(sc, 'cosim_pass', None),
                "baseline_latency": getattr(sc, 'baseline_latency', None),
                "candidate_latency": getattr(sc, 'candidate_latency', None),
                "acceleration": getattr(sc, 'acceleration', None),
                "is_opt": getattr(sc, 'is_opt', None),
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
        ("cosim", _reported_cosim_status(state)),
    ]
    gate_str = "  ".join(
        f"{name}={'N/A' if value is None else ('PASS' if value else 'FAIL')}"
        for name, value in gates
    )
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
        is_v3 = hasattr(sc, 'schema_version') and getattr(sc, 'schema_version', 0) >= 5
        if is_v3:
            score_pct = round(sc.score / max(sc.score_max, 1) * 100, 1)
            print(f"  Score:        {sc.score:.2f} / {sc.score_max:.0f} ({score_pct}%)  [V{sc.schema_version}]")
            print(f"  Valid:        {'PASS' if sc.valid else 'FAIL'}  ({sc.gate_reason})")
            if sc.valid:
                print(f"  Latency ratio:{sc.latency_ratio:.2f}x  (anchor={sc.anchor_source})")
                print(f"  Q_perf:       {sc.q_perf:.4f}  Q_area: {sc.q_area:.4f}  Q_HW: {sc.q_hw:.4f}")
                if getattr(sc, "hardware_ratio", None) is not None:
                    print(f"  HW ratio:     {sc.hardware_ratio:.4f}x  (log-symmetric perf/area)")
                print(
                    f"  Efficiency:   {sc.efficiency:.4f}  "
                    f"(cost {sc.cost_spent}/{sc.cost_limit}, "
                    f"grading time {sc.wall_time_s:.0f}/{sc.time_limit_s:.0f}s)"
                )
                print(f"  Area growth:  {sc.area_growth:.2f}x  bottleneck={sc.bottleneck_resource}")
                if sc.growth_by_resource:
                    gr = ", ".join(f"{k}={v:.1f}x" for k, v in sc.growth_by_resource.items() if v != 1.0)
                    if gr:
                        print(f"  Resources:    {gr}")
        else:
            score_pct = round(sc.score / max(getattr(sc, 'difficulty', 1), 1) * 100, 1)
            print(f"  Score:        {sc.score:.3f} / {getattr(sc, 'difficulty', '?')} ({score_pct}%)")
            accel = getattr(sc, 'acceleration', None)
            if accel is not None:
                print(f"  Acceleration: {accel:.2f}x  (baseline={getattr(sc, 'baseline_latency', '?')} → candidate={getattr(sc, 'candidate_latency', '?')} cyc)")
        if derived["budget_efficiency"] is not None:
            print(f"  Score/credit: {derived['budget_efficiency']:.3f}")
        if derived["resource_efficiency"] is not None:
            print(f"  Speed/area:   {derived['resource_efficiency']:.3f}  (growth={derived['resource_growth']})")

    # LLM usage (server-reported only; never estimate missing token counts)
    llm = _llm_summary(state)
    if llm is not None:
        usage = llm.get("token_usage")
        print(f"  LLM:          {llm.get('model') or llm.get('client')}")
        if isinstance(usage, dict):
            requests = usage.get("request_count", 0)
            reported = usage.get("reported_usage_count", 0)
            if usage.get("complete"):
                print(
                    "  API tokens:   "
                    f"prompt={usage.get('prompt_tokens')}  "
                    f"completion={usage.get('completion_tokens')}  "
                    f"total={usage.get('total_tokens')}  "
                    f"({reported}/{requests} requests reported)"
                )
            else:
                print(
                    "  API tokens:   incomplete server usage "
                    f"({reported}/{requests} requests reported; exact total unavailable)"
                )

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
