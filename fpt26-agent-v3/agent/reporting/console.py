"""Console (stdout) display of agent run results.

Separated from JSON report writing so each can evolve independently.
"""

from __future__ import annotations

from typing import Any


def _res_str(r: dict) -> str:
    """Full resource string — all five resources."""
    parts = []
    for k in ("LUT", "FF", "DSP", "BRAM_18K", "URAM"):
        v = r.get(k, 0)
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


def _total_area(res: dict) -> int:
    return res.get("LUT", 0) + res.get("FF", 0) + res.get("DSP", 0)


def _lat_ratio(cand_lat, anchor_lat):
    if anchor_lat and cand_lat and anchor_lat > 0:
        return f"{cand_lat / anchor_lat:.2f}x"
    return "N/A"


def _area_ratio(cand_r, anchor_r):
    if anchor_r and cand_r:
        return f"{_total_area(cand_r) / max(_total_area(anchor_r), 1):.2f}x"
    return "N/A"


def print_scorecard(
    *,
    status: str,
    stage: str,
    gate_str: str,
    spent: Any,
    total_budget: Any,
    budget_util_pct: float,
    wall_time_s: float,
    grading_time_s: float,
    breakdown: dict[str, int],
    is_v3: bool = True,
    sc: Any = None,
    rsc: Any = None,
) -> None:
    """Print a compact scorecard section to stdout."""
    print(f"  Status: {status} | Stage: {stage} | Gates: {gate_str}")
    print(f"  Budget: {spent}/{total_budget} credits ({budget_util_pct:.0f}%) | "
          f"Wall: {wall_time_s:.0f}s | Grading: {grading_time_s:.0f}/3600s | "
          f"Tools: csim×{breakdown.get('csim',0)}, "
          f"synth×{breakdown.get('synth',0)}, "
          f"cosim×{breakdown.get('cosim',0)}")

    print(f"\n  {'SCORE':─^76}")
    if is_v3 and sc is not None:
        starter_score = (
            f"{sc.score:.2f}/{sc.score_max:.0f} "
            f"({round(sc.score / max(sc.score_max, 1) * 100, 1)}%)"
        )
        print(f"  Starter anchor  : {starter_score} | "
              f"Q_perf={sc.q_perf:.4f} | Q_area={sc.q_area:.4f} | "
              f"Q_HW={sc.q_hw:.4f}")
        if rsc is not None:
            ref_str = (
                f"{rsc.score:.2f}/{rsc.score_max:.0f} "
                f"({round(rsc.score / max(rsc.score_max, 1) * 100, 1)}%)"
            )
            print(f"  Reference anchor: {ref_str} | "
                  f"Q_HW={rsc.q_hw:.4f} | Valid={rsc.valid}")
        hw = getattr(sc, "hardware_ratio", 1.0)
        print(f"  Efficiency={sc.efficiency:.4f} | HW ratio={hw:.4f}x")
    elif sc is not None:
        print(f"  Score: {sc.score:.3f} / {getattr(sc, 'difficulty', '?')}")
    else:
        print("  Evaluator score: N/A (submission role uses public acceptance "
              "gates only)")


def print_candidate_table(
    baseline_info: dict | None,
    candidates_info: list[dict],
    final_is_baseline: bool,
    synth_tx_indices: list[int],
) -> None:
    """Print the synthesis candidates comparison table."""
    all_entries = []
    if baseline_info:
        bl_idx = synth_tx_indices[0] if synth_tx_indices else 2
        label = (
            f"Final Best (#{bl_idx})" if final_is_baseline
            else f"Baseline (#{bl_idx})"
        )
        all_entries.append(
            (label, baseline_info, baseline_info.get("decision", "BASELINE"))
        )
    for i, c in enumerate(candidates_info):
        idx = (
            synth_tx_indices[i + 1]
            if i + 1 < len(synth_tx_indices)
            else (i + 3)
        )
        decision = c.get("decision", "REJECTED")
        label_prefix = {
            "ACCEPTED": "Accepted",
            "SELECTED": "Selected",
            "VALID_NOT_SELECTED": "Valid",
        }.get(decision, "Rejected")
        strategy = c.get("strategy")
        label = f"{label_prefix} (#{idx})"
        if strategy:
            label = f"{label_prefix}:{strategy[:10]} (#{idx})"
        all_entries.append((label, c, decision))

    if all_entries:
        print(f"\n  {'SYNTHESIS CANDIDATES':─^76}")
        hdr = (f"  {'Candidate':<22} {'Lat / Top Int':<17} "
               f"{'Loop II':<10} {'Clock':<10} {'Area':<40} {'Decision':<12}")
        print(hdr)
        print(f"  {'─'*22} {'─'*17} {'─'*10} {'─'*10} {'─'*40} {'─'*12}")
        for label, c, decision in all_entries:
            lat = c.get("latency", "?")
            ti = c.get("top_interval", "?")
            lii = c.get("loop_ii", "?")
            clk = f"{c['clock_ns']} ns" if c.get("clock_ns") else "?"
            res = _res_str(c.get("resources", {}))
            dec_str = {
                "BASELINE": "SELECTED" if final_is_baseline else "BASELINE",
                "ACCEPTED": "ACCEPTED",
                "SELECTED": "SELECTED",
                "VALID_NOT_SELECTED": "VALID",
            }.get(decision, "REJECTED")
            print(f"  {label:<22} {f'{lat} / {ti} cyc':<17} "
                  f"{str(lii) if lii is not None else '?':<10} "
                  f"{clk:<10} {res:<40} {dec_str:<12}")


def print_comparison_table(
    *,
    base_res: dict,
    base_lat,
    base_ti,
    base_lii,
    base_clk,
    best_res: dict,
    best_lat,
    best_ti,
    best_lii,
    best_clk,
    best_cosim,
    ref_lat=None,
    ref_ti=None,
    ref_clk=None,
    ref_res: dict | None = None,
    is_v3: bool = False,
    sc: Any = None,
) -> None:
    """Print the starter/final/reference comparison table."""
    print(f"\n  {'STARTER / FINAL BEST / REFERENCE':─^76}")
    print(f"  {'':<22} {'Starter':<20} {'Final Best':<20} {'Reference':<20}")
    print(f"  {'─'*22} {'─'*20} {'─'*20} {'─'*20}")
    print(f"  {'Lat / Top Int (cyc)':<22} "
          f"{str(base_lat)+' / '+str(base_ti):<20} "
          f"{str(best_lat)+' / '+str(best_ti):<20} "
          f"{str(ref_lat)+' / '+str(ref_ti):<20}")
    print(f"  {'Loop II':<22} "
          f"{str(base_lii) if base_lii is not None else 'N/A':<20} "
          f"{str(best_lii) if best_lii is not None else 'N/A':<20} "
          f"{'N/A':<20}")
    print(f"  {'Clock':<22} "
          f"{str(base_clk)+' ns' if base_clk else 'N/A':<20} "
          f"{str(best_clk)+' ns' if best_clk else 'N/A':<20} "
          f"{str(ref_clk)+' ns' if ref_clk else 'N/A':<20}")
    print(f"  {'CoSim max latency':<22} {'N/A':<20} "
          f"{str(best_cosim)+' cyc' if best_cosim is not None else 'N/A':<20} "
          f"{'N/A':<20}")
    print(f"  {'Power':<22} {'N/A':<20} {'N/A':<20} {'N/A':<20}")
    print(f"  {'Area':<22} {_res_str(base_res):<20} "
          f"{_res_str(best_res):<20} {_res_str(ref_res or {}):<20}")

    best_vs_starter_lat = _lat_ratio(best_lat, base_lat)
    best_vs_starter_area = _area_ratio(best_res, base_res)
    best_vs_ref_lat = _lat_ratio((best_lat or base_lat), ref_lat)
    best_vs_ref_area = _area_ratio(
        (best_res if best_res else base_res), ref_res or {}
    )
    print(f"  Final Best vs Starter  : latency={best_vs_starter_lat} | "
          f"area={best_vs_starter_area}")
    if ref_lat:
        print(f"  Final Best vs Reference: latency={best_vs_ref_lat} | "
              f"area={best_vs_ref_area}")

    if is_v3 and sc is not None and sc.valid:
        growth_str = ", ".join(
            f"{k}={v:.2f}x" for k, v in sc.growth_by_resource.items()
        ) if sc.growth_by_resource else "N/A"
        print(f"\n  Area bottleneck: {sc.bottleneck_resource} | "
              f"Growth: {growth_str}")
