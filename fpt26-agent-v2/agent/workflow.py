"""FPT26 Track-A agent workflow — the single file to read for understanding the full pipeline.

Workflow overview::

    baseline_check ──┬── csim pass ──→ cosim? ──→ optimize ──→ score
                      │
                      └── csim fail ──→ repair loop ──→ ...
                                            │
                            LLM modifies code → csim simulation →
                            read result log → decide whether to call LLM again

Each step below is a pure function ``RunState -> RunState``.  Open
``build_pipeline()`` to see the step ordering and conditional logic at a glance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from llm4hls.budget import BudgetExceeded
from llm4hls.harness import ToolServer
from llm4hls.scoring import grade as official_grade
from llm4hls.task import Task
from llm4hls.tools import ToolResult

from agent.agents.base import AgentConfig, RunState

# ---------------------------------------------------------------------------
# Pipeline framework
# ---------------------------------------------------------------------------


@dataclass
class Step:
    """A named step in the pipeline.

    Args:
        name: Short identifier shown in logs.
        fn: ``RunState -> RunState`` callable.
        condition: If set, the step is skipped when this returns False.
        desc: Human-readable one-liner for log output.
    """

    name: str
    fn: Callable[[RunState], RunState]
    condition: Callable[[RunState], bool] | None = None
    desc: str = ""


class Pipeline:
    """Ordered collection of Steps executed sequentially."""

    def __init__(self, steps: list[Step] | None = None, *, name: str = "workflow") -> None:
        self.steps: list[Step] = steps or []
        self.name = name

    def run(self, state: RunState) -> RunState:
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
            if state.status in ("budget_exceeded", "stopped", "error"):
                state.log(f"  pipeline stopping: status={state.status}")
                break
        state.log(f"Pipeline done, status={state.status}")
        return state


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

_CODE_RE = re.compile(r"```(?:cpp|c\+\+|c)?\s*\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str | None:
    """Extract kernel source from an LLM response (```cpp fenced block)."""
    blocks = _CODE_RE.findall(text)
    if blocks:
        return blocks[0].strip() + "\n"
    stripped = text.strip()
    return stripped + "\n" if stripped else None


def _latency(result: ToolResult) -> int | None:
    """Extract worst-case latency from a synthesis ToolResult."""
    if result.report is None:
        return None
    return (
        result.report.latency_worst
        if result.report.latency_worst is not None
        else result.report.latency_avg
    )


# ---------------------------------------------------------------------------
# Step functions — tool calls (simple, no LLM)
# ---------------------------------------------------------------------------


def step_csim(state: RunState) -> RunState:
    """Run C simulation on the current kernel."""
    r = state.server.csim(state.kernel)
    state.results.append(r)
    state.csim_ok = r.ok
    state.log(f"csim: {r.brief()}")
    if not r.ok:
        state.status = "csim_failed"
    return state


def step_synth(state: RunState) -> RunState:
    """Run C synthesis on the current kernel (requires csim to have passed)."""
    if not state.csim_ok:
        state.log("synth: skipped (csim not ok)")
        return state
    r = state.server.synth(state.kernel)
    state.results.append(r)
    state.synth_ok = r.ok
    lat = _latency(r)
    if lat is not None:
        state.best_latency = lat
    state.log(f"synth: {r.brief()}  latency={lat}")
    return state


def step_cosim(state: RunState) -> RunState:
    """Run C/RTL co-simulation (only for structural tasks)."""
    if not state.task.requires_cosim:
        state.cosim_ok = True  # not required → trivially ok
        return state
    r = state.server.cosim(state.kernel)
    state.results.append(r)
    state.cosim_ok = r.ok
    state.log(f"cosim: {r.brief()}")
    return state


def step_score(state: RunState) -> RunState:
    """Run official hidden-testbench grading (outside the metered budget)."""
    if not state.config.score:
        return state
    grade_root = Path(state.config.output_root) / state.task.id / "grade"
    state.scorecard = official_grade(state.task, state.kernel, grade_root)
    if state.scorecard is not None:
        state.log(f"score: {state.scorecard.score:.4f}  (functional={state.scorecard.functional_pass})")
    return state


def step_finalize(state: RunState) -> RunState:
    """Persist the final kernel to the output directory."""
    out = Path(state.config.output_root) / state.task.id
    out.mkdir(parents=True, exist_ok=True)
    kernel_path = out / f"final_{state.task.kernel_name}"
    kernel_path.write_text(state.kernel, encoding="utf-8")
    state.log(f"final kernel → {kernel_path}")
    state.status = "completed"
    return state


# ---------------------------------------------------------------------------
# Step functions — agent-based (delegate to agents/*.py)
# ---------------------------------------------------------------------------


def step_repair(state: RunState) -> RunState:
    """Run the repair agent loop if csim failed."""
    if state.csim_ok:
        state.log("repair: skipped (csim already ok)")
        return state
    if state.llm is None:
        state.log("repair: no LLM client — cannot repair")
        state.status = "repair_no_llm"
        return state

    try:
        from agent.agents.repair import RepairAgent
    except ImportError:
        state.log("repair: RepairAgent not implemented yet")
        return state

    agent = RepairAgent(llm=state.llm, max_attempts=state.config.max_repair_attempts)
    result = agent.run(state)
    state.kernel = result.kernel
    # result is the same RunState object; results already appended in-place
    state.csim_ok = result.csim_ok
    state.log(f"repair: csim_ok={result.csim_ok}")
    return state


def step_structural_repair(state: RunState) -> RunState:
    """Run structural repair if cosim failed on a structural task."""
    if state.cosim_ok:
        state.log("structural_repair: skipped (cosim already ok)")
        return state
    if not state.task.requires_cosim:
        return state
    if state.llm is None:
        state.log("structural_repair: no LLM client")
        state.status = "structural_repair_no_llm"
        return state

    try:
        from agent.agents.structural import StructuralRepairAgent
    except ImportError:
        state.log("structural_repair: StructuralRepairAgent not implemented yet")
        return state

    agent = StructuralRepairAgent(llm=state.llm, max_attempts=state.config.max_structural_attempts)
    result = agent.run(state)
    state.kernel = result.kernel
    # result is the same RunState object; cosim_ok set in-place on success
    state.cosim_ok = result.cosim_ok
    state.log(f"structural_repair: {result.status}")
    return state


def step_optimize(state: RunState) -> RunState:
    """Run the optimization agent loop."""
    if state.llm is None:
        state.log("optimize: no LLM client")
        state.status = "optimize_no_llm"
        return state

    try:
        from agent.agents.optimize import OptimizeAgent
    except ImportError:
        state.log("optimize: OptimizeAgent not implemented yet")
        return state

    agent = OptimizeAgent(llm=state.llm, max_rounds=state.config.max_optimization_rounds)
    result = agent.run(state)
    state.kernel = result.kernel
    # result is the same RunState object; results already appended in-place
    if result.best_latency is not None:
        state.best_latency = result.best_latency
    state.log(f"optimize: {result.status}  latency={state.best_latency}")
    return state


# ---------------------------------------------------------------------------
# Pipeline builder — the single place to understand the full workflow
# ---------------------------------------------------------------------------


def build_pipeline(
    *,
    config: AgentConfig,
    task: Task,
    server: ToolServer,
    llm: Any = None,
) -> Pipeline:
    """Build the agent pipeline based on mode and task type.

    This is **the** function to read when you want to understand or modify
    the agent's execution order.  Each ``Step`` entry below corresponds to
    one stage in the run.

    Modes:
    - ``baseline``   — csim → synth → score (no LLM)
    - ``repair``     — csim → repair → synth → score
    - ``optimize``   — csim → synth → optimize → score
    - ``structural`` — csim → synth → cosim → structural_repair → score
    - ``full``       — all of the above, conditioned on task type
    """
    mode = config.mode

    # Every pipeline starts with an init step
    def _init(state: RunState) -> RunState:
        state.log(f"task={task.id}  type={task.type}  mode={mode}  budget={server.budget.total}")
        return state

    pipeline = Pipeline(name=f"fpt26-v2/{mode}")
    pipeline.steps.append(Step("init", _init, desc="initialise run state"))

    # ---- Stage 1: Baseline correctness check ----
    pipeline.steps.append(Step("csim", step_csim, desc="C simulation (baseline)"))

    # ---- Stage 2: Repair (if enabled and needed) ----
    if mode in ("repair", "full"):
        pipeline.steps.append(
            Step("repair", step_repair,
                 condition=lambda s: not s.csim_ok,
                 desc="LLM repair loop: modify code → csim → read log → retry")
        )

    # ---- Stage 3: Synthesis ----
    pipeline.steps.append(Step("synth", step_synth, desc="C synthesis (baseline PPA)"))

    # ---- Stage 4: Co-simulation (structural tasks) ----
    if task.requires_cosim and mode in ("structural", "full"):
        pipeline.steps.append(Step("cosim", step_cosim, desc="C/RTL co-simulation"))

    # ---- Stage 5: Structural repair ----
    if task.requires_cosim and mode in ("structural", "full"):
        pipeline.steps.append(
            Step("structural_repair", step_structural_repair,
                 condition=lambda s: not s.cosim_ok,
                 desc="Structural repair: fix streaming/dataflow deadlocks")
        )

    # ---- Stage 6: Optimization ----
    if mode in ("optimize", "full"):
        optimize_desc = (
            "Parallel competition: N agents generate candidates, pick best latency"
            if config.competition
            else "LLM optimization loop: propose → csim → synth → compare latency"
        )
        pipeline.steps.append(
            Step("optimize", step_optimize,
                 condition=lambda s: s.csim_ok and s.synth_ok,
                 desc=optimize_desc)
        )

    # ---- Stage 7: Scoring ----
    pipeline.steps.append(Step("score", step_score, desc="Hidden-testbench grading"))

    # ---- Stage 8: Finalize ----
    pipeline.steps.append(Step("finalize", step_finalize, desc="Persist final kernel"))

    return pipeline
