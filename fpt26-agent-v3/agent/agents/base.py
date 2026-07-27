"""Base types for the v2 agent pipeline.

RunState is the shared context that flows through every pipeline step.
AgentResult is the return value from each Agent.run() call.

RunState is the **only** production context.  ``PipelineContext``
(``agent.pipeline.core``) is deprecated and unused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agent.integrations.harness import Task, ToolResult, ToolServer


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
    status: str = "running"
    results: list[ToolResult] = field(default_factory=list)
    best_latency: int | None = None


@dataclass
class AgentConfig:
    """Configuration knobs for a pipeline run."""

    mode: str = "auto"                # auto | baseline | repair | optimize | structural | full
    run_role: str = "submission"      # submission | evaluator
    competition: bool = False         # independent strategy lanes, measured sequentially
    max_repair_attempts: int = 3
    max_optimization_rounds: int = 5
    max_structural_attempts: int = 3
    output_root: str = "runs"
    score: bool = False
    scoring_profile: str = "balanced"
    verbose: bool = True

    @property
    def needs_llm(self) -> bool:
        return self.mode in {"auto", "repair", "optimize", "structural", "full"}


@dataclass
class RunState:
    """Mutable shared state flowing through pipeline steps.

    Each step function receives a RunState, modifies what it needs,
    and returns it (or a copy).  The pipeline walks the step list in order.

    Explicit fields below replace the ad-hoc ``metadata`` dict for
    accounting, anchor evidence, gate history, preflight, errors, and
    artifacts.  ``metadata`` remains as a serialisation mirror only —
    business logic MUST read from the explicit fields.
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
    interface_ok: bool = False
    frequency_ok: bool = False
    resource_ok: bool = False

    # -- PPA tracking ----------------------------------------------------
    best_latency: int | None = None
    best_synth_result: Any = None
    last_verified_kernel: str | None = None
    safe_fallback_kernel: str | None = None

    # -- scoring ---------------------------------------------------------
    scorecard: Any = None
    ref_scorecard: Any = None  # anchored against reference solution

    # -- status ----------------------------------------------------------
    status: str = "running"
    stop_reason: str = ""

    # -- explicit structured fields (migrated from metadata dict) --------

    # Accounting: the single source of truth for cost/time.  May be None
    # during submission; required for formal evaluation.
    evaluation_accounting: Any = None  # EvaluationAccounting | None

    # Anchor evidence: recorded once by the scoring step.
    anchor_evidence: Any = None  # AnchorEvidence | dict | None

    # Gate history: structured records instead of ad-hoc metadata lists.
    interface_validations: list[dict[str, Any]] = field(default_factory=list)
    synth_gate_history: list[dict[str, Any]] = field(default_factory=list)
    cosim_gate_history: list[dict[str, Any]] = field(default_factory=list)

    # Preflight: task-level preflight data (Vitis version, part, etc.)
    task_preflight: dict[str, Any] = field(default_factory=dict)

    # Errors: infrastructure errors encountered during the run.
    infrastructure_errors: list[dict[str, Any]] = field(default_factory=list)

    # Artifacts: manifests of persisted artifacts.
    artifact_manifests: list[Any] = field(default_factory=list)

    # -- free-form metadata for serialisation / agent-to-agent -----------
    # Business logic MUST prefer the explicit fields above.  This dict is
    # a serialisation mirror only.
    metadata: dict[str, Any] = field(default_factory=dict)

    def log(self, msg: str) -> None:
        if self.config.verbose:
            from agent.console_ui import progress

            progress(self.config.mode, msg)
