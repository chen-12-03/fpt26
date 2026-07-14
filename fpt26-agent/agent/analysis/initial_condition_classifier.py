from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from agent.analysis.issue_classifier import IssueClassification, IssueClassifier
from agent.analysis.log_normalizer import LogNormalizer
from agent.core.task_context import TaskContext
from agent.execution.result_adapter import UnifiedToolResult


@dataclass(frozen=True)
class InitialCondition:
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


class InitialConditionClassifier:
    def __init__(
        self,
        *,
        log_normalizer: LogNormalizer | None = None,
        issue_classifier: IssueClassifier | None = None,
    ) -> None:
        self.log_normalizer = log_normalizer or LogNormalizer()
        self.issue_classifier = issue_classifier or IssueClassifier()

    def classify(
        self,
        task_context: TaskContext,
        results: Iterable[UnifiedToolResult],
    ) -> InitialCondition:
        result_list = list(results)
        if not result_list:
            return self._unknown("no tool results available", "run_csim")

        classifications: list[IssueClassification] = []
        for result in result_list:
            normalized = self.log_normalizer.normalize(result)
            issue = self.issue_classifier.classify(result, normalized)
            classifications.append(issue)

        for category in (
            "budget_exceeded",
            "timeout",
            "compile_failure",
            "structural_failure",
            "csim_failure",
            "synth_failure",
            "cosim_failure",
        ):
            for issue in classifications:
                if issue.issue_category == category:
                    return InitialCondition(**issue.to_dict())

        stages = {result.stage: result.status for result in result_list}
        if (
            task_context.task_type == "optimize"
            and stages.get("csim") == "pass"
            and stages.get("synth") == "pass"
        ):
            return InitialCondition(
                condition="correct_unoptimized",
                issue_category="correct_unoptimized",
                stage="synth",
                confidence="high",
                evidence=["csim passed", "synth passed", "task_type=optimize"],
                recommended_action="optimize_ppa",
            )

        if any(result.status == "pass" for result in result_list):
            return self._unknown("passing tools do not determine initial condition", "run_next_required_tool")
        return self._unknown("no deterministic issue category matched", "inspect_logs")

    def _unknown(self, evidence: str, action: str) -> InitialCondition:
        return InitialCondition(
            condition="unknown",
            issue_category="unknown",
            stage=None,
            confidence="low",
            evidence=[evidence],
            recommended_action=action,
        )
