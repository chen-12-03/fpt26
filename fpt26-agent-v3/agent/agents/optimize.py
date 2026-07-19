"""OptimizeAgent — report-driven proposals with scorer-aligned selection."""
from __future__ import annotations
import difflib
import re
from typing import Any
from agent.agents.base import RunState
from agent.analysis.action_contract import build_ii_resource_action_contract
from agent.analysis.log_normalizer import LogNormalizer
from agent.analysis.synth_diagnostics import extract_ii_resource_limits
from agent.prompts import SYSTEM, build_prompt
from scoring.scoring_v3 import (
    Anchor,
    QoREvidence,
    TaskScoringConfig,
    ValidityGates,
    verified_available_resources,
)
from scoring.profiles import DEFAULT_SCORING_PROFILE, grade_with_profile

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


def _hls_pragmas(code: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in code.splitlines()
        if re.match(r"^\s*#\s*pragma\s+HLS\b", line, re.IGNORECASE)
    ]


def _strategy_contract_violation(
    best: str,
    candidate: str,
    strategy: dict[str, Any] | None,
) -> str | None:
    """Enforce mutually distinct candidate families before tool spending."""
    if not strategy:
        return None
    name = strategy.get("name")
    best_pragmas = {pragma.lower() for pragma in _hls_pragmas(best)}
    candidate_pragmas = _hls_pragmas(candidate)
    added_pragmas = [
        pragma for pragma in candidate_pragmas
        if pragma.lower() not in best_pragmas
    ]
    source_changed = (
        _without_hls_pragmas_fingerprint(best)
        != _without_hls_pragmas_fingerprint(candidate)
    )

    if name == "conservative_loop_parallelism":
        if source_changed:
            return "conservative lane must preserve non-pragma source"
        if len(added_pragmas) != 1 or not re.search(
            r"\bUNROLL\b", added_pragmas[0], re.IGNORECASE
        ):
            return "conservative lane requires exactly one added UNROLL pragma"
        if re.search(
            r"\b(ARRAY_PARTITION|ARRAY_RESHAPE|PIPELINE)\b",
            added_pragmas[0],
            re.IGNORECASE,
        ):
            return "conservative lane cannot mix banking or pipeline directives"
        return None

    if name == "source_reduction_restructure":
        if added_pragmas:
            return "source-restructure lane cannot add HLS pragmas"
        if not source_changed:
            return "source-restructure lane must change the non-pragma architecture"
        return None

    if name == "speed_first_parallel_architecture":
        if source_changed:
            return None
        unrolls = [
            pragma for pragma in added_pragmas
            if re.search(r"\bUNROLL\b", pragma, re.IGNORECASE)
        ]
        if not unrolls:
            return "speed-first lane requires a distinct parallel architecture"
        for pragma in unrolls:
            factor = re.search(
                r"\bfactor\s*=\s*(\d+)", pragma, re.IGNORECASE
            )
            if factor and int(factor.group(1)) <= 2:
                return "speed-first lane cannot reuse conservative factor<=2"
        return None

    return f"unknown strategy contract: {name}"


def _source_array_rank(code: str, variable: str) -> int | None:
    """Return the largest visible bracket rank for an array identifier."""
    ranks = [
        brackets.count("[")
        for brackets in re.findall(
            rf"\b{re.escape(variable)}\s*((?:\[[^\[\]]*\]\s*)+)",
            code,
        )
    ]
    return max(ranks) if ranks else None


def _ii_resource_intent_feedback(
    synth_result: Any,
    best: str,
    candidate: str,
    action_contract: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Reject pragma-only actions that cannot resolve a measured port limit."""
    limits = extract_ii_resource_limits(
        getattr(synth_result, "log", "") or ""
    )
    if not limits or _without_hls_pragmas_fingerprint(
        best
    ) != _without_hls_pragmas_fingerprint(candidate):
        return None

    best_pragmas = {pragma.lower() for pragma in _hls_pragmas(best)}
    added_pragmas = [
        pragma
        for pragma in _hls_pragmas(candidate)
        if pragma.lower() not in best_pragmas
    ]
    if not added_pragmas:
        return None

    evidence_arrays = {
        limit.array.lower() for limit in limits if limit.array
    }
    banking_actions: list[dict[str, Any]] = []
    recognized_only = True
    for pragma in added_pragmas:
        banking = re.search(
            r"\b(ARRAY_PARTITION|ARRAY_RESHAPE)\b.*?"
            r"\bvariable\s*=\s*([A-Za-z_]\w*)",
            pragma,
            re.IGNORECASE,
        )
        if banking:
            style = re.search(
                r"\b(cyclic|block|complete)\b", pragma, re.IGNORECASE
            )
            factor = re.search(
                r"\bfactor\s*=\s*(\d+)", pragma, re.IGNORECASE
            )
            dimension = re.search(
                r"\bdim\s*=\s*(\d+)", pragma, re.IGNORECASE
            )
            banking_actions.append(
                {
                    "pragma": pragma,
                    "pragma_class": banking.group(1).upper(),
                    "variable": banking.group(2),
                    "style": style.group(1).lower() if style else None,
                    "factor": int(factor.group(1)) if factor else None,
                    "dimension": (
                        int(dimension.group(1)) if dimension else None
                    ),
                }
            )
            continue
        if re.search(r"\b(?:PIPELINE|UNROLL)\b", pragma, re.IGNORECASE):
            continue
        recognized_only = False
        break

    # Preserve an escape hatch for storage directives whose effects this
    # narrow contract cannot prove, and for candidates with real code changes.
    if not recognized_only:
        return None

    contract = action_contract or build_ii_resource_action_contract(
        getattr(synth_result, "log", "") or ""
    )
    contract_violations: list[str] = []
    if contract:
        if len(added_pragmas) != 1:
            contract_violations.append(
                "expected exactly one newly added HLS pragma"
            )
        if len(banking_actions) != 1:
            contract_violations.append(
                "the single action must be ARRAY_PARTITION"
            )
        else:
            action = banking_actions[0]
            variable = action["variable"]
            rank = _source_array_rank(best, variable)
            if action["pragma_class"] != "ARRAY_PARTITION":
                contract_violations.append(
                    "pragma class must be ARRAY_PARTITION"
                )
            if variable.lower() not in evidence_arrays:
                contract_violations.append(
                    f"variable '{variable}' is not a reported target"
                )
            if action["style"] != "cyclic":
                contract_violations.append("partition style must be cyclic")
            if action["factor"] != 2:
                contract_violations.append("partition factor must be 2")
            dimension = action["dimension"]
            if dimension is None:
                contract_violations.append(
                    "partition dim must be explicit and source-supported"
                )
            elif dimension < 1:
                contract_violations.append("partition dim must be positive")
            elif rank is not None and dimension > rank:
                contract_violations.append(
                    f"partition dim={dimension} exceeds visible array rank={rank}"
                )
        if not contract_violations:
            return None
    elif any(
        action["variable"].lower() in evidence_arrays
        for action in banking_actions
    ):
        return None

    evidence = [
        {
            "message_id": "HLS 200-448",
            "ii_lower_bound": limit.lower_bound,
            "operation": limit.operation,
            "array": limit.array,
            "source": limit.source,
            "core": limit.core,
        }
        for limit in limits[:3]
    ]
    arrays = [limit.array for limit in limits if limit.array]
    return {
        "status": "REJECTED_BY_SYNTH_EVIDENCE_INTENT",
        "candidate_pragmas": added_pragmas,
        "unmatched_banking_variables": [
            action["variable"]
            for action in banking_actions
            if action["variable"].lower() not in evidence_arrays
        ],
        "contract_violations": contract_violations,
        "ii_resource_limits": evidence,
        "reason": (
            "The candidate changes only concurrency directives and/or banks "
            "arrays other than the one named by Vitis HLS 200-448. Vitis "
            "already proved which memory ports set the II lower bound, so this "
            "action does not address the measured bottleneck. No candidate "
            "tool was run."
        ),
        "required_next_action": (
            f"Apply exactly one evidence-matched ARRAY_PARTITION cyclic "
            f"factor=2 pragma to reported array(s) {arrays}, with an explicit "
            "dimension no larger than that array's visible source rank; or make "
            "a real code-locality change such as a line buffer/cache that "
            "reduces external reads. Otherwise return the current editable "
            "kernel unchanged to stop."
        ),
    }


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


def _score_candidate(
    task: Any,
    anchor_report: Any,
    candidate_report: Any,
    scoring_profile: str = DEFAULT_SCORING_PROFILE,
) -> Any:
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
        available=verified_available_resources(
            getattr(anchor_report, "available", None)
        ),
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
    return grade_with_profile(
        task_cfg=cfg,
        anchor=anchor,
        evidence=evidence,
        scoring_profile=scoring_profile,
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
    bottleneck = card.bottleneck_resource
    growth = card.growth_by_resource

    # Resource-specific guidance
    resource_hint = ""
    if bottleneck == "DSP" and growth.get("DSP", 1.0) > 2.0:
        resource_hint = (
            f"DSP grew {growth['DSP']:.1f}x — reduce UNROLL/PIPELINE factor "
            "or switch to resource-shared implementation."
        )
    elif bottleneck == "LUT" and growth.get("LUT", 1.0) > 3.0:
        resource_hint = (
            f"LUT grew {growth['LUT']:.1f}x — try smaller UNROLL factor (2 instead of 4+) "
            "or PIPELINE instead of UNROLL to reduce combinational duplication."
        )
    elif bottleneck == "FF" and growth.get("FF", 1.0) > 3.0:
        resource_hint = (
            f"FF grew {growth['FF']:.1f}x — reduce UNROLL factor or ARRAY_PARTITION "
            "factor to lower register count."
        )
    elif bottleneck == "BRAM_18K":
        resource_hint = (
            "BRAM growth detected — reduce ARRAY_PARTITION factor or partition "
            "dimension to lower memory banking cost."
        )

    # Clock degradation check
    cand_clk = getattr(report, "clock_period_ns", None)
    clock_hint = ""
    if cand_clk and cand_clk > 7.0:
        clock_hint = (
            f"Candidate clock={cand_clk:.1f}ns is very slow — the speedup in cycles "
            "may be offset by clock period in effective latency. Try a less aggressive "
            "pipeline/unroll that keeps clock closer to target."
        )

    feedback = {
        "status": "REJECTED_BY_SCORING_V3_Q_HW",
        "candidate_synth": _report(SimpleToolResult(report)),
        "candidate_q_hw": card.q_hw,
        "current_best_q_hw": best_q_hw,
        "candidate_latency_ratio": card.latency_ratio,
        "candidate_area_growth": card.area_growth,
        "bottleneck_resource": bottleneck,
        "growth_by_resource": growth,
        "candidate_pragmas": pragmas,
        "resource_hint": resource_hint,
        "clock_hint": clock_hint,
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
            f"Do not increase or repeat the rejected parallelism factor. "
            f"{resource_hint + ' ' if resource_hint else ''}"
            f"{clock_hint + ' ' if clock_hint else ''}"
            "Remove that pragma class and use a materially different, report-supported "
            "resource-neutral/resource-reducing idea. If no such evidence-based "
            "idea exists, return the current editable kernel unchanged to stop."
        ).strip()
    else:
        feedback["required_next_action"] = (
            f"{resource_hint + ' ' if resource_hint else ''}"
            f"{clock_hint + ' ' if clock_hint else ''}"
            "Remove speculative top-level ARRAY_PARTITION and any function-scope "
            "PIPELINE first. Use a materially different single pragma class. If "
            "no report-supported alternative exists, return the current editable "
            "kernel unchanged to stop."
        ).strip()
    return feedback


def _candidate_diff(best: str, candidate: str, max_chars: int = 4000) -> str:
    """Return a bounded source diff for reflection after tool failure."""
    lines = difflib.unified_diff(
        best.splitlines(),
        candidate.splitlines(),
        fromfile="current_best",
        tofile="failed_candidate",
        n=2,
        lineterm="",
    )
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[: max_chars - 16].rstrip() + "\n... [truncated]"
    return text


def _csim_failure_feedback(result: Any, best: str, candidate: str) -> dict[str, Any]:
    """Build concise compiler/runtime evidence for the next candidate round."""
    phase = getattr(result, "phase", "unknown") or "unknown"
    normalized = LogNormalizer(max_key_lines=8, max_warnings=4).normalize(
        "csim", phase, getattr(result, "log", "") or ""
    )
    status_phase = re.sub(r"[^A-Z0-9]+", "_", phase.upper()).strip("_")
    if phase == "compile_error":
        required_next_action = (
            "Correct the exact compiler error in the failed candidate with the "
            "smallest change (for example, add the required existing header for "
            "an undeclared HLS type). Do not invent another unrelated architecture "
            "before this evidence is resolved. Return current_best unchanged if the "
            "optimization is not justified."
        )
    else:
        required_next_action = (
            "The candidate compiled but failed functional C-simulation. Restore the "
            "current_best behavior and remove the semantic change that caused the "
            "failure; do not repeat the failed candidate. Return current_best "
            "unchanged if no pragma-only correction is justified."
        )
    return {
        "status": f"REJECTED_BY_CSIM_{status_phase or 'UNKNOWN'}",
        "phase": phase,
        "error_summary": normalized.error_summary,
        "key_lines": normalized.key_lines,
        "failed_candidate_diff": _candidate_diff(best, candidate),
        "reason": "The previous optimization candidate failed real C-simulation.",
        "required_next_action": required_next_action,
    }


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
        ii_resource_limits = extract_ii_resource_limits(
            getattr(r, "log", "") or ""
        )
        if ii_resource_limits:
            issues.extend(
                f"Measured loop PipelineII={max(violating_loops)}>1. "
                f"{limit.summary()}"
                for limit in ii_resource_limits[:3]
            )
        else:
            issues.append(
                f"Measured loop PipelineII={max(violating_loops)}>1 — classify the "
                "reported loop violation (recurrence, timing, or memory ports) before "
                "adding a matching directive."
            )
        issues.append(
            "See knowledge pattern 'Pipeline II Violation Resolution' for step-by-step "
            "II fix guidance (memory port → ARRAY_PARTITION, data dependency → restructure, "
            "timing → reduce combinational path)."
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
        loop_detail = ""
        if dominant_loop is not None:
            trip = dominant_loop.get("trip_count") or 0
            lii = dominant_loop.get("pipeline_ii")
            lname = dominant_loop.get("name", "?")
            l_lat = dominant_loop.get("latency") or 0
            loop_detail = (
                f" Dominant loop: {lname} (trip={trip}, latency={l_lat}, "
                f"PipelineII={lii})."
            )
            if lii is not None and lii == 1 and trip > 16:
                issues.append(
                    f"Moderate latency ({lat} cycles).{loop_detail} "
                    f"The loop already achieves PipelineII=1 with trip count {trip}; "
                    "cycles are dominated by the trip count. To reduce latency "
                    "while keeping resource growth minimal, experiment with a "
                    "conservative partial UNROLL factor=2 first — this halves "
                    "the trip count at low cost. If multiple loops exist, target "
                    "only the highest-latency loop."
                )
            elif lii is None and trip > 16:
                issues.append(
                    f"Moderate latency ({lat} cycles).{loop_detail} "
                    f"Loop PipelineII is unavailable (may be unrolled/flattened). "
                    "Try adding PIPELINE II=1 to the innermost loop first, or "
                    "if already pipelined, try a small partial UNROLL factor=2 "
                    "on the dominant loop."
                )
            elif lii is not None and lii > 1:
                issues.append(
                    f"Moderate latency ({lat} cycles).{loop_detail} "
                    f"PipelineII={lii}>1 — there is an II violation. Classify the "
                    "cause (timing, recurrence, or memory ports) before adding "
                    "directives."
                )
            else:
                issues.append(
                    f"Moderate latency ({lat} cycles).{loop_detail} "
                    "The loop has low trip count — latency improvement may be "
                    "limited. Focus on PipelineII optimization if II>1."
                )
        else:
            issues.append(
                f"Moderate latency ({lat} cycles): loop metrics unavailable. "
                "Synthesize first to get loop-level evidence, then target only "
                "the measured bottleneck loop."
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
    lines.append("V9 scoring: equal proportional speedup & resource growth = neutral (Q_HW=0.75).")
    lines.append("Goal: speedup > worst resource growth to exceed baseline.")
    return "\n".join(lines)


class OptimizeAgent:
    """Resource-aware optimization using current scoring_v3 QoR selection."""

    def __init__(
        self,
        llm: Any,
        max_rounds: int = 5,
        scoring_profile: str = DEFAULT_SCORING_PROFILE,
        search_strategy: dict[str, Any] | None = None,
        shared_candidate_fingerprints: set[str] | None = None,
        stop_after_first_measured: bool = False,
    ) -> None:
        self.llm = llm
        self.max_rounds = max_rounds
        self.scoring_profile = scoring_profile
        self.search_strategy = search_strategy
        self.shared_candidate_fingerprints = shared_candidate_fingerprints
        self.stop_after_first_measured = stop_after_first_measured
        self.max_stag = 3  # rounds without Q_HW improvement before converging

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
        synth_candidates: list[dict] = []  # structured candidate records for reporting
        semantic_current_best_skips = 0
        ii_resource_intent_rejections = 0
        minimum_factor_convergence = False
        cross_strategy_duplicate_skips = 0
        strategy_contract_rejections = 0
        strategy_contract_rejection_reasons: list[str] = []

        # Record baseline synth for reporting
        if best_synth_result is not None and best_synth_result.report is not None:
            br = best_synth_result.report
            bl_ii = br.loop_metrics[0].get("pipeline_ii") if br.loop_metrics else None
            synth_candidates.append({
                "round": 0,
                "is_baseline": True,
                "latency": br.latency_worst,
                "top_interval": br.interval_max,
                "loop_ii": bl_ii,
                "clock_ns": br.clock_period_ns,
                "resources": dict(br.resources),
                "loop_metrics": [dict(lm) for lm in (br.loop_metrics or [])],
                "q_hw_before": None,
                "q_hw_after": None,
                "decision": "BASELINE",
            })

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
                current_card = _score_candidate(
                    task, anchor_report, cr.report, self.scoring_profile
                )
                if best_q_hw is None:
                    best_q_hw = current_card.q_hw
                if not best_resources:
                    best_resources = dict(cr.report.resources)

            report_str = _report(cr) if cr.ok else f"SYNTH FAIL: {getattr(cr, 'log', '')[-500:]}"
            if cr.ok and cr.report and anchor_report is not None:
                current_card = _score_candidate(
                    task, anchor_report, cr.report, self.scoring_profile
                )
                report_str += (
                    f" ScoreAligned(Q_HW={current_card.q_hw:.4f}, "
                    f"latency_ratio={current_card.latency_ratio:.2f}x, "
                    f"area_growth={current_card.area_growth:.2f}x, "
                    f"bottleneck={current_card.bottleneck_resource})"
                )
            diag = _diagnose(cr)
            action_contract = build_ii_resource_action_contract(
                getattr(cr, "log", "") or ""
            )
            rsrc_trend = _resource_delta(resource_history)

            state.log(f"opt r{rnd}: lat={best_lat} | {report_str}")
            for line in diag.split("\n"):
                if line.strip():
                    state.log(f"  {line.strip()}")
            if action_contract:
                targets = [
                    target["array"] for target in action_contract["targets"]
                ]
                state.log(
                    f"opt r{rnd}: measured action contract targets={targets}"
                )

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
                action_contract=action_contract,
                search_strategy=self.search_strategy,
            )

            # ── 4. LLM proposes optimization ────────────────────────────
            resp = self.llm.complete(SYSTEM, prompt)
            cand = extract_code(resp)
            if not cand or cand.strip() == best.strip():
                state.log(f"opt r{rnd}: no change — converged")
                break
            candidate_fingerprint = _candidate_fingerprint(cand)
            if candidate_fingerprint == _candidate_fingerprint(best):
                semantic_current_best_skips += 1
                state.log(
                    f"opt r{rnd}: semantic no-op versus current best — "
                    "skip csim/synth"
                )
                if self.search_strategy and rnd < self.max_rounds:
                    rejection_feedback = {
                        "status": "REJECTED_BY_STRATEGY_CONTRACT",
                        "reason": "candidate was a semantic no-op versus the baseline",
                        "required_next_action": (
                            "Stay in the assigned strategy and produce one material, "
                            "contract-compliant candidate."
                        ),
                    }
                    continue
                break
            strategy_violation = _strategy_contract_violation(
                best, cand, self.search_strategy
            )
            if strategy_violation is not None:
                strategy_contract_rejections += 1
                strategy_contract_rejection_reasons.append(strategy_violation)
                state.log(
                    f"opt r{rnd}: strategy contract rejected candidate before tools: "
                    f"{strategy_violation}"
                )
                rejection_feedback = {
                    "status": "REJECTED_BY_STRATEGY_CONTRACT",
                    "reason": strategy_violation,
                    "required_next_action": (
                        "Stay in the assigned search_strategy and correct only this "
                        "contract violation. Do not switch optimization families."
                    ),
                }
                if rnd < self.max_rounds:
                    continue
                break
            if (
                self.shared_candidate_fingerprints is not None
                and candidate_fingerprint in self.shared_candidate_fingerprints
            ):
                semantic_duplicate_skips += 1
                cross_strategy_duplicate_skips += 1
                state.log(
                    f"opt r{rnd}: strategy={self.search_strategy.get('name') if self.search_strategy else 'default'} "
                    "duplicated another strategy candidate — skip tools"
                )
                rejection_feedback = {
                    "status": "REJECTED_BY_STRATEGY_CONTRACT",
                    "reason": "semantic duplicate of another strategy candidate",
                    "required_next_action": (
                        "Produce a materially different candidate within the assigned "
                        "strategy family."
                    ),
                }
                if rnd < self.max_rounds:
                    continue
                break
            if self.shared_candidate_fingerprints is not None:
                self.shared_candidate_fingerprints.add(candidate_fingerprint)
            if candidate_fingerprint in rejected_fingerprints:
                semantic_duplicate_skips += 1
                state.log(
                    f"opt r{rnd}: semantic duplicate of measured rejected "
                    "candidate — skip csim/synth and converge"
                )
                break

            intent_feedback = _ii_resource_intent_feedback(
                cr, best, cand, action_contract
            )
            if intent_feedback is not None:
                ii_resource_intent_rejections += 1
                rejected_fingerprints.add(candidate_fingerprint)
                rejection_feedback = intent_feedback
                state.log(
                    f"opt r{rnd}: pragma-only action conflicts with measured "
                    "HLS 200-448 memory-port limit — skip csim/synth and reflect"
                )
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

            # ── 6. Compare current scoring_v3 hardware quality ──────────
            lat = _latency(sr)
            cand_lut = (sr.report.resources.get('LUT', 0) or 0) if sr.report else 0
            best_lut = best_resources.get('LUT', 0) if best_resources else 0
            cand_card = (
                _score_candidate(
                    task, anchor_report, sr.report, self.scoring_profile
                )
                if anchor_report is not None and sr.report is not None
                else None
            )

            state.log(
                f"opt r{rnd}: lat {best_lat}→{lat} | {_report(sr)} | "
                f"Q_HW {best_q_hw}→{cand_card.q_hw if cand_card else None}"
            )

            old_q_hw = best_q_hw
            if (
                cand_card is not None
                and best_q_hw is not None
                and cand_card.q_hw > best_q_hw
            ):
                accepted = True
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
                accepted = False
                stag += 1
                if cand_card is not None and sr.report is not None:
                    rejected_fingerprints.add(candidate_fingerprint)
                    rejection_feedback = _rejection_feedback(
                        cand_card, sr.report, cand, best_q_hw
                    )
                state.log(
                    f"opt r{rnd}: no score-aligned improvement (stag {stag}/{self.max_stag})"
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

            # Record structured candidate info for reporting
            if sr is not None and sr.report is not None:
                report = sr.report
                loop_ii = None
                if report.loop_metrics:
                    loop_ii = report.loop_metrics[0].get("pipeline_ii")
                entry = {
                    "round": rnd,
                    "strategy": (
                        self.search_strategy.get("name")
                        if self.search_strategy else "sequential_default"
                    ),
                    "latency": report.latency_worst,
                    "top_interval": report.interval_max,
                    "loop_ii": loop_ii,
                    "clock_ns": report.clock_period_ns,
                    "resources": dict(report.resources),
                    "loop_metrics": [
                        dict(lm) for lm in (report.loop_metrics or [])
                    ],
                    "q_hw_before": old_q_hw,
                    "q_hw_after": cand_card.q_hw if cand_card else None,
                    "decision": "ACCEPTED" if accepted else "REJECTED",
                }
                synth_candidates.append(entry)

            if self.stop_after_first_measured:
                state.log("opt: strategy lane measured one candidate — stop lane")
                break

            if stag >= self.max_stag:
                state.log(f"opt: converged ({self.max_stag} stagnant rounds)")
                break

        state.kernel = best
        state.best_latency = best_lat
        state.metadata["resource_history"] = resource_history
        state.metadata["best_q_hw"] = best_q_hw
        state.metadata["semantic_duplicate_skips"] = semantic_duplicate_skips
        state.metadata["semantic_current_best_skips"] = semantic_current_best_skips
        state.metadata["synth_candidates"] = synth_candidates
        state.metadata["ii_resource_intent_rejections"] = (
            ii_resource_intent_rejections
        )
        state.metadata["minimum_factor_convergence"] = minimum_factor_convergence
        state.metadata["cross_strategy_duplicate_skips"] = (
            cross_strategy_duplicate_skips
        )
        state.metadata["search_strategy"] = (
            self.search_strategy.get("name")
            if self.search_strategy else "sequential_default"
        )
        state.metadata["strategy_contract_rejections"] = (
            strategy_contract_rejections
        )
        state.metadata["strategy_contract_rejection_reasons"] = (
            strategy_contract_rejection_reasons
        )
        return state
