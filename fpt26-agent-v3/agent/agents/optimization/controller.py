"""Optimization controller — the main optimization loop extracted from OptimizeAgent."""

from __future__ import annotations

from typing import Any

from agent.agents.base import RunState
from agent.analysis.action_contract import build_ii_resource_action_contract
from agent.candidate.validator import (
    extract_code,
    mark_fully_verified,
    record_cosim_gate,
    record_synth_gates,
    validate_candidate,
)
from agent.prompts import SYSTEM, build_prompt
from agent.validation import can_afford_validation
from scoring.profiles import DEFAULT_SCORING_PROFILE

from agent.agents.optimization.diagnostics import _diagnose, _latency, _report, _resource_delta
from agent.agents.optimization.feedback import _csim_failure_feedback, _rejection_feedback
from agent.agents.optimization.intent import ii_resource_intent_feedback
from agent.agents.optimization.scoring import (
    latest_successful_cosim_latency,
    latest_successful_synth,
    score_candidate,
)
from agent.agents.optimization.strategies import (
    _candidate_fingerprint,
    _is_minimum_unroll_frontier,
    _strategy_contract_violation,
)


# ── Production entry point reused by OptimizeAgent ───────────────────────

def run_optimization_loop(
    state: RunState,
    llm: Any,
    max_rounds: int = 5,
    scoring_profile: str = DEFAULT_SCORING_PROFILE,
    search_strategy: dict[str, Any] | None = None,
    shared_candidate_fingerprints: set[str] | None = None,
    stop_after_first_measured: bool = False,
    max_stag: int = 3,
) -> RunState:
    """Run the full optimization loop, mutating *state* in place and returning it."""
    task = state.task
    server = state.server
    best = state.kernel
    best_lat = state.best_latency
    stag = 0
    resource_history: list[dict] = []
    best_resources: dict = {}
    anchor_report: Any = None
    best_q_hw: float | None = None
    rejection_feedback: dict[str, Any] | None = None
    best_synth_result = latest_successful_synth(state.results)
    best_cosim_latency = latest_successful_cosim_latency(state.results)
    rejected_fingerprints: set[str] = set()
    semantic_duplicate_skips = 0
    synth_candidates: list[dict] = []
    semantic_current_best_skips = 0
    ii_resource_intent_rejections = 0
    minimum_factor_convergence = False
    cross_strategy_duplicate_skips = 0
    strategy_contract_rejections = 0
    strategy_contract_rejection_reasons: list[str] = []

    # Record baseline synth
    if best_synth_result is not None and best_synth_result.report is not None:
        br = best_synth_result.report
        bl_ii = br.loop_metrics[0].get("pipeline_ii") if br.loop_metrics else None
        synth_candidates.append({
            "round": 0, "is_baseline": True,
            "latency": br.latency_worst, "top_interval": br.interval_max,
            "loop_ii": bl_ii, "clock_ns": br.clock_period_ns,
            "resources": dict(br.resources),
            "loop_metrics": [dict(lm) for lm in (br.loop_metrics or [])],
            "q_hw_before": None, "q_hw_after": None, "decision": "BASELINE",
        })

    for rnd in range(1, max_rounds + 1):
        # ── 1. Synthesize current best ──────────────────────────────
        if best_synth_result is not None:
            cr = best_synth_result
            state.log(f"opt r{rnd}: reusing current-best synth report")
        else:
            cr = server.synth(best)
            state.results.append(cr)
            if cr.ok and cr.report:
                best_synth_result = cr

        if cr.ok and cr.report:
            resource_history.append(cr.report.resources)
            if anchor_report is None:
                anchor_report = cr.report
            current_card = score_candidate(task, anchor_report, cr.report,
                                           scoring_profile, cosim_latency=best_cosim_latency)
            if best_q_hw is None:
                best_q_hw = current_card.q_hw
            if not best_resources:
                best_resources = dict(cr.report.resources)

        report_str = _report(cr) if cr.ok else f"SYNTH FAIL: {getattr(cr, 'log', '')[-500:]}"
        if cr.ok and cr.report and anchor_report is not None:
            current_card = score_candidate(task, anchor_report, cr.report,
                                           scoring_profile, cosim_latency=best_cosim_latency)
            report_str += (f" ScoreAligned(Q_HW={current_card.q_hw:.4f}, "
                           f"latency_ratio={current_card.latency_ratio:.2f}x, "
                           f"area_growth={current_card.area_growth:.2f}x, "
                           f"bottleneck={current_card.bottleneck_resource})")
        diag = _diagnose(cr)
        action_contract = build_ii_resource_action_contract(getattr(cr, "log", "") or "")
        rsrc_trend = _resource_delta(resource_history)

        state.log(f"opt r{rnd}: lat={best_lat} | {report_str}")
        for line in diag.split("\n"):
            if line.strip():
                state.log(f"  {line.strip()}")
        if action_contract:
            targets = [t["array"] for t in action_contract["targets"]]
            state.log(f"opt r{rnd}: measured action contract targets={targets}")

        # ── 2. Knowledge lookup ─────────────────────────────────────
        know = ""
        try:
            from agent.knowledge import lookup_patterns, format_for_prompt
            m = lookup_patterns(task.description or "")
            know = format_for_prompt(m) if m else ""
            if know:
                state.log(f"opt r{rnd}: knowledge ×{len(m)} patterns")
        except Exception as exc:
            state.log(f"opt r{rnd}: knowledge lookup failed ({exc})")

        # ── 3. Build prompt ─────────────────────────────────────────
        prompt = build_prompt(
            task=task, current_kernel=best, best_latency=best_lat,
            csim_result="PASS", synth_result=report_str,
            bottleneck_hint=diag, knowledge_hint=know,
            resource_delta=rsrc_trend,
            rejection_feedback=rejection_feedback,
            action_contract=action_contract,
            search_strategy=search_strategy,
        )

        # ── 4. LLM proposes optimization ────────────────────────────
        resp = llm.complete(SYSTEM, prompt)
        cand = extract_code(resp)
        if not cand or cand.strip() == best.strip():
            state.log(f"opt r{rnd}: no change — converged")
            break
        candidate_fingerprint = _candidate_fingerprint(cand)
        if candidate_fingerprint == _candidate_fingerprint(best):
            semantic_current_best_skips += 1
            state.log(f"opt r{rnd}: semantic no-op versus current best — skip csim/synth")
            if search_strategy and rnd < max_rounds:
                rejection_feedback = {
                    "status": "REJECTED_BY_STRATEGY_CONTRACT",
                    "reason": "candidate was a semantic no-op versus the baseline",
                    "required_next_action": "Stay in the assigned strategy and produce one material, contract-compliant candidate.",
                }
                continue
            break
        strategy_violation = _strategy_contract_violation(best, cand, search_strategy)
        if strategy_violation is not None:
            strategy_contract_rejections += 1
            strategy_contract_rejection_reasons.append(strategy_violation)
            state.log(f"opt r{rnd}: strategy contract rejected candidate before tools: {strategy_violation}")
            rejection_feedback = {
                "status": "REJECTED_BY_STRATEGY_CONTRACT", "reason": strategy_violation,
                "required_next_action": "Stay in the assigned search_strategy and correct only this contract violation.",
            }
            if rnd < max_rounds:
                continue
            break
        if (shared_candidate_fingerprints is not None
                and candidate_fingerprint in shared_candidate_fingerprints):
            semantic_duplicate_skips += 1
            cross_strategy_duplicate_skips += 1
            state.log(f"opt r{rnd}: strategy={search_strategy.get('name') if search_strategy else 'default'} "
                      "duplicated another strategy candidate — skip tools")
            rejection_feedback = {
                "status": "REJECTED_BY_STRATEGY_CONTRACT",
                "reason": "semantic duplicate of another strategy candidate",
                "required_next_action": "Produce a materially different candidate within the assigned strategy family.",
            }
            if rnd < max_rounds:
                continue
            break
        if shared_candidate_fingerprints is not None:
            shared_candidate_fingerprints.add(candidate_fingerprint)
        if candidate_fingerprint in rejected_fingerprints:
            semantic_duplicate_skips += 1
            state.log(f"opt r{rnd}: semantic duplicate of measured rejected candidate — skip csim/synth and converge")
            break

        if not validate_candidate(state, cand, stage=f"optimize_candidate_{rnd}", current_best=False):
            validation = state.metadata.get("interface_validations", [{}])[-1]
            rejection_feedback = {
                "status": "REJECTED_BY_INTERFACE_GATE",
                "reason": validation.get("reason", "interface validation failed"),
                "required_next_action": "Preserve the exact starter top function signature and required includes.",
            }
            rejected_fingerprints.add(candidate_fingerprint)
            stag += 1
            continue
        if not can_afford_validation(getattr(server, "budget", None),
                                      requires_cosim=task.requires_cosim):
            state.stop_reason = "insufficient_budget_for_candidate_validation"
            state.metadata["budget_safe_stop"] = {
                "round": rnd, "remaining": server.budget.remaining(),
                "requires_cosim": task.requires_cosim,
            }
            state.log(f"opt r{rnd}: preserve current best; remaining budget cannot fund candidate validation")
            break

        intent_feedback = ii_resource_intent_feedback(cr, best, cand, action_contract)
        if intent_feedback is not None:
            ii_resource_intent_rejections += 1
            rejected_fingerprints.add(candidate_fingerprint)
            rejection_feedback = intent_feedback
            state.log(f"opt r{rnd}: pragma-only action conflicts with measured HLS 200-448 — skip csim/synth and reflect")
            stag += 1
            continue

        # ── 5. Validate: csim → synth ──────────────────────────────
        cs = server.csim(cand)
        state.results.append(cs)
        if not cs.ok:
            rejected_fingerprints.add(candidate_fingerprint)
            rejection_feedback = _csim_failure_feedback(cs, best, cand)
            state.log(f"opt r{rnd}: csim FAIL — discard")
            stag += 1
            continue

        sr = server.synth(cand)
        state.results.append(sr)
        if not sr.ok:
            state.log(f"opt r{rnd}: synth FAIL — discard")
            stag += 1
            continue

        if not record_synth_gates(state, sr, stage=f"optimize_candidate_{rnd}", current_best=False):
            state.log(f"opt r{rnd}: frequency/resource gate FAIL — discard")
            rejected_fingerprints.add(candidate_fingerprint)
            rejection_feedback = {
                "status": "REJECTED_BY_TARGET_GATE",
                "frequency": (state.metadata.get("synth_gate_history", [{}])[-1].get("frequency")),
                "resource": (state.metadata.get("synth_gate_history", [{}])[-1].get("resource")),
                "required_next_action": "Produce a candidate meeting at least 100 MHz and device capacity.",
            }
            stag += 1
            continue

        cosim_result = None
        if task.requires_cosim:
            cosim_result = server.cosim(cand)
            state.results.append(cosim_result)
            if not record_cosim_gate(state, cosim_result, stage=f"optimize_candidate_{rnd}",
                                     current_best=False, source_code=cand):
                state.log(f"opt r{rnd}: required cosim FAIL — discard candidate")
                rejected_fingerprints.add(candidate_fingerprint)
                rejection_feedback = {
                    "status": "REJECTED_BY_REQUIRED_COSIM",
                    "phase": getattr(cosim_result, "phase", "unknown"),
                    "required_next_action": "Preserve bounded stream/dataflow behavior.",
                }
                stag += 1
                continue

        # ── 6. Compare current scoring_v3 hardware quality ──────────
        lat = _latency(sr)
        cand_lut = (sr.report.resources.get('LUT', 0) or 0) if sr.report else 0
        best_lut = best_resources.get('LUT', 0) if best_resources else 0
        cand_card = (score_candidate(
            task, anchor_report, sr.report, scoring_profile,
            cosim_latency=(getattr(getattr(cosim_result, "cosim", None), "latency_max", None)
                           if task.requires_cosim else None),
        ) if anchor_report is not None and sr.report is not None else None)

        state.log(f"opt r{rnd}: lat {best_lat}→{lat} | {_report(sr)} | "
                  f"Q_HW {best_q_hw}→{cand_card.q_hw if cand_card else None}")

        old_q_hw = best_q_hw
        if cand_card is not None and best_q_hw is not None and cand_card.q_hw > best_q_hw:
            accepted = True
            if best_lut > 0 and cand_lut > best_lut * 2:
                state.log(f"opt r{rnd}: ACCEPTED Q_HW={cand_card.q_hw:.4f} BUT resources {best_lut}→{cand_lut} LUT (>{2.0}x) — efficiency warning")
            else:
                state.log(f"opt r{rnd}: ACCEPTED ✓ (Q_HW {best_q_hw:.4f}→{cand_card.q_hw:.4f}, lat={lat})")
            best, best_lat, stag = cand, lat, 0
            best_q_hw = cand_card.q_hw
            rejection_feedback = None
            best_synth_result = sr
            if task.requires_cosim:
                best_cosim_latency = getattr(getattr(cosim_result, "cosim", None), "latency_max", None)
            if sr.report:
                best_resources = sr.report.resources
            state.kernel = best
            state.csim_ok = True
            state.synth_ok = True
            state.cosim_ok = True if task.requires_cosim else getattr(state, "cosim_ok", False)
            state.interface_ok = True
            record_synth_gates(state, sr, stage=f"optimize_candidate_{rnd}_accepted")
            if task.requires_cosim and cosim_result is not None:
                record_cosim_gate(state, cosim_result, stage=f"optimize_candidate_{rnd}_accepted",
                                  source_code=cand)
            mark_fully_verified(state)
        else:
            accepted = False
            stag += 1
            if cand_card is not None and sr.report is not None:
                rejected_fingerprints.add(candidate_fingerprint)
                rejection_feedback = _rejection_feedback(cand_card, sr.report, cand, best_q_hw)
            state.log(f"opt r{rnd}: no score-aligned improvement (stag {stag}/{max_stag})")
            if (cand_card is not None and cr.report is not None
                    and _is_minimum_unroll_frontier(best, cand, cand_card, cr.report)):
                minimum_factor_convergence = True
                state.log(f"opt r{rnd}: minimum UNROLL factor=2 already loses Q_HW with loop II=1 — converge")
                break

        if sr is not None and sr.report is not None:
            report = sr.report
            loop_ii = report.loop_metrics[0].get("pipeline_ii") if report.loop_metrics else None
            synth_candidates.append({
                "round": rnd,
                "strategy": search_strategy.get("name") if search_strategy else "sequential_default",
                "latency": report.latency_worst, "top_interval": report.interval_max,
                "loop_ii": loop_ii, "clock_ns": report.clock_period_ns,
                "resources": dict(report.resources),
                "loop_metrics": [dict(lm) for lm in (report.loop_metrics or [])],
                "q_hw_before": old_q_hw,
                "q_hw_after": cand_card.q_hw if cand_card else None,
                "decision": "ACCEPTED" if accepted else "REJECTED",
            })

        if stop_after_first_measured:
            state.log("opt: strategy lane measured one candidate — stop lane")
            break
        if stag >= max_stag:
            state.log(f"opt: converged ({max_stag} stagnant rounds)")
            break

    state.kernel = best
    state.best_latency = best_lat
    state.metadata["resource_history"] = resource_history
    state.metadata["best_q_hw"] = best_q_hw
    state.metadata["semantic_duplicate_skips"] = semantic_duplicate_skips
    state.metadata["semantic_current_best_skips"] = semantic_current_best_skips
    state.metadata["synth_candidates"] = synth_candidates
    state.metadata["ii_resource_intent_rejections"] = ii_resource_intent_rejections
    state.metadata["minimum_factor_convergence"] = minimum_factor_convergence
    state.metadata["cross_strategy_duplicate_skips"] = cross_strategy_duplicate_skips
    state.metadata["search_strategy"] = search_strategy.get("name") if search_strategy else "sequential_default"
    state.metadata["strategy_contract_rejections"] = strategy_contract_rejections
    state.metadata["strategy_contract_rejection_reasons"] = strategy_contract_rejection_reasons
    return state
