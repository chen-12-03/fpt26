from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any

from agent.analysis.cosim_analyzer import CoSimAnalyzer, CoSimDiagnosis
from agent.analysis.kernel_validator import KernelValidationResult, KernelValidator
from agent.analysis.log_normalizer import LogNormalizer
from agent.analysis.stream_analyzer import StreamAnalysis, StreamAnalyzer
from agent.core.candidate import Candidate
from agent.core.candidate_store import CandidateStore
from agent.core.task_context import TaskContext
from agent.execution.harness_backend import HarnessBackend
from agent.execution.result_adapter import UnifiedToolResult
from agent.llm.llm_client import LLMClient
from agent.llm.prompts import STRUCTURAL_REPAIR_RESPONSE_SCHEMA, build_structural_repair_messages
from agent.llm.schemas import LLMResponse


STRUCTURAL_REPAIR_CATEGORIES = {
    "deadlock",
    "stream_underflow",
    "stream_overflow",
    "producer_consumer_mismatch",
    "protocol_error",
}


@dataclass(frozen=True)
class StructuralRepairAttempt:
    attempt_index: int
    candidate: Candidate | None
    replacement_kernel: str | None
    diagnosis: str | None
    repair_strategy: str | None
    affected_streams: list[str]
    changes: list[str]
    confidence: str | None
    prompt_sha256: str | None
    llm_response: LLMResponse
    llm_call_record: dict[str, Any] | None
    validation_result: KernelValidationResult | None
    stream_analysis: StreamAnalysis | None
    stage_results: list[UnifiedToolResult]
    cosim_diagnosis: CoSimDiagnosis | None
    diff_patch: str
    selection_status: str
    status: str
    stop_reason: str | None
    budget_before: int | None
    budget_after: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_index": self.attempt_index,
            "candidate": self.candidate.to_dict() if self.candidate is not None else None,
            "replacement_kernel": self.replacement_kernel,
            "diagnosis": self.diagnosis,
            "repair_strategy": self.repair_strategy,
            "affected_streams": list(self.affected_streams),
            "changes": list(self.changes),
            "confidence": self.confidence,
            "prompt_sha256": self.prompt_sha256,
            "llm_response": self.llm_response.to_dict(),
            "llm_call_record": self.llm_call_record,
            "validation_result": self.validation_result.to_dict() if self.validation_result is not None else None,
            "stream_analysis": self.stream_analysis.to_dict() if self.stream_analysis is not None else None,
            "stage_results": [result.to_dict() for result in self.stage_results],
            "cosim_diagnosis": self.cosim_diagnosis.to_dict() if self.cosim_diagnosis is not None else None,
            "diff_patch": self.diff_patch,
            "selection_status": self.selection_status,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "budget_before": self.budget_before,
            "budget_after": self.budget_after,
        }


@dataclass(frozen=True)
class StructuralRepairResult:
    status: str
    attempts: list[StructuralRepairAttempt]
    selected_candidate: Candidate
    final_kernel: str
    baseline_cosim_diagnosis: CoSimDiagnosis
    final_cosim_diagnosis: CoSimDiagnosis
    stop_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "selected_candidate": self.selected_candidate.to_dict(),
            "final_kernel": self.final_kernel,
            "baseline_cosim_diagnosis": self.baseline_cosim_diagnosis.to_dict(),
            "final_cosim_diagnosis": self.final_cosim_diagnosis.to_dict(),
            "stop_reason": self.stop_reason,
        }


class StructuralRepairController:
    def __init__(
        self,
        *,
        stream_analyzer: StreamAnalyzer | None = None,
        kernel_validator: KernelValidator | None = None,
        cosim_analyzer: CoSimAnalyzer | None = None,
        log_normalizer: LogNormalizer | None = None,
        safety_margin: int = 1,
    ) -> None:
        self.stream_analyzer = stream_analyzer or StreamAnalyzer()
        self.kernel_validator = kernel_validator or KernelValidator()
        self.cosim_analyzer = cosim_analyzer or CoSimAnalyzer()
        self.log_normalizer = log_normalizer or LogNormalizer()
        self.safety_margin = safety_margin

    def repair(
        self,
        task_context: TaskContext,
        baseline_candidate: Candidate,
        baseline_cosim_result: UnifiedToolResult,
        cosim_diagnosis: CoSimDiagnosis,
        harness_backend: HarnessBackend,
        llm_client: LLMClient,
        candidate_store: CandidateStore,
        max_attempts: int = 2,
    ) -> StructuralRepairResult:
        baseline_kernel = _initial_kernel(task_context)
        current_kernel = baseline_kernel
        current_candidate = baseline_candidate
        current_diagnosis = cosim_diagnosis
        attempts: list[StructuralRepairAttempt] = []

        if not _is_structural_repairable(task_context, baseline_cosim_result, cosim_diagnosis):
            return StructuralRepairResult(
                "not_repairable",
                attempts,
                baseline_candidate,
                baseline_kernel,
                cosim_diagnosis,
                cosim_diagnosis,
                "not_repairable",
            )

        for attempt_index in range(1, max_attempts + 1):
            budget_before = _budget_remaining(harness_backend)
            budget_summary = _budget_summary(harness_backend, self.safety_margin)
            if not budget_summary["can_attempt"]:
                return StructuralRepairResult(
                    "failed",
                    attempts,
                    baseline_candidate,
                    baseline_kernel,
                    cosim_diagnosis,
                    current_diagnosis,
                    "hls_budget_insufficient",
                )

            stream_analysis = self.stream_analyzer.analyze(task_context, current_kernel)
            messages = build_structural_repair_messages(
                task_context=task_context,
                current_kernel=current_kernel,
                stream_analysis=stream_analysis,
                cosim_diagnosis=current_diagnosis,
                budget_summary=budget_summary,
            )
            llm_response = llm_client.generate(
                messages,
                response_schema=STRUCTURAL_REPAIR_RESPONSE_SCHEMA,
                purpose="structural_repair",
            )
            if llm_response.status != "ok":
                attempts.append(
                    _llm_error_attempt(
                        attempt_index=attempt_index,
                        llm_response=llm_response,
                        stream_analysis=stream_analysis,
                        stop_reason=llm_response.error_type or "llm_error",
                        budget_before=budget_before,
                        budget_after=_budget_remaining(harness_backend),
                    )
                )
                return StructuralRepairResult(
                    "failed",
                    attempts,
                    baseline_candidate,
                    baseline_kernel,
                    cosim_diagnosis,
                    current_diagnosis,
                    "llm_error",
                )

            parsed = llm_response.parsed
            replacement = parsed["replacement_kernel"]
            action = {
                "type": "llm_structural_repair",
                "attempt_index": attempt_index,
                "diagnosis": parsed["diagnosis"],
                "repair_strategy": parsed["repair_strategy"],
                "affected_streams": parsed["affected_streams"],
                "changes": parsed["changes"],
                "confidence": parsed["confidence"],
            }
            candidate = candidate_store.structural_repair_candidate(
                task_context,
                replacement,
                attempt_index=attempt_index,
                parent_candidate=current_candidate,
                action=action,
            )
            validation = self.kernel_validator.validate(task_context, replacement)
            candidate_stream_analysis = self.stream_analyzer.analyze(task_context, replacement) if validation.ok else None
            diff_patch = _diff(current_kernel, replacement)
            if not validation.ok:
                attempts.append(
                    _attempt(
                        attempt_index,
                        candidate,
                        replacement,
                        parsed,
                        llm_response,
                        validation,
                        candidate_stream_analysis,
                        [],
                        None,
                        diff_patch,
                        "not_eligible",
                        "validation_failed",
                        "validation_failed",
                        budget_before,
                        _budget_remaining(harness_backend),
                    )
                )
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
                        candidate_stream_analysis,
                        stage_results,
                        None,
                        diff_patch,
                        "not_eligible",
                        "csim_failed",
                        "csim_failed",
                        budget_before,
                        _budget_remaining(harness_backend),
                    )
                )
                if csim.status in {"budget_exceeded", "timeout", "exception"}:
                    break
                continue

            synth = harness_backend.synth(replacement)
            stage_results.append(synth)
            if synth.status != "pass":
                attempts.append(
                    _attempt(
                        attempt_index,
                        candidate,
                        replacement,
                        parsed,
                        llm_response,
                        validation,
                        candidate_stream_analysis,
                        stage_results,
                        None,
                        diff_patch,
                        "not_eligible",
                        "synth_failed",
                        "synth_failed",
                        budget_before,
                        _budget_remaining(harness_backend),
                    )
                )
                if synth.status in {"budget_exceeded", "timeout", "exception"}:
                    break
                continue

            cosim = harness_backend.cosim(replacement)
            stage_results.append(cosim)
            candidate_cosim_diagnosis = self.cosim_analyzer.analyze(
                task_context,
                cosim,
                self.log_normalizer.normalize(cosim),
            )
            if cosim.status == "pass":
                attempts.append(
                    _attempt(
                        attempt_index,
                        candidate,
                        replacement,
                        parsed,
                        llm_response,
                        validation,
                        candidate_stream_analysis,
                        stage_results,
                        candidate_cosim_diagnosis,
                        diff_patch,
                        "selected",
                        "repaired",
                        "structural_repair_succeeded",
                        budget_before,
                        _budget_remaining(harness_backend),
                    )
                )
                return StructuralRepairResult(
                    "repaired",
                    attempts,
                    candidate,
                    replacement,
                    cosim_diagnosis,
                    candidate_cosim_diagnosis,
                    "structural_repair_succeeded",
                )

            attempts.append(
                _attempt(
                    attempt_index,
                    candidate,
                    replacement,
                    parsed,
                    llm_response,
                    validation,
                    candidate_stream_analysis,
                    stage_results,
                    candidate_cosim_diagnosis,
                    diff_patch,
                    "not_eligible",
                    "cosim_failed",
                    "cosim_failed",
                    budget_before,
                    _budget_remaining(harness_backend),
                )
            )
            current_kernel = replacement
            current_candidate = candidate
            current_diagnosis = candidate_cosim_diagnosis
            if cosim.status in {"budget_exceeded", "timeout", "exception"}:
                break

        return StructuralRepairResult(
            "failed",
            attempts,
            baseline_candidate,
            baseline_kernel,
            cosim_diagnosis,
            current_diagnosis,
            "max_attempts_exhausted",
        )


def _is_structural_repairable(
    task_context: TaskContext,
    baseline_cosim_result: UnifiedToolResult,
    cosim_diagnosis: CoSimDiagnosis,
) -> bool:
    if task_context.task_type not in {"structural", "mixed"}:
        return False
    if baseline_cosim_result.stage != "cosim" or baseline_cosim_result.status == "pass":
        return False
    return cosim_diagnosis.category in STRUCTURAL_REPAIR_CATEGORIES


def _initial_kernel(task_context: TaskContext) -> str:
    content = task_context.initial_kernel.get("content")
    if isinstance(content, str):
        return content
    raise ValueError("TaskContext initial_kernel content is required for structural repair")


def _budget_summary(harness_backend: HarnessBackend, safety_margin: int) -> dict[str, Any]:
    budget = getattr(getattr(harness_backend, "tool_server", None), "budget", None)
    costs = getattr(budget, "cost", {}) or {}
    remaining = _budget_remaining(harness_backend)
    required = int(costs.get("csim", 1)) + int(costs.get("synth", 4)) + int(costs.get("cosim", 20))
    required_with_margin = required + int(safety_margin)
    return {
        "remaining": remaining,
        "candidate_csim_cost": int(costs.get("csim", 1)),
        "candidate_synth_cost": int(costs.get("synth", 4)),
        "candidate_cosim_cost": int(costs.get("cosim", 20)),
        "safety_margin": int(safety_margin),
        "required_for_candidate": required,
        "required_with_safety_margin": required_with_margin,
        "can_attempt": remaining is None or remaining >= required_with_margin,
    }


def _budget_remaining(harness_backend: HarnessBackend) -> int | None:
    budget = getattr(getattr(harness_backend, "tool_server", None), "budget", None)
    remaining_fn = getattr(budget, "remaining", None)
    if not callable(remaining_fn):
        return None
    try:
        remaining = remaining_fn()
    except Exception:
        return None
    return int(remaining) if isinstance(remaining, int) else None


def _attempt(
    attempt_index: int,
    candidate: Candidate,
    replacement: str,
    parsed: dict[str, Any],
    llm_response: LLMResponse,
    validation: KernelValidationResult,
    stream_analysis: StreamAnalysis | None,
    stage_results: list[UnifiedToolResult],
    cosim_diagnosis: CoSimDiagnosis | None,
    diff_patch: str,
    selection_status: str,
    status: str,
    stop_reason: str,
    budget_before: int | None,
    budget_after: int | None,
) -> StructuralRepairAttempt:
    return StructuralRepairAttempt(
        attempt_index=attempt_index,
        candidate=candidate,
        replacement_kernel=replacement,
        diagnosis=parsed.get("diagnosis"),
        repair_strategy=parsed.get("repair_strategy"),
        affected_streams=list(parsed.get("affected_streams", [])),
        changes=list(parsed.get("changes", [])),
        confidence=parsed.get("confidence"),
        prompt_sha256=llm_response.prompt_sha256,
        llm_response=llm_response,
        llm_call_record=llm_response.attempts[-1].to_dict() if llm_response.attempts else None,
        validation_result=validation,
        stream_analysis=stream_analysis,
        stage_results=stage_results,
        cosim_diagnosis=cosim_diagnosis,
        diff_patch=diff_patch,
        selection_status=selection_status,
        status=status,
        stop_reason=stop_reason,
        budget_before=budget_before,
        budget_after=budget_after,
    )


def _llm_error_attempt(
    *,
    attempt_index: int,
    llm_response: LLMResponse,
    stream_analysis: StreamAnalysis,
    stop_reason: str,
    budget_before: int | None,
    budget_after: int | None,
) -> StructuralRepairAttempt:
    return StructuralRepairAttempt(
        attempt_index=attempt_index,
        candidate=None,
        replacement_kernel=None,
        diagnosis=None,
        repair_strategy=None,
        affected_streams=[],
        changes=[],
        confidence=None,
        prompt_sha256=llm_response.prompt_sha256,
        llm_response=llm_response,
        llm_call_record=llm_response.attempts[-1].to_dict() if llm_response.attempts else None,
        validation_result=None,
        stream_analysis=stream_analysis,
        stage_results=[],
        cosim_diagnosis=None,
        diff_patch="",
        selection_status="not_eligible",
        status="llm_error",
        stop_reason=stop_reason,
        budget_before=budget_before,
        budget_after=budget_after,
    )


def _diff(before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="before/kernel.cpp",
            tofile="after/kernel.cpp",
        )
    )
