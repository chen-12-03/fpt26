"""Structured feedback builders — pure functions, no LLM calls, no state mutation."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, replace
from typing import Any

from agent.analysis.issue_classifier import IssueClassifier
from agent.analysis.log_normalizer import LogNormalizer


@dataclass(frozen=True)
class OptimizationFailure:
    """Bounded, serializable evidence from one failed optimization synth."""

    stage: str
    phase: str
    failure_category: str
    error_summary: str | None
    key_diagnostic_lines: list[str]
    candidate_fingerprint: str
    candidate_action_diff_summary: str
    implicated: dict[str, list[str]]
    recommended_next_constraint: str
    repetition_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        status_phase = re.sub(
            r"[^A-Z0-9]+", "_", self.phase.upper()
        ).strip("_")
        return {
            "status": f"REJECTED_BY_SYNTH_{status_phase or 'UNKNOWN'}",
            "stage": self.stage,
            "phase": self.phase,
            "failure_category": self.failure_category,
            "error_summary": self.error_summary,
            "key_diagnostic_lines": list(self.key_diagnostic_lines),
            "candidate_fingerprint": self.candidate_fingerprint,
            "candidate_action_diff_summary": self.candidate_action_diff_summary,
            "implicated": {
                key: list(values)
                for key, values in sorted(self.implicated.items())
            },
            "recommended_next_constraint": self.recommended_next_constraint,
            "required_next_action": self.recommended_next_constraint,
            "repetition_count": self.repetition_count,
            "reason": (
                "The previous optimization candidate failed real synthesis. "
                "Do not repeat the same candidate or failure pattern."
            ),
        }


def _implicated_source_elements(
    result: Any, candidate_diff: str
) -> dict[str, list[str]]:
    added = [
        line[1:].strip()
        for line in candidate_diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    pragmas: list[str] = []
    for line in added:
        match = re.search(
            r"#\s*pragma\s+HLS\b.*$", line, re.IGNORECASE
        )
        if match:
            pragmas.append(re.sub(r"\s+", " ", match.group(0)))
    pragmas = sorted(set(pragmas))[:8]
    arrays: set[str] = set()
    loops: set[str] = set()
    evidence = "\n".join(
        [candidate_diff, str(getattr(result, "log", "") or "")]
    )
    for match in re.finditer(
        r"\bvariable\s*=\s*([A-Za-z_]\w*)", evidence, re.IGNORECASE
    ):
        arrays.add(match.group(1))
    for match in re.finditer(
        r"\barray\s+['\"]?([A-Za-z_]\w*)", evidence, re.IGNORECASE
    ):
        arrays.add(match.group(1))
    for line in added:
        label = re.search(r"\b([A-Za-z_]\w*)\s*:\s*for\s*\(", line)
        if label:
            loops.add(label.group(1))
    for match in re.finditer(
        r"\bloop\s+['\"]?([A-Za-z_]\w*)", evidence, re.IGNORECASE
    ):
        loops.add(match.group(1))
    return {
        "pragmas": pragmas,
        "loops": sorted(loops)[:8],
        "arrays": sorted(arrays)[:8],
    }


def build_synth_failure(
    result: Any,
    best: str,
    candidate: str,
    *,
    candidate_fingerprint: str,
) -> OptimizationFailure:
    """Build one bounded synth-failure record without invoking an LLM."""
    phase = str(getattr(result, "phase", "unknown") or "unknown")
    normalized = LogNormalizer(
        max_summary_chars=360,
        max_line_chars=180,
        max_key_lines=6,
        max_warnings=4,
    ).normalize("synth", phase, getattr(result, "log", "") or "")
    issue = IssueClassifier().classify(result, normalized)
    candidate_diff = _candidate_diff(best, candidate)
    implicated = _implicated_source_elements(result, candidate_diff)
    has_factor = any(
        re.search(r"\bfactor\s*=\s*\d+", pragma, re.IGNORECASE)
        for pragma in implicated["pragmas"]
    )
    if has_factor:
        constraint = (
            "Roll back the failed candidate, reduce factor before any retry, "
            "and do not repeat the same pragma combination. If synthesis "
            "evidence does not justify a smaller factor, avoid this pattern."
        )
    elif phase == "compile_error":
        constraint = (
            "Roll back the failed candidate and correct only the exact "
            "synthesis compiler diagnostic. Do not repeat the unsupported "
            "construct; return the current best if no supported alternative exists."
        )
    else:
        constraint = (
            "Roll back the failed candidate and avoid the implicated pattern. "
            "Use a materially different report-supported action, or return the "
            "current best unchanged."
        )
    return OptimizationFailure(
        stage="synth",
        phase=phase,
        failure_category=issue.issue_category,
        error_summary=normalized.error_summary,
        key_diagnostic_lines=list(normalized.key_lines),
        candidate_fingerprint=str(candidate_fingerprint)[:64],
        candidate_action_diff_summary=candidate_diff,
        implicated=implicated,
        recommended_next_constraint=constraint,
    )


def _failure_signature(failure: OptimizationFailure) -> tuple[str, str, str]:
    summary = re.sub(
        r"\b\d+\b", "<n>", (failure.error_summary or "").lower()
    )
    summary = re.sub(r"\s+", " ", summary).strip()
    return failure.stage, failure.failure_category, summary


def merge_optimization_failure(
    history: list[OptimizationFailure],
    failure: OptimizationFailure,
    *,
    max_entries: int = 3,
) -> list[OptimizationFailure]:
    """Aggregate equal fingerprints/patterns and retain newest bounded history."""
    retained = list(history)
    match_index: int | None = None
    for index, prior in enumerate(retained):
        if (
            prior.candidate_fingerprint == failure.candidate_fingerprint
            or _failure_signature(prior) == _failure_signature(failure)
        ):
            match_index = index
            break
    if match_index is not None:
        prior = retained.pop(match_index)
        failure = replace(
            failure, repetition_count=prior.repetition_count + 1
        )
    retained.append(failure)
    return retained[-max(1, int(max_entries)) :]


def _candidate_diff(best: str, candidate: str, max_chars: int = 1600) -> str:
    """Return a bounded source diff for reflection after tool failure."""
    lines = difflib.unified_diff(
        best.splitlines(), candidate.splitlines(),
        fromfile="current_best", tofile="failed_candidate", n=2, lineterm="",
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


def _rejection_feedback(
    card: Any, report: Any, candidate: str, best_q_hw: float | None = None,
) -> dict[str, Any]:
    """Build concise scorer evidence for the next optimization round."""
    from agent.agents.optimization.diagnostics import _report as _fmt_report
    from agent.agents.optimize import SimpleToolResult

    pragmas = [l.strip() for l in candidate.splitlines() if "#pragma HLS" in l]
    bottleneck = card.bottleneck_resource
    growth = card.growth_by_resource

    resource_hint = ""
    if bottleneck == "DSP" and growth.get("DSP", 1.0) > 2.0:
        resource_hint = f"DSP grew {growth['DSP']:.1f}x — reduce UNROLL/PIPELINE factor."
    elif bottleneck == "LUT" and growth.get("LUT", 1.0) > 3.0:
        resource_hint = f"LUT grew {growth['LUT']:.1f}x — try smaller UNROLL factor."
    elif bottleneck == "FF" and growth.get("FF", 1.0) > 3.0:
        resource_hint = f"FF grew {growth['FF']:.1f}x — reduce UNROLL or ARRAY_PARTITION factor."
    elif bottleneck == "BRAM_18K":
        resource_hint = "BRAM growth detected — reduce ARRAY_PARTITION factor."

    cand_clk = getattr(report, "clock_period_ns", None)
    clock_hint = ""
    if cand_clk and cand_clk > 7.0:
        clock_hint = f"Candidate clock={cand_clk:.1f}ns is very slow."

    feedback = {
        "status": "REJECTED_BY_SCORING_V3_Q_HW",
        "candidate_synth": _fmt_report(SimpleToolResult(report)),
        "candidate_q_hw": card.q_hw,
        "current_best_q_hw": best_q_hw,
        "candidate_latency_ratio": card.latency_ratio,
        "candidate_area_growth": card.area_growth,
        "bottleneck_resource": bottleneck,
        "growth_by_resource": growth,
        "candidate_pragmas": pragmas,
        "resource_hint": resource_hint,
        "clock_hint": clock_hint,
        "reason": "The candidate did not improve Q_HW over the current best.",
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
