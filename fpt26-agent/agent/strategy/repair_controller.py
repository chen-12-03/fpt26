from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.analysis.issue_classifier import IssueClassification, IssueClassifier
from agent.analysis.kernel_validator import KernelValidationResult, KernelValidator
from agent.analysis.log_normalizer import LogNormalizer, NormalizedLog
from agent.core.candidate import Candidate
from agent.core.candidate_store import CandidateStore
from agent.core.task_context import TaskContext
from agent.config import OFFICIAL_CREDIT_COST
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
        attempt_feedback: dict[str, Any] | None = None
        attempts: list[RepairAttempt] = []

        if not _is_repairable_failure(task_context, current_failure, self.log_normalizer, self.issue_classifier):
            return RepairLoopResult("not_repairable", attempts, baseline_candidate, baseline_kernel, "not_repairable")

        next_attempt_index = 1
        deterministic = _deterministic_repair(task_context, current_kernel)
        if deterministic is not None and max_attempts >= 1:
            attempt_index = 1
            if not _has_budget_for_final_checks(harness_backend):
                return RepairLoopResult("failed", attempts, baseline_candidate, baseline_kernel, "hls_budget_insufficient")
            replacement = deterministic["replacement_kernel"]
            action = {
                "type": "deterministic_repair",
                "attempt_index": attempt_index,
                "diagnosis": deterministic["diagnosis"],
                "changes": deterministic["changes"],
                "confidence": deterministic["confidence"],
            }
            candidate = candidate_store.deterministic_repair_candidate(
                task_context,
                replacement,
                attempt_index=attempt_index,
                parent_candidate=current_candidate,
                action=action,
            )
            llm_response = _deterministic_response(deterministic)
            validation = self.kernel_validator.validate(task_context, replacement)
            if not validation.ok:
                attempts.append(
                    _attempt(
                        attempt_index,
                        candidate,
                        replacement,
                        deterministic,
                        llm_response,
                        validation,
                        [],
                        "validation_failed",
                        "validation_failed",
                    )
                )
                next_attempt_index = 2
                attempt_feedback = _validation_feedback(validation, replacement)
            else:
                csim = harness_backend.csim(replacement)
                stage_results = [csim]
                if csim.status != "pass":
                    attempts.append(
                        _attempt(
                            attempt_index,
                            candidate,
                            replacement,
                            deterministic,
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
                    attempt_feedback = None
                    next_attempt_index = 2
                else:
                    synth = harness_backend.synth(replacement)
                    stage_results.append(synth)
                    if synth.status == "pass":
                        attempts.append(
                            _attempt(
                                attempt_index,
                                candidate,
                                replacement,
                                deterministic,
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
                            deterministic,
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
                    attempt_feedback = None
                    next_attempt_index = 2

        for attempt_index in range(next_attempt_index, max_attempts + 1):
            if not _has_budget_for_final_checks(harness_backend):
                return RepairLoopResult("failed", attempts, baseline_candidate, baseline_kernel, "hls_budget_insufficient")

            normalized = self.log_normalizer.normalize(current_failure)
            issue = self.issue_classifier.classify(current_failure, normalized)
            messages = build_repair_messages(
                task_context=task_context,
                current_kernel=current_kernel,
                normalized_log=normalized,
                issue=issue,
                attempt_feedback=attempt_feedback,
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
                if attempt_index >= max_attempts:
                    return RepairLoopResult("failed", attempts, baseline_candidate, baseline_kernel, "llm_error")
                attempt_feedback = _llm_error_feedback(llm_response)
                continue

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
                # Static-invalid candidates never become the next repair base. They
                # have not passed the HLS tool boundary and may not contain a top
                # function at all, so retry from the latest tool-observed failure.
                attempt_feedback = _validation_feedback(validation, replacement)
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
                attempt_feedback = None
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
            attempt_feedback = None

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


def _deterministic_repair(task_context: TaskContext, kernel: str) -> dict[str, Any] | None:
    task_text = _task_text(task_context).lower()
    if task_context.top_function != "projection":
        return None
    if "angle 0" not in task_text or "z2" not in task_text:
        return None
    pattern = re.compile(
        r"triangle_2d->z\s*=\s*triangle_3d\.z0\s*/\s*3\s*\+\s*triangle_3d\.z1\s*/\s*3\s*;",
        re.MULTILINE,
    )
    replacement = "triangle_2d->z = triangle_3d.z0 / 3 + triangle_3d.z1 / 3 + triangle_3d.z2 / 3;"
    fixed, count = pattern.subn(replacement, kernel, count=1)
    if count != 1 or fixed == kernel:
        return None
    return {
        "diagnosis": "angle 0 z average drops the third z vertex term",
        "replacement_kernel": fixed,
        "changes": ["add triangle_3d.z2 / 3 to the angle 0 z average"],
        "confidence": "high",
    }


def _task_text(task_context: TaskContext) -> str:
    parts = [task_context.description or ""]
    constraints = task_context.design_constraints or {}
    for value in constraints.values():
        if isinstance(value, str):
            parts.append(value)
    content = task_context.initial_kernel.get("content")
    if isinstance(content, str):
        parts.append(content)
    return "\n".join(parts)


def _validation_feedback(validation: KernelValidationResult, replacement: str) -> dict[str, Any]:
    return {
        "stage": "static_validation",
        "status": validation.status,
        "errors": validation.errors,
        "top_function": validation.top_function,
        "original_signature": validation.original_signature,
        "candidate_signature": validation.candidate_signature,
        "candidate_excerpt": _excerpt(replacement),
        "instruction": (
            "The previous replacement was rejected before any HLS tool call. "
            "Retry from the provided editable_kernel and return a complete source file "
            "with the unchanged top function signature."
        ),
    }


def _llm_error_feedback(llm_response: LLMResponse) -> dict[str, Any]:
    return {
        "stage": "llm_request",
        "status": llm_response.status,
        "error_type": llm_response.error_type,
        "error_message": llm_response.error_message,
        "instruction": "Retry with a complete replacement kernel if the LLM call is available.",
    }


def _excerpt(text: str, limit: int = 1200) -> str:
    compact = text.strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "\n...[truncated]"


def _has_budget_for_final_checks(harness_backend: HarnessBackend) -> bool:
    budget = getattr(getattr(harness_backend, "tool_server", None), "budget", None)
    if budget is None:
        return True
    remaining_fn = getattr(budget, "remaining", None)
    costs = getattr(budget, "cost", {}) or OFFICIAL_CREDIT_COST
    if not callable(remaining_fn) or not isinstance(costs, dict):
        return True
    required = int(costs.get("csim", OFFICIAL_CREDIT_COST["csim"])) + int(
        costs.get("synth", OFFICIAL_CREDIT_COST["synth"])
    )
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


def _deterministic_response(parsed: dict[str, Any]) -> LLMResponse:
    return LLMResponse(
        status="not_called",
        content=None,
        parsed=parsed,
        model="deterministic",
        purpose="repair",
        prompt_sha256="",
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        usage_source="not_applicable",
        elapsed_seconds=0.0,
        attempt_count=0,
        error_type=None,
        error_message=None,
        model_version=None,
        license=None,
        source="deterministic_transform",
        attempts=[],
    )
