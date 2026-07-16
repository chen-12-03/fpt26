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
                "resource_capacity_pass": getattr(
                    sc, "resource_capacity_pass", None
                ),
                "anchor_source": sc.anchor_source,
                "latency_ratio": sc.latency_ratio,
                "acceleration_source": getattr(
                    sc, "acceleration_source", "synth"
                ),
                "cosim_latency_used": getattr(sc, "cosim_latency_used", None),
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
                "available_resources": getattr(sc, "available_resources", {}),
                "cost_spent": sc.cost_spent,
                "cost_limit": sc.cost_limit,
                "wall_time_s": sc.wall_time_s,
                "time_limit_s": sc.time_limit_s,
            }
            # Reference-anchored scorecard (vs golden answer)
            if state.ref_scorecard is not None:
                rsc = state.ref_scorecard
                report["scoring_vs_reference"] = {
                    "anchor": "reference",
                    "score": rsc.score,
                    "score_pct": round(rsc.score / max(rsc.score_max, 1) * 100, 1),
                    "valid": rsc.valid,
                    "q_hw": rsc.q_hw,
                    "q_perf": rsc.q_perf,
                    "q_area": rsc.q_area,
                    "latency_ratio": rsc.latency_ratio,
                    "area_growth": rsc.area_growth,
                    "bottleneck_resource": rsc.bottleneck_resource,
                    "reference_latency": rsc.anchor_latency,
                    "reference_ii": rsc.anchor_ii,
                    "reference_clock_ns": rsc.anchor_clock_ns,
                    "reference_resources": rsc.baseline_resources,
                    "candidate_resources": rsc.candidate_resources,
                    "growth_by_resource": rsc.growth_by_resource,
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


def _res_str(r: dict) -> str:
    """Compact resource string."""
    parts = []
    for k in ("LUT", "FF", "DSP", "BRAM_18K", "URAM"):
        v = r.get(k, 0)
        if v or k in ("LUT", "FF"):
            parts.append(f"{k}={v}")
    return " ".join(parts)


def _loop_str(loop_metrics: list) -> str:
    """Format loop metrics as string."""
    if not loop_metrics:
        return ""
    loops = []
    for lm in loop_metrics:
        trip = lm.get("trip_count", "?")
        lat = lm.get("latency", "?")
        ii = lm.get("pipeline_ii", "?")
        name = lm.get("name", "?")
        loops.append(f"{name}(trip={trip},lat={lat},II={ii})")
    return ", ".join(loops)


def print_evaluation(state: RunState) -> None:
    """Print a structured optimization report to stdout."""
    derived = _compute_derived(state)
    breakdown = derived["tool_breakdown"]
    budget = state.server.budget
    total_budget = getattr(budget, "total", "?")
    spent = getattr(budget, "spent", "?")
    sc = state.scorecard
    rsc = state.ref_scorecard
    is_v3 = sc is not None and hasattr(sc, 'schema_version') and getattr(sc, 'schema_version', 0) >= 5

    # ── Extract synth transcript indices ────────────────────────────────
    synth_tx_indices: list[int] = []
    for entry in state.server.transcript:
        if entry.kind == "synth":
            synth_tx_indices.append(entry.n)

    # ── Structured candidate data (from OptimizeAgent) ──────────────────
    structured = state.metadata.get("synth_candidates", [])

    # ── Build candidate list from structured data (preferred) or results ─
    baseline_info: dict | None = None
    candidates_info: list[dict] = []
    for c in structured:
        if c.get("is_baseline") or c.get("round") == 0:
            baseline_info = c
        else:
            candidates_info.append(c)

    # Extract baseline from results if no structured data
    if baseline_info is None:
        for r in state.results:
            if r.kind == "synth" and r.report is not None:
                br = r.report
                bl_ii = br.loop_metrics[0].get("pipeline_ii") if br.loop_metrics else None
                baseline_info = {
                    "round": 0, "is_baseline": True,
                    "latency": br.latency_worst, "top_interval": br.interval_max,
                    "loop_ii": bl_ii, "clock_ns": br.clock_period_ns,
                    "resources": dict(br.resources),
                    "loop_metrics": [dict(lm) for lm in (br.loop_metrics or [])],
                    "decision": "BASELINE",
                }
                break

    # ── Helper: total area ──────────────────────────────────────────────
    def _total_area(res: dict) -> int:
        return res.get("LUT", 0) + res.get("FF", 0) + res.get("DSP", 0)

    # ── Header ──────────────────────────────────────────────────────────
    task_id = state.task.id
    print(f"\n{'='*80}")
    print(f"  OPTIMIZATION REPORT — {task_id}")
    print(f"{'='*80}")

    gates = [
        ("csim", state.csim_ok),
        ("synth", state.synth_ok),
        ("cosim", _reported_cosim_status(state)),
    ]
    gate_str = ", ".join(
        f"{n}={('N/A' if v is None else ('PASS' if v else 'FAIL'))}"
        for n, v in gates
    )
    status = "PASS" if (is_v3 and sc.valid) else ("FAIL" if is_v3 else "?")
    stage = getattr(sc, 'stage', '?') if is_v3 else "?"
    grading_time = sc.wall_time_s if is_v3 else 0
    print(f"  Status: {status} | Stage: {stage} | Gates: {gate_str}")
    print(f"  Budget: {spent}/{total_budget} credits ({derived['budget_utilization']*100:.0f}%) | "
          f"Wall: {derived['wall_time_seconds']:.0f}s | Grading: {grading_time:.0f}/3600s | "
          f"Tools: csim×{breakdown.get('csim',0)}, synth×{breakdown.get('synth',0)}, cosim×{breakdown.get('cosim',0)}")

    # ── Score ───────────────────────────────────────────────────────────
    print(f"\n  {'SCORE':─^76}")
    if is_v3:
        starter_score = f"{sc.score:.2f}/{sc.score_max:.0f} ({round(sc.score / max(sc.score_max, 1) * 100, 1)}%)"
        print(f"  Starter anchor  : {starter_score} | Q_perf={sc.q_perf:.4f} | Q_area={sc.q_area:.4f} | Q_HW={sc.q_hw:.4f}")
        if rsc is not None:
            ref_score_str = f"{rsc.score:.2f}/{rsc.score_max:.0f} ({round(rsc.score / max(rsc.score_max, 1) * 100, 1)}%)"
            print(f"  Reference anchor: {ref_score_str} | Q_HW={rsc.q_hw:.4f} | Valid={rsc.valid}")
        print(f"  Efficiency={sc.efficiency:.4f} | HW ratio={getattr(sc, 'hardware_ratio', 1.0):.4f}x")
    else:
        print(f"  Score: {sc.score:.3f} / {getattr(sc, 'difficulty', '?')}")

    # ── STARTER / FINAL BEST / REFERENCE table ──────────────────────────
    base_res = baseline_info.get("resources", {}) if baseline_info else {}
    base_lat = baseline_info.get("latency") if baseline_info else None
    base_ti = baseline_info.get("top_interval") if baseline_info else None
    base_lii = baseline_info.get("loop_ii") if baseline_info else None
    base_clk = baseline_info.get("clock_ns") if baseline_info else None

    # Best = what was ultimately submitted
    if is_v3 and sc.valid:
        best_res = sc.candidate_resources
        best_lat = sc.anchor_latency
        best_ti = sc.anchor_ii
        best_clk = base_clk
        # Check if agent accepted a candidate (scorecard reflects improvement)
        improved = (sc.latency_ratio is not None and sc.latency_ratio != 1.0) or \
                   (sc.area_growth is not None and sc.area_growth != 1.0)
        if improved:
            for c in reversed(candidates_info):
                if c.get("decision") == "ACCEPTED":
                    best_lat = c.get("latency", best_lat)
                    best_ti = c.get("top_interval", best_ti)
                    best_clk = c.get("clock_ns", best_clk)
                    best_res = c.get("resources", best_res)
                    break
    else:
        best_res = base_res
        best_lat = base_lat
        best_ti = base_ti
        best_clk = base_clk

    ref_lat = rsc.anchor_latency if rsc else None
    ref_ti = rsc.anchor_ii if rsc else None
    ref_clk = rsc.anchor_clock_ns if rsc else None
    ref_res = rsc.baseline_resources if rsc else {}

    # Is final best same as baseline?
    final_is_baseline = (best_lat == base_lat and best_res == base_res)

    print(f"\n  {'STARTER / FINAL BEST / REFERENCE':─^76}")
    print(f"  {'':<22} {'Starter':<20} {'Final Best':<20} {'Reference':<20}")
    print(f"  {'─'*22} {'─'*20} {'─'*20} {'─'*20}")
    print(f"  {'Latency / Top Interval':<22} {str(base_lat)+' / '+str(base_ti):<20} {str(best_lat)+' / '+str(best_ti):<20} {str(ref_lat)+' / '+str(ref_ti):<20}")
    print(f"  {'Loop II':<22} {str(base_lii) if base_lii is not None else 'N/A':<20} {'N/A':<20} {'N/A':<20}")
    print(f"  {'Clock':<22} {str(base_clk)+' ns' if base_clk else 'N/A':<20} {str(best_clk)+' ns' if best_clk else 'N/A':<20} {str(ref_clk)+' ns' if ref_clk else 'N/A':<20}")
    print(f"  {'Power':<22} {'N/A':<20} {'N/A':<20} {'N/A':<20}")
    print(f"  {'Area':<22} {_res_str(base_res):<20} {_res_str(best_res):<20} {_res_str(ref_res):<20}")

    # Ratios: split into two rows
    def _lat_ratio(cand_lat, anchor_lat):
        if anchor_lat and cand_lat and anchor_lat > 0:
            return f"{cand_lat / anchor_lat:.2f}x"
        return "N/A"

    def _area_ratio(cand_r, anchor_r):
        if anchor_r and cand_r:
            return f"{_total_area(cand_r) / max(_total_area(anchor_r), 1):.2f}x"
        return "N/A"

    best_vs_starter_lat = _lat_ratio(best_lat, base_lat)
    best_vs_starter_area = _area_ratio(best_res, base_res)
    best_vs_ref_lat = _lat_ratio((best_lat or base_lat), ref_lat)
    best_vs_ref_area = _area_ratio((best_res if best_res else base_res), ref_res)

    print(f"  {'Best vs Starter':<22} {f'latency={best_vs_starter_lat}  area={best_vs_starter_area}':<20} {'':<20}")
    ref_ratio_str = f"latency={best_vs_ref_lat}  area={best_vs_ref_area}" if ref_lat else "N/A"
    print(f"  {'Best vs Reference':<22} {'':<20} {ref_ratio_str:<20}")

    # Bottleneck
    if is_v3 and sc.valid:
        bottleneck = sc.bottleneck_resource
        growth_str = ", ".join(
            f"{k}={v:.2f}x" for k, v in sc.growth_by_resource.items()
        ) if sc.growth_by_resource else "N/A"
        print(f"\n  Area bottleneck: {bottleneck} | Growth: {growth_str}")

    # ── SYNTHESIS CANDIDATES ────────────────────────────────────────────
    all_entries = []
    # Baseline
    if baseline_info:
        bl_idx = synth_tx_indices[0] if synth_tx_indices else 2
        label = f"Final Best (#{bl_idx})" if final_is_baseline else f"Baseline (#{bl_idx})"
        all_entries.append((label, baseline_info, baseline_info.get("decision", "BASELINE")))
    # Candidates
    for i, c in enumerate(candidates_info):
        idx = synth_tx_indices[i + 1] if i + 1 < len(synth_tx_indices) else (i + 3)
        qhwb = c.get("q_hw_before")
        qhwa = c.get("q_hw_after")
        decision = c.get("decision", "REJECTED")
        delta_str = f"Q_HW {qhwb:.4f}→{qhwa:.4f}" if (qhwb is not None and qhwa is not None) else ""
        label = f"{'Accepted' if decision == 'ACCEPTED' else 'Rejected'} (#{idx})"
        all_entries.append((label, c, decision))

    if all_entries:
        print(f"\n  {'SYNTHESIS CANDIDATES':─^76}")
        print(f"  {'Candidate':<22} {'Lat / Top Int':<17} {'Loop II':<10} {'Clock':<10} {'Area':<40} {'Decision':<12}")
        print(f"  {'─'*22} {'─'*17} {'─'*10} {'─'*10} {'─'*40} {'─'*12}")
        for label, c, decision in all_entries:
            lat = c.get("latency", "?")
            ti = c.get("top_interval", "?")
            lii = c.get("loop_ii", "?")
            clk = f"{c['clock_ns']} ns" if c.get("clock_ns") else "?"
            res = _res_str(c.get("resources", {}))
            lat_ti = f"{lat} / {ti} cyc"
            lii_str = str(lii) if lii is not None else "?"
            dec_str = decision if decision != "BASELINE" else "—"
            print(f"  {label:<22} {lat_ti:<17} {lii_str:<10} {clk:<10} {res:<40} {dec_str:<12}")

    # ── Loop details ────────────────────────────────────────────────────
    if baseline_info:
        bl_loops = _loop_str(baseline_info.get("loop_metrics", []))
        if bl_loops:
            lbl = f"{'Final Best' if final_is_baseline else 'Baseline'} loops"
            print(f"\n  {lbl}: {bl_loops}")

    for i, c in enumerate(candidates_info):
        if c.get("decision") == "REJECTED":
            cl = _loop_str(c.get("loop_metrics", []))
            if cl:
                print(f"  Rejected candidate R{c.get('round','?')} loops: {cl}")
                break  # only show last rejected

    # ── Trade-off ───────────────────────────────────────────────────────
    if baseline_info and candidates_info:
        last_cand = candidates_info[-1]
        base_l = baseline_info.get("latency")
        cand_l = last_cand.get("latency")
        if base_l and cand_l and base_l > 0:
            lat_diff = cand_l - base_l
            lat_pct = abs(lat_diff) / base_l * 100
            direction = "↓" if lat_diff < 0 else "↑"
            parts = [f"Latency {direction}{abs(lat_diff)} ({lat_pct:.1f}%)"]

            base_r = baseline_info.get("resources", {})
            cand_r = last_cand.get("resources", {})
            for res_key in ("LUT", "FF", "DSP"):
                bv = base_r.get(res_key, 0)
                cv = cand_r.get(res_key, 0)
                if bv != cv and bv > 0:
                    diff = cv - bv
                    pct = abs(diff) / bv * 100
                    arrow = "↓" if diff < 0 else "↑"
                    parts.append(f"{res_key} {arrow}{abs(diff)} ({pct:.1f}%)")
            if parts:
                print(f"\n  Trade-off: {' | '.join(parts)}")

    # ── MODEL / TOKEN / COST ────────────────────────────────────────────
    llm = _llm_summary(state)
    print(f"\n  {'MODEL / TOKEN / COST':─^76}")
    if llm is not None:
        usage = llm.get("token_usage")
        model_str = llm.get("model") or llm.get("client") or "?"
        if isinstance(usage, dict):
            requests = usage.get("request_count", 0)
            reported = usage.get("reported_usage_count", 0)
            prompt_t = usage.get("prompt_tokens", 0)
            compl_t = usage.get("completion_tokens", 0)
            total_t = usage.get("total_tokens", 0)
            print(f"  Model={model_str} | API={reported}/{requests} | Prompt={prompt_t} | Completion={compl_t} | Total={total_t} tokens")
        else:
            print(f"  Model={model_str} | API tokens: unavailable")
    csim_times = ", ".join(f"{r.elapsed_s:.1f}s" for r in state.results if r.kind == "csim")
    synth_times = ", ".join(f"{r.elapsed_s:.1f}s" for r in state.results if r.kind == "synth")
    print(f"  Credits={spent}/{total_budget} | CSIM time={csim_times} | Synthesis time={synth_times}")

    # ── OPTIMIZATION TARGETS ────────────────────────────────────────────
    print(f"\n  {'OPTIMIZATION TARGETS':─^76}")
    base_lat_str = f"{base_lat} cyc" if base_lat else "?"
    print(f"  Latency : {base_lat_str} → reduce loop II and loop latency")
    if base_res:
        res_parts = ", ".join(f"{k}={v}" for k, v in base_res.items() if v)
        bt = sc.bottleneck_resource if (is_v3 and sc.valid) else "N/A"
        print(f"  Area    : {res_parts} → {bt} is the current bottleneck")
    print(f"  Power   : N/A → add total, dynamic and static power measurements")
    llm_tokens_val = 0
    if llm is not None and isinstance(llm.get("token_usage"), dict):
        llm_tokens_val = llm["token_usage"].get("total_tokens", 0)
    print(f"  Token   : {llm_tokens_val} → reduce prompt size and unnecessary repeated tool calls")
    wall_s = derived['wall_time_seconds']
    print(f"  Time    : {wall_s:.0f}s wall / {grading_time:.0f}s grading → reduce unsuccessful synthesis iterations")
    print(f"{'='*80}\n")


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
