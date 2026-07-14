from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.analysis.kernel_validator import KernelValidationResult, KernelValidator
from agent.analysis.report_analyzer import ReportAnalysis, ReportAnalyzer
from agent.core.candidate import Candidate
from agent.core.candidate_store import CandidateStore
from agent.core.task_context import TaskContext
from agent.execution.harness_backend import HarnessBackend
from agent.execution.result_adapter import UnifiedToolResult
from agent.strategy.selector import SelectionResult, Selector, compare_to_baseline
from agent.transform.actions import TransformAction
from agent.transform.transformer import DeterministicTransformer, TransformResult


@dataclass(frozen=True)
class OptimizationCandidateRecord:
    candidate: Candidate | None
    kernel_code: str | None
    actions: list[TransformAction]
    transform_result: TransformResult | None
    validation_result: KernelValidationResult | None
    stage_results: list[UnifiedToolResult]
    metrics: dict[str, Any]
    constraint_checks: dict[str, Any]
    comparison_to_baseline: dict[str, Any]
    diff_patch: str
    selection_status: str
    status: str
    stop_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict() if self.candidate is not None else None,
            "kernel_code": self.kernel_code,
            "actions": [action.to_dict() for action in self.actions],
            "transform_result": self.transform_result.to_dict() if self.transform_result is not None else None,
            "validation_result": self.validation_result.to_dict() if self.validation_result is not None else None,
            "stage_results": [result.to_dict() for result in self.stage_results],
            "metrics": _json_value(self.metrics),
            "constraint_checks": _json_value(self.constraint_checks),
            "comparison_to_baseline": _json_value(self.comparison_to_baseline),
            "diff_patch": self.diff_patch,
            "selection_status": self.selection_status,
            "status": self.status,
            "stop_reason": self.stop_reason,
        }


@dataclass(frozen=True)
class OptimizationResult:
    status: str
    candidates: list[OptimizationCandidateRecord]
    selected_candidate: Candidate
    final_kernel: str
    baseline_metrics: dict[str, Any]
    final_metrics: dict[str, Any]
    selection_reason: str
    search_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "selected_candidate": self.selected_candidate.to_dict(),
            "final_kernel": self.final_kernel,
            "baseline_metrics": _json_value(self.baseline_metrics),
            "final_metrics": _json_value(self.final_metrics),
            "selection_reason": self.selection_reason,
            "search_summary": _json_value(self.search_summary),
        }


class OptimizationController:
    def __init__(
        self,
        *,
        report_analyzer: ReportAnalyzer | None = None,
        transformer: DeterministicTransformer | None = None,
        kernel_validator: KernelValidator | None = None,
        selector: Selector | None = None,
    ) -> None:
        self.report_analyzer = report_analyzer or ReportAnalyzer()
        self.transformer = transformer or DeterministicTransformer()
        self.kernel_validator = kernel_validator or KernelValidator()
        self.selector = selector or Selector()

    def optimize(
        self,
        task_context: TaskContext,
        baseline_candidate: Candidate,
        baseline_stage_results: list[UnifiedToolResult],
        harness_backend: HarnessBackend,
        candidate_store: CandidateStore,
        max_candidates: int = 3,
    ) -> OptimizationResult:
        baseline_kernel = _initial_kernel(task_context)
        baseline_synth = _baseline_synth_result(baseline_stage_results)
        baseline_metrics = _metrics_from_result(baseline_synth)

        skip_reason = _skip_reason(task_context, baseline_stage_results)
        if skip_reason is not None:
            return self._baseline_result(skip_reason, baseline_candidate, baseline_kernel, baseline_metrics, [])

        assert baseline_synth is not None
        baseline_analysis = self.report_analyzer.analyze(
            baseline_synth,
            task_context,
            kernel_code=baseline_kernel,
        )
        actions = self._candidate_actions(task_context, baseline_kernel, baseline_analysis, max_candidates)
        if not actions:
            return self._baseline_result(
                "no_safe_transform_action",
                baseline_candidate,
                baseline_kernel,
                baseline_analysis.metrics,
                [],
            )

        records: list[OptimizationCandidateRecord] = []
        for attempt_index, action in enumerate(actions[:max_candidates], start=1):
            if not _has_budget_for_candidate(harness_backend):
                return self._select_or_baseline(
                    "budget_stopped",
                    baseline_candidate,
                    baseline_kernel,
                    baseline_analysis.metrics,
                    records,
                    "hls_budget_insufficient",
                )

            transform = self.transformer.apply(task_context, baseline_kernel, action)
            if not transform.ok or transform.kernel_code is None:
                records.append(
                    _record(
                        candidate=None,
                        kernel_code=None,
                        actions=[action],
                        transform_result=transform,
                        validation_result=None,
                        stage_results=[],
                        metrics={},
                        constraint_checks={},
                        comparison={},
                        selection_status="not_eligible",
                        status="transform_failed",
                        stop_reason=transform.error,
                    )
                )
                continue

            candidate = candidate_store.optimization_candidate(
                task_context,
                transform.kernel_code,
                attempt_index=attempt_index,
                parent_candidate=baseline_candidate,
                action=action.to_dict(),
            )
            validation = self.kernel_validator.validate(task_context, transform.kernel_code)
            if not validation.ok:
                records.append(
                    _record(
                        candidate=candidate,
                        kernel_code=transform.kernel_code,
                        actions=[action],
                        transform_result=transform,
                        validation_result=validation,
                        stage_results=[],
                        metrics={},
                        constraint_checks={},
                        comparison={},
                        selection_status="not_eligible",
                        status="validation_failed",
                        stop_reason="validation_failed",
                    )
                )
                continue

            csim = harness_backend.csim(transform.kernel_code)
            stage_results = [csim]
            if csim.status != "pass":
                records.append(
                    _record(
                        candidate=candidate,
                        kernel_code=transform.kernel_code,
                        actions=[action],
                        transform_result=transform,
                        validation_result=validation,
                        stage_results=stage_results,
                        metrics={},
                        constraint_checks={},
                        comparison={},
                        selection_status="not_eligible",
                        status="csim_failed",
                        stop_reason="csim_failed",
                    )
                )
                if csim.status in {"budget_exceeded", "timeout", "exception"}:
                    break
                continue

            synth = harness_backend.synth(transform.kernel_code)
            stage_results.append(synth)
            if synth.status != "pass":
                records.append(
                    _record(
                        candidate=candidate,
                        kernel_code=transform.kernel_code,
                        actions=[action],
                        transform_result=transform,
                        validation_result=validation,
                        stage_results=stage_results,
                        metrics={},
                        constraint_checks={},
                        comparison={},
                        selection_status="not_eligible",
                        status="synth_failed",
                        stop_reason="synth_failed",
                    )
                )
                if synth.status in {"budget_exceeded", "timeout", "exception"}:
                    break
                continue

            analysis = self.report_analyzer.analyze(synth, task_context, kernel_code=transform.kernel_code)
            comparison = compare_to_baseline(baseline_analysis.metrics, analysis.metrics)
            checks = analysis.constraint_checks
            selection_status = (
                "eligible"
                if comparison.get("improved") is True
                and checks.get("timing_valid") is True
                and checks.get("resource_limits_valid") is True
                else "not_eligible"
            )
            records.append(
                _record(
                    candidate=candidate,
                    kernel_code=transform.kernel_code,
                    actions=[action],
                    transform_result=transform,
                    validation_result=validation,
                    stage_results=stage_results,
                    metrics=analysis.metrics,
                    constraint_checks=checks,
                    comparison=comparison,
                    selection_status=selection_status,
                    status="synth_pass",
                    stop_reason=None,
                )
            )

        return self._select_or_baseline(
            "completed",
            baseline_candidate,
            baseline_kernel,
            baseline_analysis.metrics,
            records,
            None,
        )

    def _candidate_actions(
        self,
        task_context: TaskContext,
        baseline_kernel: str,
        analysis: ReportAnalysis,
        max_candidates: int,
    ) -> list[TransformAction]:
        loops = self.transformer.discover_loops(baseline_kernel)
        arrays = self.transformer.discover_array_parameters(task_context, baseline_kernel)
        actions: list[TransformAction] = []
        loop = next((item for item in loops if item.bound is not None), loops[0] if loops else None)
        if loop is not None and not loop.has_pipeline:
            actions.append(
                TransformAction(
                    action_type="pipeline_loop",
                    target=loop.target,
                    ii=1,
                    reason="baseline synth passed and loop has no PIPELINE pragma",
                    risk="low",
                )
            )
        if loop is not None and loop.bound is not None and not loop.has_unroll:
            actions.append(
                TransformAction(
                    action_type="unroll_loop",
                    target=loop.target,
                    factor=2,
                    reason="fixed-bound loop can be partially unrolled by factor 2",
                    risk="low",
                )
            )
        if arrays and ("high_ii" in analysis.bottleneck_hints or "unpipelined_loop" in analysis.bottleneck_hints):
            actions.append(
                TransformAction(
                    action_type="array_partition",
                    target=arrays[0],
                    factor=2,
                    dimension=1,
                    partition_mode="cyclic",
                    reason="array parameter may limit loop throughput and resources remain checkable",
                    risk="low",
                )
            )
        return actions[:max_candidates]

    def _baseline_result(
        self,
        status: str,
        baseline_candidate: Candidate,
        baseline_kernel: str,
        baseline_metrics: dict[str, Any],
        records: list[OptimizationCandidateRecord],
    ) -> OptimizationResult:
        return OptimizationResult(
            status=status,
            candidates=records,
            selected_candidate=baseline_candidate,
            final_kernel=baseline_kernel,
            baseline_metrics=baseline_metrics,
            final_metrics=baseline_metrics,
            selection_reason=status,
            search_summary=_summary(status, records),
        )

    def _select_or_baseline(
        self,
        status: str,
        baseline_candidate: Candidate,
        baseline_kernel: str,
        baseline_metrics: dict[str, Any],
        records: list[OptimizationCandidateRecord],
        stop_reason: str | None,
    ) -> OptimizationResult:
        selection = self.selector.select(
            baseline_candidate=baseline_candidate,
            baseline_kernel=baseline_kernel,
            baseline_metrics=baseline_metrics,
            candidate_records=records,
        )
        final_status = selection.status if selection.status == "improved" else (stop_reason or "no_improvement")
        return OptimizationResult(
            status=final_status,
            candidates=records,
            selected_candidate=selection.selected_candidate,
            final_kernel=selection.selected_kernel,
            baseline_metrics=selection.baseline_metrics,
            final_metrics=selection.final_metrics,
            selection_reason=selection.selection_reason,
            search_summary={
                **_summary(status, records),
                "stop_reason": stop_reason,
                "selection": selection.to_dict(),
            },
        )


def _record(
    *,
    candidate: Candidate | None,
    kernel_code: str | None,
    actions: list[TransformAction],
    transform_result: TransformResult | None,
    validation_result: KernelValidationResult | None,
    stage_results: list[UnifiedToolResult],
    metrics: dict[str, Any],
    constraint_checks: dict[str, Any],
    comparison: dict[str, Any],
    selection_status: str,
    status: str,
    stop_reason: str | None,
) -> OptimizationCandidateRecord:
    return OptimizationCandidateRecord(
        candidate=candidate,
        kernel_code=kernel_code,
        actions=actions,
        transform_result=transform_result,
        validation_result=validation_result,
        stage_results=stage_results,
        metrics=metrics,
        constraint_checks=constraint_checks,
        comparison_to_baseline=comparison,
        diff_patch=transform_result.diff_patch if transform_result is not None else "",
        selection_status=selection_status,
        status=status,
        stop_reason=stop_reason,
    )


def _skip_reason(task_context: TaskContext, baseline_stage_results: list[UnifiedToolResult]) -> str | None:
    if task_context.task_type not in {"optimize", "mixed"}:
        return "task_type_not_optimizable"
    stages = {result.stage: result.status for result in baseline_stage_results}
    if stages.get("csim") != "pass":
        return "baseline_csim_not_pass"
    if stages.get("synth") != "pass":
        return "baseline_synth_not_pass"
    return None


def _baseline_synth_result(results: list[UnifiedToolResult]) -> UnifiedToolResult | None:
    for result in results:
        if result.stage == "synth":
            return result
    return None


def _metrics_from_result(result: UnifiedToolResult | None) -> dict[str, Any]:
    return dict(result.metrics) if result is not None and isinstance(result.metrics, dict) else {}


def _initial_kernel(task_context: TaskContext) -> str:
    content = task_context.initial_kernel.get("content")
    if isinstance(content, str):
        return content
    raise ValueError("TaskContext initial_kernel content is required for optimization")


def _has_budget_for_candidate(harness_backend: HarnessBackend) -> bool:
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


def _summary(status: str, records: list[OptimizationCandidateRecord]) -> dict[str, Any]:
    return {
        "status": status,
        "candidate_count": len(records),
        "candidate_statuses": [
            {
                "candidate_id": record.candidate.candidate_id if record.candidate is not None else None,
                "status": record.status,
                "selection_status": record.selection_status,
            }
            for record in records
        ],
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
