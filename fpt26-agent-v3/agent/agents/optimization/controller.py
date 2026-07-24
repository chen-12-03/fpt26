"""Optimization controller — the main optimization loop extracted from OptimizeAgent."""

from __future__ import annotations

import hashlib
import os
from typing import Any

from agent.agents.base import RunState
from agent.analysis.action_contract import build_ii_resource_action_contract
from agent.analysis.source_metadata import (
    bounded_metadata_payload,
    extract_design_metadata,
)
from agent.candidate.validator import (
    extract_code,
    mark_fully_verified,
    record_cosim_gate,
    record_synth_gates,
    validate_candidate,
)
from agent.knowledge import (
    KnowledgeQuery,
    baseline_qor_from_report,
    format_for_prompt,
    prompt_token_upper_bound,
    resource_headroom_from_report,
    retrieve_knowledge,
)
from agent.prompts import SYSTEM, build_prompt
from agent.validation import can_afford_validation
from scoring.profiles import DEFAULT_SCORING_PROFILE

from agent.agents.optimization.diagnostics import _diagnose, _latency, _report, _resource_delta
from agent.agents.optimization.feedback import (
    OptimizationFailure,
    _csim_failure_feedback,
    _rejection_feedback,
    build_synth_failure,
    merge_optimization_failure,
)
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
    _top_function_inline_noop,
    candidate_action_summary,
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
    optimization_failures: list[OptimizationFailure] = []
    knowledge_retrievals: list[dict[str, Any]] = []
    phase1_ab_baseline = (
        os.environ.get("FPT26_QOR_RAG_AB_BASELINE", "").strip() == "1"
    )
    state.metadata["qor_rag_mode"] = (
        "phase1_keyword_ab_baseline"
        if phase1_ab_baseline
        else "phase2a_hybrid"
    )

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

        # ── 2. Structured source evidence and knowledge retrieval ───
        source_metadata = bounded_metadata_payload(
            extract_design_metadata(
                best,
                loop_metrics=(
                    getattr(getattr(cr, "report", None), "loop_metrics", None)
                    or []
                ),
            )
        )
        know = ""
        try:
            if phase1_ab_baseline:
                from agent.legacy_knowledge import (
                    format_for_prompt as legacy_format,
                    lookup_patterns as legacy_lookup,
                )

                legacy_matches = legacy_lookup(task.description or "")
                know = legacy_format(legacy_matches)
                knowledge_retrievals.append(
                    {
                        "round": rnd,
                        "mode": "phase1_keyword_ab_baseline",
                        "entry_ids": [
                            str(match.get("family", ""))
                            for match in legacy_matches
                        ],
                        "prompt_chars": len(know),
                    }
                )
            else:
                history: list[Any] = [
                    failure.to_dict() for failure in optimization_failures
                ]
                if rejection_feedback:
                    history.append(rejection_feedback)
                query = KnowledgeQuery(
                    source_metadata=source_metadata,
                    baseline_qor=baseline_qor_from_report(
                        getattr(cr, "report", None),
                        q_hw=best_q_hw,
                        bottleneck=(
                            getattr(current_card, "bottleneck_resource", "")
                            if cr.ok
                            and cr.report
                            and anchor_report is not None
                            else ""
                        ),
                    ),
                    synth_diagnostics={
                        "summary": diag,
                        "measured_action_contract": action_contract or {},
                    },
                    resource_headroom=resource_headroom_from_report(
                        getattr(cr, "report", None)
                    ),
                    history=history,
                    description=task.description or "",
                    target_part=str(getattr(task, "part", "") or ""),
                    vitis_version=_task_preflight_vitis_version(state),
                )
                matches = retrieve_knowledge(query)
                from agent.legacy_knowledge import (
                    format_for_prompt as legacy_format,
                    lookup_patterns as legacy_lookup,
                )

                legacy_matches = legacy_lookup(task.description or "")
                if _prefer_legacy_specialist(
                    legacy_matches, task.description or ""
                ):
                    specialist_matches = legacy_matches[:1]
                    measured_matches = [
                        entry for entry in matches if entry.kind != "rule"
                    ]
                    know = legacy_format(specialist_matches)
                    measured_know = format_for_prompt(measured_matches)
                    if measured_know:
                        know += "\n\n## Compatible measured cases\n" + measured_know
                    knowledge_retrievals.append(
                        {
                            "round": rnd,
                            "mode": "phase2a_legacy_specialist_fallback",
                            "query_signature": query.signature(),
                            "entry_ids": [
                                str(match.get("family", ""))
                                for match in specialist_matches
                            ]
                            + [entry.id for entry in measured_matches],
                            "structured_candidate_ids": [
                                entry.id for entry in matches
                            ],
                            "prompt_chars": len(know),
                            "prompt_token_upper_bound": (
                                prompt_token_upper_bound(know)
                            ),
                            "sources": ["agent.legacy_knowledge"]
                            + [entry.source for entry in measured_matches],
                        }
                    )
                else:
                    know = format_for_prompt(matches)
                    knowledge_retrievals.append(
                        {
                            "round": rnd,
                            "mode": "phase2a_structured",
                            "query_signature": query.signature(),
                            "entry_ids": [entry.id for entry in matches],
                            "entry_kinds": [entry.kind for entry in matches],
                            "prompt_chars": len(know),
                            "prompt_token_upper_bound": (
                                prompt_token_upper_bound(know)
                            ),
                            "sources": [entry.source for entry in matches],
                        }
                    )
            if know:
                state.log(
                    f"opt r{rnd}: QoR knowledge "
                    f"mode={state.metadata['qor_rag_mode']}"
                )
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
            design_metadata=source_metadata,
        )

        # ── 4. LLM proposes optimization ────────────────────────────
        resp = llm.complete(SYSTEM, prompt)
        cand = extract_code(resp)
        if not cand or cand.strip() == best.strip():
            state.log(f"opt r{rnd}: no change — converged")
            break
        candidate_fingerprint = _candidate_fingerprint(cand)
        candidate_action = candidate_action_summary(best, cand)
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
        if _top_function_inline_noop(best, cand, task.top):
            semantic_current_best_skips += 1
            state.log(
                f"opt r{rnd}: INLINE on top function {task.top} is a "
                "deterministic no-op — skip tools and converge"
            )
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
            rejected_fingerprints.add(candidate_fingerprint)
            fingerprint_digest = hashlib.sha256(
                candidate_fingerprint.encode("utf-8", errors="replace")
            ).hexdigest()
            synth_failure = build_synth_failure(
                sr,
                best,
                cand,
                candidate_fingerprint=fingerprint_digest,
            )
            optimization_failures = merge_optimization_failure(
                optimization_failures, synth_failure, max_entries=3
            )
            rejection_feedback = optimization_failures[-1].to_dict()
            state.log(
                f"opt r{rnd}: synth FAIL — discard and reflect "
                f"(repeat={optimization_failures[-1].repetition_count})"
            )
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
                "action": candidate_action,
                "source_metadata": source_metadata,
                "latency": report.latency_worst, "top_interval": report.interval_max,
                "loop_ii": loop_ii, "clock_ns": report.clock_period_ns,
                "resources": dict(report.resources),
                "loop_metrics": [dict(lm) for lm in (report.loop_metrics or [])],
                "q_hw_before": old_q_hw,
                "q_hw_after": cand_card.q_hw if cand_card else None,
                "decision": "ACCEPTED" if accepted else "REJECTED",
                "validation": {
                    "interface_ok": True,
                    "csim_ok": True,
                    "synth_ok": True,
                    "frequency_ok": True,
                    "resource_ok": True,
                    "cosim_required": bool(task.requires_cosim),
                    "cosim_ok": (
                        bool(getattr(cosim_result, "ok", False))
                        if task.requires_cosim
                        else None
                    ),
                },
            })

        if stop_after_first_measured:
            state.log("opt: strategy lane measured one candidate — stop lane")
            break
        if accepted and not phase1_ab_baseline and state.metadata.get(
            "task_preflight"
        ):
            state.metadata["qor_rag_early_success_stop"] = {
                "round": rnd,
                "q_hw_before": old_q_hw,
                "q_hw_after": best_q_hw,
                "reason": "first_fully_verified_q_hw_improvement",
            }
            state.log(
                "opt: QoR-RAG measured a fully verified Q_HW improvement "
                "— preserve it and stop"
            )
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
    state.metadata["optimization_failures"] = [
        failure.to_dict() for failure in optimization_failures
    ]
    state.metadata["knowledge_retrievals"] = knowledge_retrievals
    return state


def _prefer_legacy_specialist(
    legacy_matches: list[dict[str, Any]], description: str
) -> bool:
    """Keep proven Phase-1 specialists when the new seed is less specific."""

    if not legacy_matches:
        return False
    family = str(legacy_matches[0].get("family", ""))
    lowered = description.lower()
    if family == "CORDIC / Trigonometric Optimization":
        return any(
            token in lowered
            for token in ("cordic", "trigonometric", "sine", "cosine")
        )
    if family == "Reduction / Single-Loop Pipeline":
        explicit_dot_product = (
            "dotproduct" in lowered or "dot product" in lowered
        )
        specialist_signal = any(
            token in lowered
            for token in (
                "popcount",
                "accumulate",
                "accumulation",
                "reduction",
                "cumulative sum",
            )
        )
        return specialist_signal and not explicit_dot_product
    return False


def _task_preflight_vitis_version(state: RunState) -> str:
    """Return the observed/preflight Vitis version using real report keys."""

    preflight = state.metadata.get("task_preflight", {})
    if not isinstance(preflight, dict):
        return ""
    for key in (
        "observed_vitis_version",
        "required_vitis_version",
        "preflight_vitis_version",
        "vitis_version",
    ):
        value = str(preflight.get(key, "") or "").strip()
        if value:
            return value
    return ""
