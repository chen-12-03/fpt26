"""Evaluator-only hidden/reference grading for a finalized submission kernel."""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 image
    import tomli as tomllib

from llm4hls.budget import Budget
from llm4hls.task import load_task

from agent.agents.base import AgentConfig, RunState
from agent.runner import ToolServer
from agent.task_io import load_public_task
from agent.testbench import normalize_task_testbench_data
from agent.validation import CandidateValidator
from agent.workflow import (
    step_finalize,
    step_score,
    validate_candidate,
)


def _hidden_source(task_dir: Path) -> tuple[bool, str]:
    spec = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    public_name = spec["public_tb"]
    hidden_name = spec.get("hidden_tb", public_name)
    available = (task_dir / "hidden" / hidden_name).is_file()
    return available, "hidden" if available else "public_fallback"


def evaluate_final_kernel(
    *,
    task_dir: Path,
    kernel_path: Path,
    output_root: str,
    scoring_profile: str,
    verbose: bool,
) -> RunState:
    """Run evaluator-owned grading without exposing hidden data to submission."""

    task_dir = task_dir.resolve()
    kernel_path = kernel_path.resolve()
    if not kernel_path.is_file():
        raise ValueError(f"final kernel not found: {kernel_path}")

    _, preflight = load_public_task(task_dir)
    task = load_task(task_dir)
    hidden_available, source = _hidden_source(task_dir)
    task.hidden_available = hidden_available
    task.grading_source = source
    normalize_task_testbench_data(task, include_hidden=True)

    budget = Budget(total=task.budget)
    server = ToolServer(
        task,
        budget,
        Path(output_root) / task.id / "evaluator_tools",
    )
    config = AgentConfig(
        mode="baseline",
        run_role="evaluator",
        output_root=output_root,
        score=True,
        scoring_profile=scoring_profile,
        verbose=verbose,
    )
    kernel = kernel_path.read_text(encoding="utf-8")
    state = RunState(
        task=task,
        server=server,
        llm=None,
        config=config,
        kernel=kernel,
        safe_fallback_kernel=kernel,
    )
    state.metadata["task_preflight"] = preflight.to_dict()
    state.metadata["run_role"] = "evaluator"
    state.metadata["hidden_available"] = hidden_available
    state.metadata["grading_source"] = source
    state.metadata["evaluator_input_kernel"] = str(kernel_path)
    state.metadata["_candidate_validator"] = CandidateValidator.from_task(task)

    if not validate_candidate(state, state.kernel, stage="evaluator_input"):
        state.status = "failed"
        state.stop_reason = "interface_failed"
        return step_finalize(state)

    state = step_score(state)
    if state.status == "failed":
        state.metadata["evaluator_acceptance"] = {
            "ok": False,
            "failures": [state.stop_reason],
            "grading_source": source,
            "hidden_available": hidden_available,
        }
        return step_finalize(state)

    if state.scorecard is not None:
        state.csim_ok = bool(state.scorecard.csim_pass)
        state.cosim_ok = (
            bool(state.scorecard.cosim_pass)
            if task.requires_cosim
            else True
        )

    failures = []
    if state.scorecard is None or not state.scorecard.valid:
        failures.append(
            getattr(state.scorecard, "gate_reason", "evaluation_failed")
        )
    if not state.interface_ok:
        failures.append("interface_failed")
    if not state.frequency_ok:
        failures.append(
            (state.metadata.get("frequency_gate") or {}).get(
                "reason", "frequency_failed"
            )
        )
    if not state.resource_ok:
        failures.append(
            (state.metadata.get("resource_gate") or {}).get(
                "reason", "resource_failed"
            )
        )

    if failures:
        state.status = "failed"
        state.stop_reason = str(failures[0])
    else:
        state.status = "completed"
        state.last_verified_kernel = state.kernel
    state.metadata["evaluator_acceptance"] = {
        "ok": not failures,
        "failures": failures,
        "grading_source": source,
        "hidden_available": hidden_available,
    }
    return step_finalize(state)
