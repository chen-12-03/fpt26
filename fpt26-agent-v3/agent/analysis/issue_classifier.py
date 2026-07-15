from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.analysis.log_normalizer import NormalizedLog
from llm4hls.tools import ToolResult


ISSUE_CATEGORIES = (
    "correct_unoptimized",
    "compile_failure",
    "synth_failure",
    "csim_failure",
    "cosim_failure",
    "structural_failure",
    "timeout",
    "budget_exceeded",
    "unknown",
)


@dataclass(frozen=True)
class IssueClassification:
    condition: str
    issue_category: str
    stage: str | None
    confidence: str
    evidence: list[str]
    recommended_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "issue_category": self.issue_category,
            "stage": self.stage,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "recommended_action": self.recommended_action,
        }


class IssueClassifier:
    def classify(self, result: ToolResult, normalized_log: NormalizedLog) -> IssueClassification:
        # ToolResult uses 'kind' (csim/synth/cosim) and 'phase' (pass/compile_error/...)
        stage = getattr(result, "kind", None) or "unknown"
        phase = getattr(result, "phase", None) or "unknown"
        summary = getattr(result, "brief", lambda: "")() if callable(getattr(result, "brief", None)) else ""
        evidence = normalized_log.key_lines[:5]
        searchable = "\n".join([summary, *normalized_log.key_lines]).lower()

        if phase == "budget_exceeded" or "budgetexceeded" in searchable or "budget" in phase:
            return self._make("budget_exceeded", stage, "high", evidence or [summary], "stop_or_raise_budget")

        if normalized_log.missing_logs and phase != "pass":
            return self._make("unknown", stage, "low", ["tool log is missing"], "collect_tool_log")

        if stage == "cosim" and phase != "pass":
            if (phase == "timeout" or "timeout" in searchable or "timed out" in searchable) and _has_structural_signal(
                searchable
            ):
                return self._make("structural_failure", stage, "medium", evidence, "debug_dataflow_or_streaming")
            if phase == "timeout" or "timeout" in searchable or "timed out" in searchable:
                return self._make("timeout", stage, "high", evidence or [summary], "inspect_timeout_or_reduce_scope")
            if _has_structural_signal(searchable):
                return self._make("structural_failure", stage, "high", evidence, "debug_dataflow_or_streaming")
            return self._make("cosim_failure", stage, "medium", evidence, "inspect_cosim_failure")

        if phase == "timeout" or "timeout" in searchable or "timed out" in searchable:
            return self._make("timeout", stage, "high", evidence or [summary], "inspect_timeout_or_reduce_scope")

        if stage == "csim" and phase != "pass":
            if phase == "compile_error" or _has_compile_signal(searchable):
                return self._make("compile_failure", stage, "high", evidence, "repair_compile_error")
            if _has_mismatch_signal(searchable):
                return self._make("csim_failure", stage, "high", evidence, "repair_functional_mismatch")
            return self._make("csim_failure", stage, "medium", evidence, "repair_functional_failure")

        if stage == "synth" and phase != "pass":
            return self._make("synth_failure", stage, "high", evidence, "repair_synthesizability")

        return self._make("unknown", stage, "low", evidence, "inspect_task_goal")

    def _make(
        self,
        category: str,
        stage: str | None,
        confidence: str,
        evidence: list[str],
        recommended_action: str,
    ) -> IssueClassification:
        return IssueClassification(
            condition=category,
            issue_category=category,
            stage=stage,
            confidence=confidence,
            evidence=evidence,
            recommended_action=recommended_action,
        )


def _has_compile_signal(text: str) -> bool:
    return bool(
        re.search(r"\b(error:|fatal error|undefined reference|no such file|compile_error|compilation failed)\b", text)
    )


def _has_mismatch_signal(text: str) -> bool:
    return bool(re.search(r"\b(mismatch|expected|actual|wrong answer|output differs|runtime_fail)\b", text))


def _has_structural_signal(text: str) -> bool:
    return bool(re.search(r"\b(deadlock|dataflow|stream|fifo|channel|protocol|underflow|overflow|blocked|stall)\b", text))
