from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.analysis.issue_classifier import IssueClassification, IssueClassifier
from agent.analysis.kernel_validator import KernelValidationResult, KernelValidator
from agent.analysis.log_normalizer import LogNormalizer, NormalizedLog
from agent.core.candidate import Candidate
from agent.core.candidate_store import CandidateStore
from agent.core.task_context import TaskContext
from agent.execution.harness_backend import HarnessBackend
from agent.execution.result_adapter import UnifiedToolResult
from agent.llm.llm_client import LLMClient
from agent.llm.prompts import REPAIR_RESPONSE_SCHEMA, build_repair_messages
from agent.llm.schemas import LLMResponse


@dataclass(frozen=True)
class RepairAttempt:
    attempt_index: int
    candidate: Candidate | None
    replacement_kernel: str | None
    diagnosis: str | None
    changes: list[str]
    confidence: str | None
    prompt_sha256: str | None
    llm_response: LLMResponse
    llm_call_record: dict[str, Any] | None
    validation_result: KernelValidationResult | None
    stage_results: list[UnifiedToolResult]
    status: str
    stop_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_index": self.attempt_index,
            "candidate": self.candidate.to_dict() if self.candidate is not None else None,
            "replacement_kernel": self.replacement_kernel,
            "diagnosis": self.diagnosis,
            "changes": list(self.changes),
            "confidence": self.confidence,
            "prompt_sha256": self.prompt_sha256,
            "llm_response": self.llm_response.to_dict(),
            "llm_call_record": self.llm_call_record,
            "validation_result": self.validation_result.to_dict() if self.validation_result is not None else None,
            "stage_results": [result.to_dict() for result in self.stage_results],
            "status": self.status,
            "stop_reason": self.stop_reason,
        }


@dataclass(frozen=True)
class RepairLoopResult:
    status: str
    attempts: list[RepairAttempt]
    selected_candidate: Candidate
    final_kernel: str
    stop_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "selected_candidate": self.selected_candidate.to_dict(),
            "final_kernel": self.final_kernel,
            "stop_reason": self.stop_reason,
        }


class RepairController:
    def __init__(
        self,
        *,
        log_normalizer: LogNormalizer | None = None,
        issue_classifier: IssueClassifier | None = None,
        kernel_validator: KernelValidator | None = None,
    ) -> None:
        self.log_normalizer = log_normalizer or LogNormalizer()
        self.issue_classifier = issue_classifier or IssueClassifier()
        self.kernel_validator = kernel_validator or KernelValidator()

    def repair(
        self,
        task_context: TaskContext,
        baseline_candidate: Candidate,
        failure_result: UnifiedToolResult,
        harness_backend: HarnessBackend,
        llm_client: LLMClient,
        candidate_store: CandidateStore,
        max_attempts: int = 2,
    ) -> RepairLoopResult:
        baseline_kernel = _initial_kernel(task_context)
        current_kernel = baseline_kernel
        current_candidate = baseline_candidate
        current_failure = failure_result
        attempts: list[RepairAttempt] = []

        if not _is_repairable_failure(task_context, current_failure, self.log_normalizer, self.issue_classifier):
            return RepairLoopResult("not_repairable", attempts, baseline_candidate, baseline_kernel, "not_repairable")

        for attempt_index in range(1, max_attempts + 1):
            if not _has_budget_for_final_checks(harness_backend):
                return RepairLoopResult("failed", attempts, baseline_candidate, baseline_kernel, "hls_budget_insufficient")

            normalized = self.log_normalizer.normalize(current_failure)
            issue = self.issue_classifier.classify(current_failure, normalized)
            messages = build_repair_messages(
                task_context=task_context,
                current_kernel=current_kernel,
                normalized_log=normalized,
                issue=issue,
            )
            llm_response = llm_client.generate(
                messages,
                response_schema=REPAIR_RESPONSE_SCHEMA,
                purpose="repair",
            )
            if llm_response.status != "ok":
                attempts.append(
                    _llm_error_attempt(
                        attempt_index=attempt_index,
                        llm_response=llm_response,
                        stop_reason=llm_response.error_type or "llm_error",
                    )
                )
                return RepairLoopResult("failed", attempts, baseline_candidate, baseline_kernel, "llm_error")

            parsed = llm_response.parsed
            replacement = parsed["replacement_kernel"]
            action = {
                "type": "llm_repair",
                "attempt_index": attempt_index,
                "diagnosis": parsed["diagnosis"],
                "changes": parsed["changes"],
                "confidence": parsed["confidence"],
            }
            candidate = candidate_store.repair_candidate(
                task_context,
                replacement,
                attempt_index=attempt_index,
                parent_candidate=current_candidate,
                action=action,
            )
            validation = self.kernel_validator.validate(task_context, replacement)
            if not validation.ok:
                attempts.append(
                    _attempt(
                        attempt_index,
                        candidate,
                        replacement,
                        parsed,
                        llm_response,
                        validation,
                        [],
                        "validation_failed",
                        "validation_failed",
                    )
                )
                current_candidate = candidate
                current_kernel = replacement
                continue

            csim = harness_backend.csim(replacement)
            stage_results = [csim]
            if csim.status != "pass":
                attempts.append(
                    _attempt(
                        attempt_index,
                        candidate,
                        replacement,
                        parsed,
                        llm_response,
                        validation,
                        stage_results,
                        "csim_failed",
                        "csim_failed",
                    )
                )
                current_failure = csim
                current_candidate = candidate
                current_kernel = replacement
                continue

            synth = harness_backend.synth(replacement)
            stage_results.append(synth)
            if synth.status == "pass":
                attempts.append(
                    _attempt(
                        attempt_index,
                        candidate,
                        replacement,
                        parsed,
                        llm_response,
                        validation,
                        stage_results,
                        "repaired",
                        "repair_succeeded",
                    )
                )
                return RepairLoopResult("repaired", attempts, candidate, replacement, "repair_succeeded")

            attempts.append(
                _attempt(
                    attempt_index,
                    candidate,
                    replacement,
                    parsed,
                    llm_response,
                    validation,
                    stage_results,
                    "synth_failed",
                    "synth_failed",
                )
            )
            current_failure = synth
            current_candidate = candidate
            current_kernel = replacement

        return RepairLoopResult("failed", attempts, baseline_candidate, baseline_kernel, "max_attempts_exhausted")


def _is_repairable_failure(
    task_context: TaskContext,
    result: UnifiedToolResult,
    normalizer: LogNormalizer,
    classifier: IssueClassifier,
) -> bool:
    if task_context.task_type not in {"repair", "generate", "unknown"}:
        return False
    if result.stage != "csim" or result.status == "pass":
        return False
    issue = classifier.classify(result, normalizer.normalize(result))
    return issue.issue_category in {"csim_failure", "compile_failure"}


def _has_budget_for_final_checks(harness_backend: HarnessBackend) -> bool:
    budget = getattr(getattr(harness_backend, "tool_server", None), "budget", None)
    if budget is None:
        return True
    remaining_fn = getattr(budget, "remaining", None)
    costs = getattr(budget, "cost", {}) or {}
    if not callable(remaining_fn) or not isinstance(costs, dict):
        return True
    required = int(costs.get("csim", 1)) + int(costs.get("synth", 4))
    try:
        return remaining_fn() >= required
    except Exception:
        return True


def _initial_kernel(task_context: TaskContext) -> str:
    content = task_context.initial_kernel.get("content")
    if isinstance(content, str):
        return content
    raise ValueError("TaskContext initial_kernel content is required for repair")


def _attempt(
    attempt_index: int,
    candidate: Candidate,
    replacement: str,
    parsed: dict[str, Any],
    llm_response: LLMResponse,
    validation: KernelValidationResult,
    stage_results: list[UnifiedToolResult],
    status: str,
    stop_reason: str,
) -> RepairAttempt:
    return RepairAttempt(
        attempt_index=attempt_index,
        candidate=candidate,
        replacement_kernel=replacement,
        diagnosis=parsed.get("diagnosis"),
        changes=list(parsed.get("changes", [])),
        confidence=parsed.get("confidence"),
        prompt_sha256=llm_response.prompt_sha256,
        llm_response=llm_response,
        llm_call_record=llm_response.attempts[-1].to_dict() if llm_response.attempts else None,
        validation_result=validation,
        stage_results=stage_results,
        status=status,
        stop_reason=stop_reason,
    )


def _llm_error_attempt(
    *,
    attempt_index: int,
    llm_response: LLMResponse,
    stop_reason: str,
) -> RepairAttempt:
    return RepairAttempt(
        attempt_index=attempt_index,
        candidate=None,
        replacement_kernel=None,
        diagnosis=None,
        changes=[],
        confidence=None,
        prompt_sha256=llm_response.prompt_sha256,
        llm_response=llm_response,
        llm_call_record=llm_response.attempts[-1].to_dict() if llm_response.attempts else None,
        validation_result=None,
        stage_results=[],
        status="llm_error",
        stop_reason=stop_reason,
    )
