"""OptimizeAgent — report-driven proposals with scorer-aligned selection."""
from __future__ import annotations
import re
from typing import Any
from agent.agents.base import RunState
from agent.prompts import SYSTEM, build_prompt
from scoring.scoring_v3 import (
    Anchor,
    QoREvidence,
    TaskScoringConfig,
    ValidityGates,
    grade as v3_grade,
)

_CODE_RE = re.compile(r"```(?:cpp|c\+\+|c)?\s*\n(.*?)```", re.DOTALL)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

def extract_code(text: str) -> str | None:
    blocks = _CODE_RE.findall(text)
    return (blocks[0].strip() + "\n") if blocks else (text.strip() + "\n" if text.strip() else None)


def _candidate_fingerprint(code: str) -> str:
    """Normalize comments and layout before comparing measured candidates.

    This deliberately stops short of rewriting C/C++ expressions: it catches
    repeated model responses whose only changes are comments, blank lines, or
    indentation without risking equivalence claims for different programs.
    """
    without_blocks = _BLOCK_COMMENT_RE.sub("", code)
    normalized = []
    for line in without_blocks.splitlines():
        line = line.split("//", 1)[0]
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            normalized.append(line)
    return "\n".join(normalized)


def _without_hls_pragmas_fingerprint(code: str) -> str:
    """Normalize source while omitting standalone HLS directive lines."""
    without_blocks = _BLOCK_COMMENT_RE.sub("", code)
    normalized = []
    for line in without_blocks.splitlines():
        line = line.split("//", 1)[0]
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if re.match(r"^#\s*pragma\s+HLS\b", line, re.IGNORECASE):
            continue
        normalized.append(line)
    return "\n".join(normalized)


def _is_minimum_unroll_frontier(
    best: str,
    candidate: str,
    card: Any,
    best_report: Any,
) -> bool:
    """Return true when factor=2 is the only measured program change.

    Factor 2 is the smallest non-noop partial unroll.  If a long loop already
    has measured PipelineII=1 and that minimum parallel step loses Q_HW because
    resource growth outweighs speedup, increasing the same class has no smaller
    frontier point to explore.  Other code changes/directives keep reflection.
    """
    pragmas = [
        line.strip()
        for line in candidate.splitlines()
        if re.search(r"#\s*pragma\s+HLS\b", line, re.IGNORECASE)
    ]
    if len(pragmas) != 1 or not re.search(
        r"\bUNROLL\b.*\bfactor\s*=\s*2\b", pragmas[0], re.IGNORECASE
    ):
        return False
    if _without_hls_pragmas_fingerprint(best) != _without_hls_pragmas_fingerprint(
        candidate
    ):
        return False
    loop_iis = [
        loop.get("pipeline_ii")
        for loop in (getattr(best_report, "loop_metrics", None) or [])
        if loop.get("pipeline_ii") is not None
    ]
    return bool(
        loop_iis
        and all(ii == 1 for ii in loop_iis)
        and card.latency_ratio > 1.0
        and card.area_growth > 1.0
    )

def _latency(r: Any) -> int | None:
    if not r or not r.report:
        return None
    return r.report.latency_worst or r.report.latency_avg


def _report_latency(report: Any) -> int | None:
    if report is None:
        return None
    if report.latency_worst is not None:
        return report.latency_worst
    return report.latency_avg


def _score_candidate(task: Any, anchor_report: Any, candidate_report: Any) -> Any:
    """Evaluate visible synth QoR through the current authoritative scorer.

    This is an optimization-time proxy only: C-sim and synthesis have already
    passed, while hidden gates are still re-run by ``step_score``.  Comparing
    ``q_hw`` with cost/time held equal prevents cycle-only acceptance from
    selecting candidates that lose badly on clock period or resource growth.
    """
    cfg = TaskScoringConfig(
        task_id=task.id,
        task_type=task.type,
        difficulty=task.difficulty,
        requires_cosim=task.requires_cosim,
        budget_limit=task.budget,
        task_clock_ns=task.clock_ns,
    )
    anchor = Anchor(
        source="starter",
        valid=True,
        latency=_report_latency(anchor_report),
        ii=anchor_report.interval_max,
        clock_ns=anchor_report.clock_period_ns or task.clock_ns,
        resources=dict(anchor_report.resources),
        available={},
    )
    evidence = QoREvidence(
        candidate_latency=_report_latency(candidate_report),
        candidate_ii=candidate_report.interval_max,
        candidate_clock_ns=candidate_report.clock_period_ns or task.clock_ns,
        candidate_resources=dict(candidate_report.resources),
    )
    gates = ValidityGates(
        hidden_csim_pass=True,
        hidden_cosim_pass=True if task.requires_cosim else None,
        synth_pass=True,
        resource_capacity_pass=True,
    )
    return v3_grade(
        task_cfg=cfg,
        anchor=anchor,
        evidence=evidence,
        cost_spent=0,
        wall_time_s=0.0,
        gates=gates,
    )


def _rejection_feedback(
    card: Any,
    report: Any,
    candidate: str,
    best_q_hw: float | None = None,
) -> dict[str, Any]:
    """Build concise scorer evidence for the next optimization round."""
    pragmas = [
        line.strip()
        for line in candidate.splitlines()
        if "#pragma HLS" in line
    ]
    feedback = {
        "status": "REJECTED_BY_SCORING_V3_Q_HW",
        "candidate_synth": _report(SimpleToolResult(report)),
        "candidate_q_hw": card.q_hw,
        "current_best_q_hw": best_q_hw,
        "candidate_latency_ratio": card.latency_ratio,
        "candidate_area_growth": card.area_growth,
        "bottleneck_resource": card.bottleneck_resource,
        "growth_by_resource": card.growth_by_resource,
        "candidate_pragmas": pragmas,
        "reason": (
            "The candidate did not improve Q_HW over the current best. "
            "Do not repeat the same pragma set or architecture."
        ),
    }
    if card.latency_ratio > 1.0 and card.area_growth > 1.0:
        feedback["directional_constraint"] = (
            "The measured speedup was outweighed by worst-resource growth. "
            "Increasing any UNROLL or ARRAY_PARTITION factor from this candidate "
            "moves in the wrong direction and is forbidden."
        )
        feedback["required_next_action"] = (
            "Do not increase or repeat the rejected parallelism factor. Remove "
            "that pragma class and use a materially different, report-supported "
            "resource-neutral/resource-reducing idea. If no such evidence-based "
            "idea exists, return the current editable kernel unchanged to stop."
        )
    else:
        feedback["required_next_action"] = (
            "Remove speculative top-level ARRAY_PARTITION and any function-scope "
            "PIPELINE first. Use a materially different single pragma class. If "
            "no report-supported alternative exists, return the current editable "
            "kernel unchanged to stop."
        )
    return feedback


class SimpleToolResult:
    """Minimal adapter allowing synthesis-report formatting without a tool call."""

    def __init__(self, report: Any) -> None:
        self.report = report


def _latest_successful_synth(results: list[Any]) -> Any | None:
    """Return the newest reusable synthesis result already in the transcript."""
    for result in reversed(results):
        if (
            getattr(result, "kind", None) == "synth"
            and getattr(result, "ok", False)
            and getattr(result, "report", None) is not None
        ):
            return result
    return None

def _report(r: Any) -> str:
    if not r or not r.report:
        return "no report"
    rp = r.report
    loop_text = ", ".join(
        f"{loop.get('name', '?')}(trip={loop.get('trip_count')},"
        f"lat={loop.get('latency')},II={loop.get('pipeline_ii')})"
        for loop in (getattr(rp, "loop_metrics", None) or [])
    ) or "none"
    return (
        f"Clk={rp.clock_period_ns}ns Lat={rp.latency_worst or '?'} "
        f"TopInterval={rp.interval_max or '?'} "
        f"Pipeline={getattr(rp, 'pipeline_type', None) or '?'} "
        f"Loops=[{loop_text}] "
        f"LUT={rp.resources.get('LUT','?')} FF={rp.resources.get('FF','?')} "
        f"DSP={rp.resources.get('DSP','?')} BRAM={rp.resources.get('BRAM_18K','?')}"
    )

def _diagnose(r: Any) -> str:
    """Report-driven bottleneck diagnosis from synthesis report metrics."""
    if not r or not r.report:
        return "No synth data available. Run synthesis first."

    rp = r.report
    issues: list[str] = []

    # 1. Loop II analysis.  Overall Interval is the top-function transaction
    # interval and must not be mistaken for a loop's achieved PipelineII.
    top_interval = rp.interval_max or 0
    loop_metrics = getattr(rp, "loop_metrics", None) or []
    loop_iis = [
        loop.get("pipeline_ii")
        for loop in loop_metrics
        if loop.get("pipeline_ii") is not None
    ]
    violating_loops = [ii for ii in loop_iis if ii > 1]
    if violating_loops:
        issues.append(
            f"Measured loop PipelineII={max(violating_loops)}>1 — classify the "
            "reported loop violation (recurrence, timing, or memory ports) before "
            "adding a matching directive."
        )
    elif loop_iis:
        issues.append(
            f"Measured loop PipelineII={max(loop_iis)} is already optimal. "
            f"TopInterval={top_interval} is the function transaction interval, "
            "not evidence of a loop-II or memory-port problem."
        )
    elif top_interval > 1:
        issues.append(
            f"TopInterval={top_interval} is function-level; loop PipelineII is "
            "unavailable (the loop hierarchy may have been flattened/unrolled). "
            "Do not infer memory-port pressure from TopInterval alone."
        )

    # 2. Latency analysis
    lat = rp.latency_worst or rp.latency_avg or 0
    dominant_loop = max(
        loop_metrics,
        key=lambda loop: loop.get("latency") or 0,
        default=None,
    )
    if (
        lat > 500
        and dominant_loop is not None
        and dominant_loop.get("pipeline_ii") == 1
        and (dominant_loop.get("trip_count") or 0) > 32
    ):
        issues.append(
            f"High latency is dominated by {dominant_loop.get('name')} "
            f"(trip={dominant_loop.get('trip_count')}, "
            f"lat={dominant_loop.get('latency')}, PipelineII=1). Do NOT add "
            "PIPELINE or speculative top-array partitioning. First try only "
            "a conservative partial UNROLL factor=2 inside that loop body; keep "
            "top-level arrays unpartitioned unless Vitis reports a memory-port "
            "violation. Put loop directives immediately after the loop's opening "
            "brace: function-scope PIPELINE can flatten/auto-unroll a long loop."
        )
    elif lat > 1000:
        issues.append(
            f"High latency ({lat} cycles): identify the dominant loop from "
            "loop-level evidence before selecting PIPELINE, UNROLL, or banking."
        )
    elif lat > 100:
        issues.append(
            f"Moderate latency ({lat} cycles): change only the measured "
            "bottleneck loop; do not assume it lacks pipelining."
        )

    # 3. Resource imbalance
    lut = rp.resources.get('LUT', 0) or 0
    ff = rp.resources.get('FF', 0) or 0
    dsp = rp.resources.get('DSP', 0) or 0

    if ff > 0 and lut > 100 and ff / max(lut, 1) > 5:
        issues.append(
            f"FF/LUT={ff/max(lut,1):.1f}x — over-unrolling. Reduce UNROLL factor or use PIPELINE."
        )
    if dsp > 0 and lut > 1000 and dsp > lut * 0.5:
        issues.append(f"High DSP ({dsp}) vs LUT ({lut}) — consider resource sharing.")

    # 4. Timing
    clock = rp.clock_period_ns or 5.0
    if hasattr(rp, 'timing_slack_ns') and rp.timing_slack_ns is not None:
        slack = rp.timing_slack_ns
        if slack < 0:
            issues.append(f"NEGATIVE slack ({slack:.2f}ns) at {clock}ns clock.")
        elif slack < clock * 0.1:
            issues.append(f"Tight slack ({slack:.2f}ns) — near timing limit.")

    if not issues:
        issues.append(
            "No obvious bottleneck. II=1 may already be achieved. "
            "Try DATAFLOW or consider optimization complete."
        )

    return "\n".join(f"• {i}" for i in issues)


def _resource_delta(history: list[dict]) -> str:
    """Summarize resource trend across rounds."""
    if len(history) < 2:
        return ""
    first = history[0]
    last = history[-1]
    lines = ["Resource trend (first→last):"]
    for key in ("LUT", "FF", "DSP", "BRAM_18K"):
        fv = first.get(key, 0) or 0
        lv = last.get(key, 0) or 0
        if fv > 0:
            change = (lv - fv) / fv * 100
            arrow = "↑" if change > 5 else ("↓" if change < -5 else "→")
            lines.append(f"  {key}: {fv} → {lv} ({change:+.0f}% {arrow})")
        elif lv > 0:
            lines.append(f"  {key}: 0 → {lv} (NEW)")
    lines.append("Goal: >2x speedup with <2x resource growth.")
    return "\n".join(lines)


class OptimizeAgent:
    """Resource-aware optimization using current scoring_v3 QoR selection."""

    def __init__(self, llm: Any, max_rounds: int = 5) -> None:
        self.llm = llm
        self.max_rounds = max_rounds

    def run(self, state: RunState) -> RunState:
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
        best_synth_result = _latest_successful_synth(state.results)
        rejected_fingerprints: set[str] = set()
        semantic_duplicate_skips = 0
        minimum_factor_convergence = False

        for rnd in range(1, self.max_rounds + 1):
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
                current_card = _score_candidate(task, anchor_report, cr.report)
                if best_q_hw is None:
                    best_q_hw = current_card.q_hw
                if not best_resources:
                    best_resources = dict(cr.report.resources)

            report_str = _report(cr) if cr.ok else f"SYNTH FAIL: {getattr(cr, 'log', '')[-500:]}"
            if cr.ok and cr.report and anchor_report is not None:
                current_card = _score_candidate(task, anchor_report, cr.report)
                report_str += (
                    f" ScoreAligned(Q_HW={current_card.q_hw:.4f}, "
                    f"latency_ratio={current_card.latency_ratio:.2f}x, "
                    f"area_growth={current_card.area_growth:.2f}x, "
                    f"bottleneck={current_card.bottleneck_resource})"
                )
            diag = _diagnose(cr)
            rsrc_trend = _resource_delta(resource_history)

            state.log(f"opt r{rnd}: lat={best_lat} | {report_str}")
            for line in diag.split("\n"):
                if line.strip():
                    state.log(f"  {line.strip()}")

            # ── 2. Knowledge lookup ─────────────────────────────────────
            know = ""
            try:
                from agent.knowledge import lookup_patterns, format_for_prompt
                m = lookup_patterns(task.description or "")
                know = format_for_prompt(m) if m else ""
                if know:
                    state.log(f"opt r{rnd}: knowledge ×{len(m)} patterns")
            except Exception:
                pass

            # ── 3. Build prompt ─────────────────────────────────────────
            prompt = build_prompt(
                task=task,
                current_kernel=best,
                best_latency=best_lat,
                csim_result="PASS",
                synth_result=report_str,
                bottleneck_hint=diag,
                knowledge_hint=know,
                resource_delta=rsrc_trend,
                rejection_feedback=rejection_feedback,
            )

            # ── 4. LLM proposes optimization ────────────────────────────
            resp = self.llm.complete(SYSTEM, prompt)
            cand = extract_code(resp)
            if not cand or cand.strip() == best.strip():
                state.log(f"opt r{rnd}: no change — converged")
                break
            candidate_fingerprint = _candidate_fingerprint(cand)
            if candidate_fingerprint in rejected_fingerprints:
                semantic_duplicate_skips += 1
                state.log(
                    f"opt r{rnd}: semantic duplicate of measured rejected "
                    "candidate — skip csim/synth and converge"
                )
                break

            # ── 5. Validate: csim → synth ──────────────────────────────
            cs = server.csim(cand)
            state.results.append(cs)
            if not cs.ok:
                state.log(f"opt r{rnd}: csim FAIL — discard")
                stag += 1
                continue

            sr = server.synth(cand)
            state.results.append(sr)
            if not sr.ok:
                state.log(f"opt r{rnd}: synth FAIL — discard")
                stag += 1
                continue

            # ── 6. Compare current scoring_v3 hardware quality ──────────
            lat = _latency(sr)
            cand_lut = (sr.report.resources.get('LUT', 0) or 0) if sr.report else 0
            best_lut = best_resources.get('LUT', 0) if best_resources else 0
            cand_card = (
                _score_candidate(task, anchor_report, sr.report)
                if anchor_report is not None and sr.report is not None
                else None
            )

            state.log(
                f"opt r{rnd}: lat {best_lat}→{lat} | {_report(sr)} | "
                f"Q_HW {best_q_hw}→{cand_card.q_hw if cand_card else None}"
            )

            if (
                cand_card is not None
                and best_q_hw is not None
                and cand_card.q_hw > best_q_hw
            ):
                # Check resource efficiency
                if best_lut > 0 and cand_lut > best_lut * 2:
                    state.log(
                        f"opt r{rnd}: ACCEPTED Q_HW={cand_card.q_hw:.4f} BUT resources {best_lut}→{cand_lut} LUT "
                        f"(>{2.0}x) — efficiency warning"
                    )
                else:
                    state.log(
                        f"opt r{rnd}: ACCEPTED ✓ "
                        f"(Q_HW {best_q_hw:.4f}→{cand_card.q_hw:.4f}, lat={lat})"
                    )
                best, best_lat, stag = cand, lat, 0
                best_q_hw = cand_card.q_hw
                rejection_feedback = None
                best_synth_result = sr
                if sr.report:
                    best_resources = sr.report.resources
            else:
                stag += 1
                if cand_card is not None and sr.report is not None:
                    rejected_fingerprints.add(candidate_fingerprint)
                    rejection_feedback = _rejection_feedback(
                        cand_card, sr.report, cand, best_q_hw
                    )
                state.log(
                    f"opt r{rnd}: no score-aligned improvement (stag {stag}/2)"
                )
                if (
                    cand_card is not None
                    and cr.report is not None
                    and _is_minimum_unroll_frontier(
                        best, cand, cand_card, cr.report
                    )
                ):
                    minimum_factor_convergence = True
                    state.log(
                        f"opt r{rnd}: minimum UNROLL factor=2 already loses "
                        "Q_HW with loop II=1 — converge before another API round"
                    )
                    break

            if stag >= 2:
                state.log("opt: converged (2 stagnant rounds)")
                break

        state.kernel = best
        state.best_latency = best_lat
        state.metadata["resource_history"] = resource_history
        state.metadata["best_q_hw"] = best_q_hw
        state.metadata["semantic_duplicate_skips"] = semantic_duplicate_skips
        state.metadata["minimum_factor_convergence"] = minimum_factor_convergence
        return state
