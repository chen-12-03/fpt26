"""FPT26 Track-A agent workflow — backward-compatibility façade.

All business logic has been migrated to:
- candidate/validator.py     (gates: validate_candidate, record_*_gates, mark_fully_verified)
- pipeline/submission.py     (orchestration: build_pipeline → run_submission)
- pipeline/stages.py         (step_finalize, step_public_acceptance)
- pipeline/core.py           (Pipeline, PipelineStep)
- scoring/evaluator.py       (step_score)
- agent/agents/*.py          (step_repair, step_structural_repair, step_optimize)

This module now only re-exports for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.agents.base import AgentConfig, RunState
from agent.candidate.validator import extract_code  # noqa: F401 — re-export

# ── Pipeline classes (thin compatibility) ───────────────────────────────

@dataclass
class Step:
    name: str
    fn: Callable[[RunState], RunState]
    condition: Callable[[RunState], bool] | None = None
    desc: str = ""


class Pipeline:
    def __init__(self, steps: list[Step] | None = None, *, name: str = "workflow") -> None:
        self.steps: list[Step] = steps or []
        self.name = name

    def run(self, state: RunState) -> RunState:
        from agent.integrations.harness import BudgetExceeded
        from agent.safety import redact_sensitive_text
        state.log(f"Pipeline '{self.name}' starting ({len(self.steps)} steps)")
        for step in self.steps:
            if step.condition is not None and not step.condition(state):
                state.log(f"  skip '{step.name}' (condition not met)")
                continue
            state.log(f"  step '{step.name}': {step.desc}")
            try:
                state = step.fn(state)
            except BudgetExceeded:
                state.status = "budget_exceeded"
                state.stop_reason = "budget_exceeded"
                state.log("  budget exceeded — stopping pipeline")
                break
            except Exception as exc:
                safe_message = redact_sensitive_text(exc)
                state.status = "infrastructure_error"
                state.stop_reason = f"{type(exc).__name__}: {safe_message}"
                state.metadata["infrastructure_error"] = {
                    "type": type(exc).__name__, "message": safe_message, "step": step.name,
                }
                state.log(f"  infrastructure error in '{step.name}': {safe_message}")
                break
            if state.status in ("failed", "budget_exceeded", "infrastructure_error"):
                state.log(f"  pipeline stopping: status={state.status}")
                break
        state.log(f"Pipeline done, status={state.status}")
        return state


# ── Gate functions (forward to candidate/validator.py) ──────────────────

def validate_candidate(state, code, *, stage, current_best=True):
    from agent.candidate.validator import validate_candidate as _vc
    return _vc(state, code, stage=stage, current_best=current_best)

def record_synth_gates(state, result, *, stage, current_best=True):
    from agent.candidate.validator import record_synth_gates as _rsg
    return _rsg(state, result, stage=stage, current_best=current_best)

def record_cosim_gate(state, result, *, stage, current_best=True, source_code=None):
    from agent.candidate.validator import record_cosim_gate as _rcg
    return _rcg(state, result, stage=stage, current_best=current_best, source_code=source_code)

def mark_fully_verified(state):
    from agent.candidate.validator import mark_fully_verified as _mfv
    _mfv(state)


# ── Step functions (forward to pipeline stages or agents) ───────────────

def step_csim(state):
    from agent.pipeline.submission import _run_pipeline_step_csim
    return _run_pipeline_step_csim(state)

def step_synth(state):
    from agent.pipeline.submission import _run_pipeline_step_synth
    return _run_pipeline_step_synth(state)

def step_cosim(state):
    from agent.pipeline.submission import _run_pipeline_step_cosim
    return _run_pipeline_step_cosim(state)

def step_score(state):
    from scoring.evaluator import evaluate_and_score
    return evaluate_and_score(state)

def step_public_acceptance(state):
    from agent.pipeline.stages import step_public_acceptance as _spa
    return _spa(state)

def step_finalize(state):
    from agent.pipeline.stages import step_finalize as _sf
    return _sf(state)

def step_repair(state):
    from agent.agents.repair import RepairAgent
    if state.llm is None: state.status = "failed"; state.stop_reason = "repair_no_llm"; return state
    return RepairAgent(llm=state.llm, max_attempts=state.config.max_repair_attempts).run(state)

def step_structural_repair(state):
    from agent.agents.structural import StructuralRepairAgent
    if state.llm is None: state.status = "failed"; state.stop_reason = "structural_repair_no_llm"; return state
    return StructuralRepairAgent(llm=state.llm, max_attempts=state.config.max_structural_attempts).run(state)

def step_optimize(state):
    if state.llm is None: state.status = "failed"; state.stop_reason = "optimize_no_llm"; return state
    if state.config.competition:
        from agent.agents.competition import DiverseOptimizationStage
        return DiverseOptimizationStage(
            llm=state.llm,
            max_candidates=min(3, state.config.max_optimization_rounds),
            scoring_profile=getattr(
                state.config, "scoring_profile", "balanced"
            ),
        ).run(state)
    from agent.agents.optimize import OptimizeAgent
    return OptimizeAgent(llm=state.llm, max_rounds=state.config.max_optimization_rounds,
                         scoring_profile=getattr(state.config, "scoring_profile", "balanced")).run(state)


# ── Orchestration ───────────────────────────────────────────────────────

def build_pipeline(*, config: AgentConfig, task, server, llm=None):
    """DEPRECATED: use ``pipeline.submission.run_submission()`` instead."""
    from agent.pipeline.submission import _build_compat_pipeline
    return _build_compat_pipeline(config=config, task=task, server=server, llm=llm,
                                   Step=Step, Pipeline=Pipeline,
                                   step_csim=step_csim, step_synth=step_synth,
                                   step_cosim=step_cosim, step_repair=step_repair,
                                   step_structural_repair=step_structural_repair,
                                   step_optimize=step_optimize,
                                   step_public_acceptance=step_public_acceptance,
                                   step_finalize=step_finalize)
