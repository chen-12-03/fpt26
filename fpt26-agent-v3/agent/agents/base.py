"""Base types for the v2 agent pipeline.

RunState is the shared context that flows through every pipeline step.
AgentResult is the return value from each Agent.run() call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from llm4hls.harness import ToolServer
from llm4hls.task import Task
from llm4hls.tools import ToolResult


class Agent(Protocol):
    """Protocol for pipeline agents.

    Each agent is an independent strategy module.  To add a new agent:
    1. Implement ``run(ctx) -> RunState``
    2. Add a ``Step(name, agent.run)`` in ``workflow.build_pipeline()``
    """

    def run(self, ctx: "RunState") -> "RunState": ...


@dataclass
class AgentResult:
    """Return value from a standalone Agent run (not the pipeline itself)."""

    kernel: str
    status: str = "ok"
    results: list[ToolResult] = field(default_factory=list)
    best_latency: int | None = None


@dataclass
class AgentConfig:
    """Configuration knobs for a pipeline run."""

    mode: str = "baseline"            # baseline | repair | optimize | structural | full
    competition: bool = False         # use parallel competition within stages
    max_repair_attempts: int = 3
    max_optimization_rounds: int = 5
    max_structural_attempts: int = 3
    output_root: str = "runs"
    score: bool = False
    verbose: bool = True

    @property
    def needs_llm(self) -> bool:
        return self.mode in {"repair", "optimize", "structural", "full"}


@dataclass
class RunState:
    """Mutable shared state flowing through pipeline steps.

    Each step function receives a RunState, modifies what it needs,
    and returns it (or a copy).  The pipeline walks the step list in order.
    """

    task: Task
    server: ToolServer
    llm: Any                          # LLMClient | None
    config: AgentConfig

    # -- evolving kernel -------------------------------------------------
    kernel: str                       # current kernel source code

    # -- tool results ----------------------------------------------------
    results: list[ToolResult] = field(default_factory=list)

    # -- correctness gates -----------------------------------------------
    csim_ok: bool = False
    synth_ok: bool = False
    cosim_ok: bool = False

    # -- PPA tracking ----------------------------------------------------
    best_latency: int | None = None

    # -- scoring ---------------------------------------------------------
    scorecard: Any = None
    ref_scorecard: Any = None  # anchored against reference solution

    # -- status ----------------------------------------------------------
    status: str = "running"
    stop_reason: str = ""

    # -- free-form metadata for agent-to-agent communication -------------
    metadata: dict[str, Any] = field(default_factory=dict)

    def log(self, msg: str) -> None:
        if self.config.verbose:
            print(f"  [{self.config.mode}] {msg}", flush=True)
