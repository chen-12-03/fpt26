from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from agent.analysis.initial_condition_classifier import InitialCondition, InitialConditionClassifier
from agent.core.task_context import TaskContext
from agent.execution.harness_backend import HarnessBackend
from agent.execution.result_adapter import UnifiedToolResult
from agent.input.task_adapter import TaskAdapter
from agent.reporting.manifest_writer import ManifestWriter
from agent.strategy.baseline_manager import BaselineManager


BackendFactory = Callable[[Any, Any], HarnessBackend]


@dataclass(frozen=True)
class AgentRunResult:
    task_id: str
    task_context: TaskContext
    initial_condition: InitialCondition
    stage_results: list[UnifiedToolResult]
    final_kernel: str
    final_kernel_sha256: str
    budget: dict[str, Any]
    status: str
    run_directory: str | None = None
    run_manifest_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_context": self.task_context.to_dict(),
            "initial_condition": self.initial_condition.to_dict(),
            "stage_results": [result.to_dict() for result in self.stage_results],
            "final_kernel": self.final_kernel,
            "final_kernel_sha256": self.final_kernel_sha256,
            "budget": _json_value(self.budget),
            "status": self.status,
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
    ) -> None:
        self.backend_factory = backend_factory or HarnessBackend
        self.classifier = classifier or InitialConditionClassifier()
        self.baseline_manager = baseline_manager or BaselineManager()

    def run(self, task: Any, tool_server: Any, output_root: str | Path | None = None) -> AgentRunResult:
        task_context = TaskAdapter.from_official_task(task)
        final_kernel = self.baseline_manager.initial_kernel(task_context)
        backend = self.backend_factory(task, tool_server)
        stage_results: list[UnifiedToolResult] = []

        csim_result = backend.csim(final_kernel)
        stage_results.append(csim_result)
        if not _passed(csim_result):
            return self._finish(task_context, tool_server, final_kernel, stage_results, output_root)

        synth_result = backend.synth(final_kernel)
        stage_results.append(synth_result)
        if not _passed(synth_result):
            return self._finish(task_context, tool_server, final_kernel, stage_results, output_root)

        if task_context.requires_cosim:
            cosim_result = backend.cosim(final_kernel)
            stage_results.append(cosim_result)
            if not _passed(cosim_result):
                return self._finish(task_context, tool_server, final_kernel, stage_results, output_root)

        return self._finish(task_context, tool_server, final_kernel, stage_results, output_root)

    def _finish(
        self,
        task_context: TaskContext,
        tool_server: Any,
        final_kernel: str,
        stage_results: list[UnifiedToolResult],
        output_root: str | Path | None,
    ) -> AgentRunResult:
        initial_condition = self.classifier.classify(task_context, stage_results)
        final_hash = self.baseline_manager.sha256(final_kernel)
        result = AgentRunResult(
            task_id=task_context.task_id,
            task_context=task_context,
            initial_condition=initial_condition,
            stage_results=list(stage_results),
            final_kernel=final_kernel,
            final_kernel_sha256=final_hash,
            budget=_budget_snapshot(tool_server),
            status=_run_status(stage_results),
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
