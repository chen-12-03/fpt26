from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.analysis.log_normalizer import NormalizedLog
from agent.execution.result_adapter import UnifiedToolResult


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
    def classify(self, result: UnifiedToolResult, normalized_log: NormalizedLog) -> IssueClassification:
        stage = result.stage
        status = result.status
        evidence = normalized_log.key_lines[:5]
        searchable = "\n".join([result.summary, *normalized_log.key_lines]).lower()

        if status == "budget_exceeded" or "budgetexceeded" in searchable or "budget" in status:
            return self._make("budget_exceeded", stage, "high", evidence or [result.summary], "stop_or_raise_budget")

        if status == "timeout" or "timeout" in searchable or "timed out" in searchable:
            return self._make("timeout", stage, "high", evidence or [result.summary], "inspect_timeout_or_reduce_scope")

        if normalized_log.missing_logs and status != "pass":
            return self._make("unknown", stage, "low", ["tool log is missing"], "collect_tool_log")

        if stage == "cosim" and status != "pass":
            if _has_structural_signal(searchable):
                return self._make("structural_failure", stage, "high", evidence, "debug_dataflow_or_streaming")
            return self._make("cosim_failure", stage, "medium", evidence, "inspect_cosim_failure")

        if stage == "csim" and status != "pass":
            if status == "compile_error" or _has_compile_signal(searchable):
                return self._make("compile_failure", stage, "high", evidence, "repair_compile_error")
            if _has_mismatch_signal(searchable):
                return self._make("csim_failure", stage, "high", evidence, "repair_functional_mismatch")
            return self._make("csim_failure", stage, "medium", evidence, "repair_functional_failure")

        if stage == "synth" and status != "pass":
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
    return bool(re.search(r"\b(deadlock|dataflow|stream|fifo|channel|cosim deadlock)\b", text))
