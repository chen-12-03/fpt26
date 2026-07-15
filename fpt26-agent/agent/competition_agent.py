from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from agent.analysis.cosim_analyzer import CoSimAnalyzer, CoSimDiagnosis
from agent.analysis.initial_condition_classifier import InitialCondition, InitialConditionClassifier
from agent.analysis.log_normalizer import LogNormalizer
from agent.config import OFFICIAL_REFERENCE_MAX_ROUNDS
from agent.core.candidate_store import CandidateStore
from agent.core.task_context import TaskContext
from agent.execution.harness_backend import HarnessBackend
from agent.execution.result_adapter import UnifiedToolResult
from agent.input.task_adapter import TaskAdapter
from agent.llm.llm_client import LLMClient
from agent.reporting.manifest_writer import ManifestWriter
from agent.strategy.baseline_manager import BaselineManager
from agent.strategy.cosim_policy import CosimDecision, CosimPolicy
from agent.strategy.optimization_controller import OptimizationCandidateRecord, OptimizationController
from agent.strategy.repair_controller import RepairAttempt, RepairController
from agent.strategy.structural_repair_controller import (
    StructuralRepairAttempt,
    StructuralRepairController,
)


BackendFactory = Callable[[Any, Any], HarnessBackend]


@dataclass(frozen=True)
class AgentRunResult:
    task_id: str
    task_context: TaskContext
    initial_condition: InitialCondition
    stage_results: list[UnifiedToolResult]
    baseline_kernel: str
    final_kernel: str
    final_kernel_sha256: str
    budget: dict[str, Any]
    status: str
    repair_status: str
    repair_attempts: list[RepairAttempt]
    optimization_status: str
    optimization_candidates: list[OptimizationCandidateRecord]
    baseline_metrics: dict[str, Any]
    final_metrics: dict[str, Any]
    selected_candidate_id: str
    selection_reason: str | None
    cosim_decision: CosimDecision | None
    cosim_diagnosis: CoSimDiagnosis | None
    baseline_cosim_diagnosis: CoSimDiagnosis | None
    final_cosim_diagnosis: CoSimDiagnosis | None
    requires_structural_repair: bool
    structural_repair_status: str
    structural_repair_attempts: list[StructuralRepairAttempt]
    llm_usage: dict[str, Any]
    stop_reason: str
    run_directory: str | None = None
    run_manifest_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_context": self.task_context.to_dict(),
            "initial_condition": self.initial_condition.to_dict(),
            "stage_results": [result.to_dict() for result in self.stage_results],
            "baseline_kernel": self.baseline_kernel,
            "final_kernel": self.final_kernel,
            "final_kernel_sha256": self.final_kernel_sha256,
            "budget": _json_value(self.budget),
            "status": self.status,
            "repair_status": self.repair_status,
            "repair_attempts": [attempt.to_dict() for attempt in self.repair_attempts],
            "optimization_status": self.optimization_status,
            "optimization_candidates": [candidate.to_dict() for candidate in self.optimization_candidates],
            "baseline_metrics": _json_value(self.baseline_metrics),
            "final_metrics": _json_value(self.final_metrics),
            "selected_candidate_id": self.selected_candidate_id,
            "selection_reason": self.selection_reason,
            "cosim_decision": self.cosim_decision.to_dict() if self.cosim_decision is not None else None,
            "cosim_diagnosis": self.cosim_diagnosis.to_dict() if self.cosim_diagnosis is not None else None,
            "baseline_cosim_diagnosis": (
                self.baseline_cosim_diagnosis.to_dict() if self.baseline_cosim_diagnosis is not None else None
            ),
            "final_cosim_diagnosis": (
                self.final_cosim_diagnosis.to_dict() if self.final_cosim_diagnosis is not None else None
            ),
            "requires_structural_repair": self.requires_structural_repair,
            "structural_repair_status": self.structural_repair_status,
            "structural_repair_attempts": [attempt.to_dict() for attempt in self.structural_repair_attempts],
            "llm_usage": _json_value(self.llm_usage),
            "stop_reason": self.stop_reason,
            "run_directory": self.run_directory,
            "run_manifest_path": self.run_manifest_path,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


class CompetitionAgent:
    def __init__(
        self,
        *,
        backend_factory: BackendFactory | None = None,
        classifier: InitialConditionClassifier | None = None,
        baseline_manager: BaselineManager | None = None,
        repair_controller: RepairController | None = None,
        optimization_controller: OptimizationController | None = None,
        structural_repair_controller: StructuralRepairController | None = None,
        cosim_policy: CosimPolicy | None = None,
        cosim_analyzer: CoSimAnalyzer | None = None,
        log_normalizer: LogNormalizer | None = None,
        llm_client: LLMClient | None = None,
        repair_enabled: bool = False,
        optimize_enabled: bool = False,
        structural_repair_enabled: bool = False,
        max_repair_attempts: int = OFFICIAL_REFERENCE_MAX_ROUNDS,
        max_optimization_candidates: int = OFFICIAL_REFERENCE_MAX_ROUNDS,
        max_structural_repair_attempts: int = OFFICIAL_REFERENCE_MAX_ROUNDS,
    ) -> None:
        self.backend_factory = backend_factory or HarnessBackend
        self.classifier = classifier or InitialConditionClassifier()
        self.baseline_manager = baseline_manager or BaselineManager()
        self.repair_controller = repair_controller or RepairController()
        self.optimization_controller = optimization_controller or OptimizationController()
        self.structural_repair_controller = structural_repair_controller or StructuralRepairController()
        self.cosim_policy = cosim_policy or CosimPolicy()
        self.cosim_analyzer = cosim_analyzer or CoSimAnalyzer()
        self.log_normalizer = log_normalizer or LogNormalizer()
        self.llm_client = llm_client
        self.repair_enabled = repair_enabled
        self.optimize_enabled = optimize_enabled
        self.structural_repair_enabled = structural_repair_enabled
        self.max_repair_attempts = max_repair_attempts
        self.max_optimization_candidates = max_optimization_candidates
        self.max_structural_repair_attempts = max_structural_repair_attempts

    def run(self, task: Any, tool_server: Any, output_root: str | Path | None = None) -> AgentRunResult:
        if self.repair_enabled and self.llm_client is None:
            raise ValueError("repair_enabled=True requires llm_client")
        if self.structural_repair_enabled and self.llm_client is None:
            raise ValueError("structural_repair_enabled=True requires llm_client")
        task_context = TaskAdapter.from_official_task(task)
        baseline_kernel = self.baseline_manager.initial_kernel(task_context)
        final_kernel = baseline_kernel
        backend = self.backend_factory(task, tool_server)
        stage_results: list[UnifiedToolResult] = []
        candidate_store = CandidateStore(output_root or Path("runs"))
        baseline_candidate = candidate_store.baseline_candidate(task_context, baseline_kernel)

        csim_result = backend.csim(baseline_kernel)
        stage_results.append(csim_result)
        if not _passed(csim_result):
            repair_attempts: list[RepairAttempt] = []
            repair_status = "not_attempted"
            selected_candidate_id = baseline_candidate.candidate_id
            stop_reason = "baseline_csim_failed"
            status = _run_status(stage_results)
            if self.repair_enabled:
                assert self.llm_client is not None
                repair = self.repair_controller.repair(
                    task_context,
                    baseline_candidate,
                    csim_result,
                    backend,
                    self.llm_client,
                    candidate_store,
                    max_attempts=self.max_repair_attempts,
                )
                repair_attempts = repair.attempts
                repair_status = repair.status
                selected_candidate_id = repair.selected_candidate.candidate_id
                stop_reason = repair.stop_reason
                for attempt in repair.attempts:
                    stage_results.extend(attempt.stage_results)
                if repair.status == "repaired":
                    final_kernel = repair.final_kernel
                    status = "completed"
                else:
                    final_kernel = baseline_kernel
                    status = "repair_failed"
            return self._finish(
                task_context,
                tool_server,
                baseline_kernel,
                final_kernel,
                stage_results,
                output_root,
                repair_status=repair_status,
                repair_attempts=repair_attempts,
                selected_candidate_id=selected_candidate_id,
                stop_reason=stop_reason,
                status=status,
                classification_results=[csim_result],
            )

        synth_result = backend.synth(baseline_kernel)
        stage_results.append(synth_result)
        if not _passed(synth_result):
            return self._finish(
                task_context,
                tool_server,
                baseline_kernel,
                final_kernel,
                stage_results,
                output_root,
                repair_status="not_attempted",
                repair_attempts=[],
                selected_candidate_id=baseline_candidate.candidate_id,
                stop_reason="baseline_synth_failed",
            )

        cosim_decision = self.cosim_policy.should_run_baseline(
            task_context,
            list(stage_results),
            getattr(tool_server, "budget", None),
        )
        cosim_diagnosis: CoSimDiagnosis | None = None
        requires_structural_repair = False
        if cosim_decision.should_run:
            cosim_result = backend.cosim(baseline_kernel)
            stage_results.append(cosim_result)
            cosim_diagnosis = self.cosim_analyzer.analyze(
                task_context,
                cosim_result,
                self.log_normalizer.normalize(cosim_result),
            )
            requires_structural_repair = cosim_diagnosis.requires_structural_repair
            if not _passed(cosim_result):
                structural_repair_status = "not_attempted"
                structural_repair_attempts: list[StructuralRepairAttempt] = []
                final_cosim_diagnosis = cosim_diagnosis
                selected_candidate_id = baseline_candidate.candidate_id
                stop_reason = "baseline_cosim_failed"
                status = _run_status(stage_results)
                if self.structural_repair_enabled and requires_structural_repair:
                    assert self.llm_client is not None
                    structural = self.structural_repair_controller.repair(
                        task_context,
                        baseline_candidate,
                        cosim_result,
                        cosim_diagnosis,
                        backend,
                        self.llm_client,
                        candidate_store,
                        max_attempts=self.max_structural_repair_attempts,
                    )
                    structural_repair_status = structural.status
                    structural_repair_attempts = structural.attempts
                    selected_candidate_id = structural.selected_candidate.candidate_id
                    final_cosim_diagnosis = structural.final_cosim_diagnosis
                    stop_reason = structural.stop_reason
                    for attempt in structural.attempts:
                        stage_results.extend(attempt.stage_results)
                    if structural.status == "repaired":
                        final_kernel = structural.final_kernel
                        status = "completed"
                    else:
                        final_kernel = baseline_kernel
                        status = "structural_repair_failed"
                return self._finish(
                    task_context,
                    tool_server,
                    baseline_kernel,
                    final_kernel,
                    stage_results,
                    output_root,
                    repair_status="not_attempted",
                    repair_attempts=[],
                    selected_candidate_id=selected_candidate_id,
                    cosim_decision=cosim_decision,
                    cosim_diagnosis=cosim_diagnosis,
                    baseline_cosim_diagnosis=cosim_diagnosis,
                    final_cosim_diagnosis=final_cosim_diagnosis,
                    requires_structural_repair=requires_structural_repair,
                    structural_repair_status=structural_repair_status,
                    structural_repair_attempts=structural_repair_attempts,
                    stop_reason=stop_reason,
                    status=status,
                    classification_results=[csim_result, synth_result, cosim_result],
                )
        elif cosim_decision.reason == "insufficient_budget":
            stage_results.append(_cosim_budget_result(cosim_decision, tool_server))
            return self._finish(
                task_context,
                tool_server,
                baseline_kernel,
                final_kernel,
                stage_results,
                output_root,
                repair_status="not_attempted",
                repair_attempts=[],
                selected_candidate_id=baseline_candidate.candidate_id,
                cosim_decision=cosim_decision,
                cosim_diagnosis=None,
                requires_structural_repair=False,
                stop_reason="cosim_budget_insufficient",
                status="budget_exceeded",
            )

        optimization_status = "not_attempted"
        optimization_candidates: list[OptimizationCandidateRecord] = []
        baseline_metrics = dict(synth_result.metrics or {})
        final_metrics = dict(synth_result.metrics or {})
        selection_reason: str | None = None
        selected_candidate_id = baseline_candidate.candidate_id
        stop_reason = "baseline_complete"
        classification_results = list(stage_results)

        if self.optimize_enabled:
            optimization = self.optimization_controller.optimize(
                task_context,
                baseline_candidate,
                list(stage_results),
                backend,
                candidate_store,
                llm_client=self.llm_client,
                max_candidates=self.max_optimization_candidates,
            )
            optimization_status = optimization.status
            optimization_candidates = optimization.candidates
            baseline_metrics = optimization.baseline_metrics
            final_metrics = optimization.final_metrics
            selection_reason = optimization.selection_reason
            selected_candidate_id = optimization.selected_candidate.candidate_id
            final_kernel = optimization.final_kernel
            if optimization.status == "improved":
                stop_reason = "optimization_improved"
            elif optimization.status not in {"task_type_not_optimizable", "baseline_csim_not_pass", "baseline_synth_not_pass"}:
                stop_reason = optimization.status
            for candidate in optimization.candidates:
                stage_results.extend(candidate.stage_results)

        return self._finish(
            task_context,
            tool_server,
            baseline_kernel,
            final_kernel,
            stage_results,
            output_root,
            repair_status="not_attempted",
            repair_attempts=[],
            optimization_status=optimization_status,
            optimization_candidates=optimization_candidates,
            baseline_metrics=baseline_metrics,
            final_metrics=final_metrics,
            selected_candidate_id=selected_candidate_id,
            selection_reason=selection_reason,
            cosim_decision=cosim_decision,
            cosim_diagnosis=cosim_diagnosis,
            baseline_cosim_diagnosis=cosim_diagnosis,
            final_cosim_diagnosis=cosim_diagnosis,
            requires_structural_repair=requires_structural_repair,
            stop_reason=stop_reason,
            status="completed",
            classification_results=classification_results,
        )

    def _finish(
        self,
        task_context: TaskContext,
        tool_server: Any,
        baseline_kernel: str,
        final_kernel: str,
        stage_results: list[UnifiedToolResult],
        output_root: str | Path | None,
        *,
        repair_status: str,
        repair_attempts: list[RepairAttempt],
        selected_candidate_id: str,
        optimization_status: str = "not_attempted",
        optimization_candidates: list[OptimizationCandidateRecord] | None = None,
        baseline_metrics: dict[str, Any] | None = None,
        final_metrics: dict[str, Any] | None = None,
        selection_reason: str | None = None,
        cosim_decision: CosimDecision | None = None,
        cosim_diagnosis: CoSimDiagnosis | None = None,
        baseline_cosim_diagnosis: CoSimDiagnosis | None = None,
        final_cosim_diagnosis: CoSimDiagnosis | None = None,
        requires_structural_repair: bool = False,
        structural_repair_status: str = "not_attempted",
        structural_repair_attempts: list[StructuralRepairAttempt] | None = None,
        stop_reason: str,
        status: str | None = None,
        classification_results: list[UnifiedToolResult] | None = None,
    ) -> AgentRunResult:
        initial_condition = self.classifier.classify(task_context, classification_results or stage_results)
        final_hash = self.baseline_manager.sha256(final_kernel)
        result = AgentRunResult(
            task_id=task_context.task_id,
            task_context=task_context,
            initial_condition=initial_condition,
            stage_results=list(stage_results),
            baseline_kernel=baseline_kernel,
            final_kernel=final_kernel,
            final_kernel_sha256=final_hash,
            budget=_budget_snapshot(tool_server),
            status=status or _run_status(stage_results),
            repair_status=repair_status,
            repair_attempts=list(repair_attempts),
            optimization_status=optimization_status,
            optimization_candidates=list(optimization_candidates or []),
            baseline_metrics=_json_value(baseline_metrics or {}),
            final_metrics=_json_value(final_metrics or {}),
            selected_candidate_id=selected_candidate_id,
            selection_reason=selection_reason,
            cosim_decision=cosim_decision,
            cosim_diagnosis=cosim_diagnosis,
            baseline_cosim_diagnosis=baseline_cosim_diagnosis,
            final_cosim_diagnosis=final_cosim_diagnosis,
            requires_structural_repair=requires_structural_repair,
            structural_repair_status=structural_repair_status,
            structural_repair_attempts=list(structural_repair_attempts or []),
            llm_usage=_llm_usage(self.llm_client),
            stop_reason=stop_reason,
        )
        if output_root is None:
            return result

        layout = ManifestWriter(output_root).persist(result)
        return replace(
            result,
            run_directory=str(layout.run_dir),
            run_manifest_path=str(layout.run_manifest_path),
        )


def _passed(result: UnifiedToolResult) -> bool:
    return result.status == "pass"


def _run_status(results: list[UnifiedToolResult]) -> str:
    if not results:
        return "not_run"
    failed = [result for result in results if result.status != "pass"]
    if not failed:
        return "completed"
    last = failed[-1]
    if last.status in {"budget_exceeded", "timeout", "exception"}:
        return last.status
    return "stopped"


def _cosim_budget_result(decision: CosimDecision, tool_server: Any) -> UnifiedToolResult:
    spent = getattr(getattr(tool_server, "budget", None), "spent", None)
    return UnifiedToolResult(
        stage="cosim",
        status="budget_exceeded",
        return_code=None,
        elapsed_seconds=0.0,
        summary=(
            "cosim budget insufficient before tool call: "
            f"required={decision.required_budget}, available={decision.available_budget}"
        ),
        metrics={},
        artifacts={},
        budget_before=spent if isinstance(spent, int) else None,
        budget_after=spent if isinstance(spent, int) else None,
    )


def _budget_snapshot(tool_server: Any) -> dict[str, Any]:
    budget = getattr(tool_server, "budget", None)
    total = getattr(budget, "total", None)
    spent = getattr(budget, "spent", None)
    remaining = None
    remaining_fn = getattr(budget, "remaining", None)
    if callable(remaining_fn):
        try:
            remaining = remaining_fn()
        except Exception:
            remaining = None
    calls = []
    for call in getattr(budget, "calls", []) or []:
        calls.append(
            {
                "kind": getattr(call, "kind", None),
                "cost": getattr(call, "cost", None),
                "spent_after": getattr(call, "spent_after", None),
            }
        )
    transcript = []
    for entry in getattr(tool_server, "transcript", []) or []:
        transcript.append(
            {
                "n": getattr(entry, "n", None),
                "kind": getattr(entry, "kind", None),
                "phase": getattr(entry, "phase", None),
                "spent": getattr(entry, "spent", None),
                "detail": getattr(entry, "detail", None),
            }
        )
    return {
        "total": total,
        "spent": spent,
        "remaining": remaining,
        "calls": calls,
        "transcript": transcript,
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _llm_usage(llm_client: LLMClient | None) -> dict[str, Any]:
    tracker = getattr(llm_client, "token_tracker", None)
    if tracker is None:
        return {"records": [], "summary": {}}
    summary = tracker.summary() if callable(getattr(tracker, "summary", None)) else {}
    records = [record.to_dict() for record in getattr(tracker, "records", [])]
    return {**summary, "records": records}
