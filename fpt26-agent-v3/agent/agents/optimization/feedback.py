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
    if phase == "compile_error":
        constraint = (
            "Roll back the failed candidate and correct only the exact "
            "synthesis compiler diagnostic. Do not repeat the unsupported "
            "construct; return the current best if no supported alternative exists."
        )
    else:
        constraint = (
            "Roll back the exact failed candidate and inspect its synthesis "
            "diagnostics before selecting a response. A changed factor, target, "
            "or architecture is allowed only as a new report/source-supported "
            "hypothesis; otherwise return the current best unchanged."
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


def _interface_gate_feedback(
    validation: dict[str, Any],
    *,
    top_function: str,
) -> dict[str, Any]:
    """Build bounded no-tool feedback after interface validation rejects code."""
    reason = str(validation.get("reason", "interface validation failed") or "")
    diagnostics = validation.get("source_diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    bounded_diagnostics = {
        key: diagnostics.get(key)
        for key in (
            "source_sha256",
            "char_count",
            "line_count",
            "markdown_fence_count",
            "first_markdown_fence_offset",
            "last_markdown_fence_offset",
            "starts_with_markdown_fence",
            "ends_with_markdown_fence",
            "has_top_function_token",
        )
        if key in diagnostics
    }
    required = (
        "No candidate tools were run because the previous source failed the "
        "interface/source-shape gate. Return one complete C/C++ translation "
        "unit inside a cpp fence: preserve all required includes, include the "
        f"exact top function `{top_function}`, keep its signature unchanged, "
        "and ensure all braces and parentheses are balanced."
    )
    if reason == "top_function_missing":
        required += (
            " The previous candidate did not contain the required top function; "
            "do not return only helper functions or a partial rewrite."
        )
    elif reason == "unbalanced_cpp_delimiters":
        required += (
            " The previous candidate had unbalanced delimiters, which often means "
            "the response was partial or truncated; regenerate the full source "
            "from the first include through the final closing brace."
        )
        if bounded_diagnostics.get("has_top_function_token") is False:
            required += (
                " It also lacked the required top-function token, so the next "
                "candidate must include the complete top-level wrapper."
            )
    elif reason == "markdown_fence_in_candidate":
        required += (
            " The extracted candidate still contained markdown fences; put fences "
            "only around the whole response, never inside the source text."
        )

    return {
        "status": "REJECTED_BY_INTERFACE_GATE",
        "reason": reason,
        "top_function": top_function,
        "no_candidate_tools_run": True,
        "source_diagnostics": bounded_diagnostics,
        "required_next_action": required,
    }


def _action_guard_feedback(
    *,
    status: str,
    reason: str,
    candidate_action: dict[str, Any],
    measured_rejected_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Preserve measured anti-repeat history after a pre-tool action rejection."""
    rejected_signatures = [
        str(entry.get("action", entry).get("semantic_signature") or "")
        for entry in measured_rejected_actions
        if isinstance(entry.get("action", entry), dict)
    ]
    candidate_signature = str(
        candidate_action.get("semantic_signature") or ""
    )
    if candidate_signature:
        rejected_signatures.append(candidate_signature)
    return {
        "status": status,
        "reason": reason,
        "no_candidate_tools_run": True,
        "candidate_action": candidate_action,
        "measured_rejected_actions": measured_rejected_actions[-4:],
        "rejected_action_signatures": sorted(
            {value for value in rejected_signatures if value}
        ),
        "required_next_action": (
            "Do not repeat the exact rejected action signature. A different "
            "parameter, target, or architecture is a new hypothesis only when "
            "the current report/source evidence supports it."
        ),
    }


def _parameter_adjustment_hint(card: Any, action: dict[str, Any]) -> str:
    """Suggest which parameter axis to adjust when a candidate fails by area.

    The hint is evidence-driven: it only mentions axes that the rejected
    action touched, so the LLM receives a concrete alternative instead of
    a blanket prohibition.
    """
    parts: list[str] = []
    for pragma in action.get("added_pragmas", []):
        factor_match = re.search(r"\bfactor\s*=\s*(\d+)", pragma, re.IGNORECASE)
        if factor_match and int(factor_match.group(1)) > 2:
            parts.append(
                f"Consider a smaller factor (current={factor_match.group(1)})."
            )
            break
    if not parts:
        for pragma in action.get("added_pragmas", []):
            if re.search(r"\bcomplete\b", pragma, re.IGNORECASE):
                parts.append(
                    "A complete partition/reshape was tried; consider a "
                    "partial (cyclic/block) variant with a smaller factor."
                )
                break
    if not parts and action.get("source_changed"):
        parts.append(
            "The source-level rewrite increased resources. Consider a "
            "pragmatic partial parallelization or a less aggressive unroll."
        )
    if not parts:
        parts.append(
            "The rejected action used parameters that exceeded the resource "
            "budget. Try a more conservative setting."
        )
    return " ".join(parts) + " "


def _rejection_feedback(
    card: Any,
    report: Any,
    candidate: str,
    best_q_hw: float | None = None,
    *,
    candidate_action: dict[str, Any] | None = None,
    measured_rejected_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build concise scorer evidence for the next optimization round."""
    from agent.agents.optimization.diagnostics import _report as _fmt_report
    from agent.agents.optimization.strategies import candidate_action_summary
    from agent.agents.optimize import SimpleToolResult

    pragmas = [l.strip() for l in candidate.splitlines() if "#pragma HLS" in l]
    action = candidate_action or candidate_action_summary("", candidate)
    rejected_actions = list(measured_rejected_actions or [])
    if not rejected_actions:
        rejected_actions.append(
            {
                "action": action,
                "candidate_q_hw": card.q_hw,
                "current_best_q_hw": best_q_hw,
            }
        )
    rejected_signatures = sorted(
        {
            str(entry.get("action", entry).get("semantic_signature") or "")
            for entry in rejected_actions
            if isinstance(entry.get("action", entry), dict)
            and entry.get("action", entry).get("semantic_signature")
        }
    )
    bottleneck = card.bottleneck_resource
    growth = card.growth_by_resource

    resource_hint = (
        "Measured aggregate capacity-normalized resource pressure is "
        f"U_baseline={card.anchor_resource_footprint:.8f}, "
        f"U_candidate={card.candidate_resource_footprint:.8f}, "
        f"area_ratio={card.area_ratio:.3f}x. The largest per-type growth "
        f"diagnostic is {bottleneck}={growth.get(bottleneck, 1.0):.3f}x."
    )

    cand_clk = getattr(report, "clock_period_ns", None)
    clock_hint = (
        f"Measured candidate clock={cand_clk:.3f}ns."
        if isinstance(cand_clk, (int, float))
        else "Candidate clock is unavailable."
    )

    feedback = {
        "status": "REJECTED_BY_SCORING_V3_Q_HW",
        "candidate_synth": _fmt_report(SimpleToolResult(report)),
        "candidate_q_hw": card.q_hw,
        "current_best_q_hw": best_q_hw,
        "candidate_latency_ratio": card.latency_ratio,
        "candidate_area_growth": card.area_growth,
        "candidate_area_ratio": card.area_ratio,
        "anchor_resource_footprint": card.anchor_resource_footprint,
        "candidate_resource_footprint": card.candidate_resource_footprint,
        "bottleneck_resource": bottleneck,
        "growth_by_resource": growth,
        "candidate_pragmas": pragmas,
        "candidate_action": action,
        "measured_rejected_actions": rejected_actions[-4:],
        "rejected_action_signatures": rejected_signatures,
        "anti_repeat_priority": (
            "Measured Q_HW rejection overrides repeated RAG suggestions."
        ),
        "resource_hint": resource_hint,
        "clock_hint": clock_hint,
        "reason": "The candidate did not improve Q_HW over the current best.",
    }
    if card.latency_ratio > 1.0 and card.area_growth > 1.0:
        feedback["directional_constraint"] = (
            "For this exact candidate, measured speedup was outweighed by "
            "aggregate capacity-normalized resource growth. Do not extrapolate "
            "this result to an entire family without another measurement."
        )
        # Give the LLM a directional hint: when area exploded,
        # try a smaller factor, a different dimension, or a different
        # resource class rather than giving up on the family entirely.
        factor_hint = _parameter_adjustment_hint(card, action)
        feedback["required_next_action"] = (
            "Do not repeat the exact rejected action signature. "
            f"{resource_hint} {clock_hint} "
            f"{factor_hint}"
            "A changed parameter, target, or architecture must state a new "
            "report/source-supported hypothesis and be measured independently."
        ).strip()
    else:
        feedback["required_next_action"] = (
            f"{resource_hint} {clock_hint} Do not repeat the exact rejected "
            "action signature. Any next hypothesis must be report/source-supported "
            "and measured independently."
        ).strip()
    return feedback
