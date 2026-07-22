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


# ═══════════════════════════════════════════════════════════════════════════════
# Full evaluation display (migrated from _legacy.py)
# ═══════════════════════════════════════════════════════════════════════════════


def print_evaluation(state: Any) -> None:
    """Print a structured evaluation report to stdout."""
    from agent.reporting.metrics import (
        _compute_derived,
        _final_synth_info,
        _grading_synth_info,
        _llm_summary,
        _reported_cosim_status,
        _synth_info,
    )

    derived = _compute_derived(state)
    breakdown = derived["tool_breakdown"]
    budget = state.server.budget
    total_budget = getattr(budget, "total", "?")
    spent = getattr(budget, "spent", "?")
    sc = state.scorecard
    rsc = getattr(state, 'ref_scorecard', None)
    is_v3 = sc is not None and hasattr(sc, 'schema_version') and getattr(sc, 'schema_version', 0) >= 5

    # ── Extract synth transcript indices ────────────────────────────────
    synth_tx_indices: list[int] = []
    for entry in state.server.transcript:
        if entry.kind == "synth":
            synth_tx_indices.append(entry.n)

    # ── Structured candidate data (from OptimizeAgent) ──────────────────
    structured = getattr(state, 'metadata', {}).get("synth_candidates", [])

    baseline_info: dict | None = None
    candidates_info: list[dict] = []
    for c in structured:
        if c.get("is_baseline") or c.get("round") == 0:
            baseline_info = c
        else:
            candidates_info.append(c)

    graded_baseline = _grading_synth_info(state, "starter_synth")
    if graded_baseline is not None:
        graded_baseline.update({"round": 0, "is_baseline": True, "decision": "BASELINE"})
        baseline_info = graded_baseline

    if baseline_info is None:
        for r in state.results:
            info = _synth_info(r)
            if getattr(r, "kind", None) == "synth" and info is not None:
                info.update({"round": 0, "is_baseline": True, "decision": "BASELINE"})
                baseline_info = info
                break

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
    status = "PASS" if state.status == "completed" else "FAIL"
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
    elif sc is not None:
        print(f"  Score: {sc.score:.3f} / {getattr(sc, 'difficulty', '?')}")
    else:
        print("  Evaluator score: N/A (submission role uses public acceptance gates only)")

    # ── STARTER / FINAL BEST / REFERENCE table ──────────────────────────
    base_res = baseline_info.get("resources", {}) if baseline_info else {}
    base_lat = baseline_info.get("latency") if baseline_info else None
    base_ti = baseline_info.get("top_interval") if baseline_info else None
    base_lii = baseline_info.get("loop_ii") if baseline_info else None
    base_clk = baseline_info.get("clock_ns") if baseline_info else None

    final_info = _final_synth_info(state)
    best_res = final_info.get("resources", {}) if final_info is not None else base_res
    best_lat = final_info.get("latency") if final_info is not None else base_lat
    best_ti = final_info.get("top_interval") if final_info is not None else base_ti
    best_lii = final_info.get("loop_ii") if final_info is not None else base_lii
    best_clk = final_info.get("clock_ns") if final_info is not None else base_clk

    ref_lat = rsc.anchor_latency if rsc else None
    ref_ti = rsc.anchor_ii if rsc else None
    ref_clk = rsc.anchor_clock_ns if rsc else None
    ref_res = rsc.baseline_resources if rsc else {}

    final_is_baseline = (best_lat == base_lat and best_res == base_res)

    print(f"\n  {'STARTER / FINAL BEST / REFERENCE':─^76}")
    print(f"  {'':<22} {'Starter':<20} {'Final Best':<20} {'Reference':<20}")
    print(f"  {'─'*22} {'─'*20} {'─'*20} {'─'*20}")
    print(f"  {'Lat / Top Int (cyc)':<22} {str(base_lat)+' / '+str(base_ti):<20} {str(best_lat)+' / '+str(best_ti):<20} {str(ref_lat)+' / '+str(ref_ti):<20}")
    print(f"  {'Loop II':<22} {str(base_lii) if base_lii is not None else 'N/A':<20} {str(best_lii) if best_lii is not None else 'N/A':<20} {'N/A':<20}")
    print(f"  {'Clock':<22} {str(base_clk)+' ns' if base_clk else 'N/A':<20} {str(best_clk)+' ns' if best_clk else 'N/A':<20} {str(ref_clk)+' ns' if ref_clk else 'N/A':<20}")
    cosim_gate = state.metadata.get("cosim_gate") or {}
    best_cosim = cosim_gate.get("latency_max")
    print(f"  {'CoSim max latency':<22} {'N/A':<20} {str(best_cosim)+' cyc' if best_cosim is not None else 'N/A':<20} {'N/A':<20}")
    print(f"  {'Power':<22} {'N/A':<20} {'N/A':<20} {'N/A':<20}")
    print(f"  {'Area':<22} {_res_str(base_res):<20} {_res_str(best_res):<20} {_res_str(ref_res):<20}")

    best_vs_starter_lat = _lat_ratio(best_lat, base_lat)
    best_vs_starter_area = _area_ratio(best_res, base_res)
    best_vs_ref_lat = _lat_ratio((best_lat or base_lat), ref_lat)
    best_vs_ref_area = _area_ratio((best_res if best_res else base_res), ref_res)

    print(f"  Final Best vs Starter  : latency={best_vs_starter_lat} | area={best_vs_starter_area}")
    if ref_lat:
        print(f"  Final Best vs Reference: latency={best_vs_ref_lat} | area={best_vs_ref_area}")

    if is_v3 and sc.valid:
        bottleneck = sc.bottleneck_resource
        growth_str = ", ".join(
            f"{k}={v:.2f}x" for k, v in sc.growth_by_resource.items()
        ) if sc.growth_by_resource else "N/A"
        print(f"\n  Area bottleneck: {bottleneck} | Growth: {growth_str}")

    # ── SYNTHESIS CANDIDATES ────────────────────────────────────────────
    all_entries = []
    if baseline_info:
        bl_idx = synth_tx_indices[0] if synth_tx_indices else 2
        label = f"Final Best (#{bl_idx})" if final_is_baseline else f"Baseline (#{bl_idx})"
        all_entries.append((label, baseline_info, baseline_info.get("decision", "BASELINE")))
    for i, c in enumerate(candidates_info):
        idx = synth_tx_indices[i + 1] if i + 1 < len(synth_tx_indices) else (i + 3)
        qhwb = c.get("q_hw_before")
        qhwa = c.get("q_hw_after")
        decision = c.get("decision", "REJECTED")
        delta_str = f"Q_HW {qhwb:.4f}→{qhwa:.4f}" if (qhwb is not None and qhwa is not None) else ""
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
            dec_str = {
                "BASELINE": "SELECTED" if final_is_baseline else "BASELINE",
                "ACCEPTED": "ACCEPTED",
                "SELECTED": "SELECTED",
                "VALID_NOT_SELECTED": "VALID",
            }.get(decision, "REJECTED")
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
                break

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
                qhwb = last_cand.get("q_hw_before")
                qhwa = last_cand.get("q_hw_after")
                dec = last_cand.get("decision", "REJECTED")
                if qhwb is not None and qhwa is not None:
                    parts.append(f"Q_HW {qhwb:.4f} → {qhwa:.4f} | {dec}")
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


def print_transcript(state: Any) -> None:
    """Print the metered tool transcript to stdout."""
    server = state.server
    total = getattr(server.budget, "total", "?")
    print(f"\n=== Tool Transcript ({len(server.transcript)} calls) ===")
    for entry in server.transcript:
        print(f"  #{entry.n:<2} {entry.detail}   [spent {entry.spent}/{total}]")
    summary = getattr(server.budget, "summary", None)
    if callable(summary):
        print(f"  {summary()}")
