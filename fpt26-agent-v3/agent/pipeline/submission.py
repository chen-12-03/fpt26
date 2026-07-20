"""Submission pipeline orchestration.

Delegates to the existing ``agent.workflow`` steps for now; this module
provides the typed entry point and dependency assembly that ``main.py`` uses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.agents.base import AgentConfig, RunState


def run_submission(
    *,
    task: Any,
    config: AgentConfig,
    server: Any,
    llm: Any,
    run_root: Path,
    total_budget: int,
) -> RunState:
    """Run the full submission pipeline and return the terminal RunState.

    This is a thin typed wrapper around ``workflow.build_pipeline().run()``.
    """
    from agent.workflow import build_pipeline, step_finalize

    state = RunState(
        task=task,
        server=server,
        llm=llm,
        config=config,
        kernel=task.kernel_code,
        safe_fallback_kernel=task.kernel_code,
    )
    state.metadata["run_role"] = "submission"
    state.metadata["effective_budget"] = total_budget
    state.metadata["official_budget"] = task.budget

    pipeline = build_pipeline(config=config, task=task, server=server, llm=llm)
    state = pipeline.run(state)

    if not state.metadata.get("finalized"):
        state = step_finalize(state)

    return state
