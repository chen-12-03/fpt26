from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.core.task_context import TaskContext
from agent.execution.result_adapter import UnifiedToolResult


@dataclass(frozen=True)
class CosimDecision:
    should_run: bool
    reason: str
    required_budget: int | None
    available_budget: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_run": self.should_run,
            "reason": self.reason,
            "required_budget": self.required_budget,
            "available_budget": self.available_budget,
        }


class CosimPolicy:
    def should_run_baseline(
        self,
        task_context: TaskContext,
        stage_results: list[UnifiedToolResult],
        budget_view: Any,
    ) -> CosimDecision:
        required_budget = _cosim_cost(budget_view)
        available_budget = _remaining_budget(budget_view)
        if not task_context.requires_cosim:
            return CosimDecision(False, "task_does_not_require_cosim", required_budget, available_budget)
        if task_context.task_type not in {"structural", "mixed"}:
            return CosimDecision(False, "task_type_not_baseline_cosim", required_budget, available_budget)

        stages = {result.stage: result.status for result in stage_results}
        if stages.get("csim") != "pass":
            return CosimDecision(False, "baseline_csim_not_pass", required_budget, available_budget)
        if stages.get("synth") != "pass":
            return CosimDecision(False, "baseline_synth_not_pass", required_budget, available_budget)
        if required_budget is not None and available_budget is not None and available_budget < required_budget:
            return CosimDecision(False, "insufficient_budget", required_budget, available_budget)
        return CosimDecision(True, "requires_cosim_structural_baseline", required_budget, available_budget)


def _cosim_cost(budget_view: Any) -> int | None:
    costs = getattr(budget_view, "cost", None)
    if isinstance(costs, dict):
        value = costs.get("cosim")
        if isinstance(value, int):
            return value
    if isinstance(budget_view, dict):
        costs = budget_view.get("cost")
        if isinstance(costs, dict) and isinstance(costs.get("cosim"), int):
            return costs["cosim"]
    return None


def _remaining_budget(budget_view: Any) -> int | None:
    remaining = getattr(budget_view, "remaining", None)
    if callable(remaining):
        try:
            value = remaining()
        except Exception:
            return None
        return int(value) if isinstance(value, int) else None
    if isinstance(budget_view, dict):
        value = budget_view.get("remaining")
        return int(value) if isinstance(value, int) else None
    return None
