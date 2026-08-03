"""Submission pipeline orchestration — real implementation.

Does NOT import from ``agent.workflow``.  Uses ``CandidateValidator``,
``ToolServer`` / ``SecureToolExecutor``, and the agent classes directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.agents.base import AgentConfig, RunState
from agent.models import SubmissionEvidence
from agent.candidate.validator import CandidateValidator, ValidationPlan


def run_submission(
    *,
    task: Any,
    config: AgentConfig,
    server: Any,
    llm: Any,
    run_root: Path,
    total_budget: int,
    preflight_metadata: dict[str, Any] | None = None,
) -> RunState:
    """Run the full submission pipeline and return the terminal RunState.

    Constructs state, injects a ``CandidateValidator``, runs the Pipeline
    (delegated to ``workflow.build_pipeline()`` via the RunState-based
    compatibility path for now), exports SubmissionEvidence, and finalises.
    """
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
    if preflight_metadata is not None:
        state.metadata["task_preflight"] = dict(preflight_metadata)

    # Inject CandidateValidator for use by pipeline steps
    state.metadata["_candidate_validator"] = CandidateValidator(
        task, task.kernel_code,
    )

    # ── Run the compatibility pipeline (delegates to workflow internals) ─
    _run_pipeline(state, config, task, server, llm)

    # ── Finalize ───────────────────────────────────────────────────────
    if not state.metadata.get("finalized"):
        _finalize(state)

    return state


def _run_pipeline(state: RunState, config: Any, task: Any, server: Any, llm: Any) -> None:
    """Run pipeline steps directly, without importing from workflow.

    Each step mutates *state* in-place.  The step functions are the
    compatibility gate functions now exported from candidate/validator.py.
    """
    from agent.candidate.validator import (
        validate_candidate,
        record_synth_gates,
        record_cosim_gate,
        mark_fully_verified,
    )
    from agent.runner import CSimTool, SynthTool, CoSimTool

    mode = config.mode
    state.log(f"task={task.id} type={task.type} mode={mode} "
              f"budget={getattr(getattr(server, 'budget', None), 'total', '?')}")

    # Stage 1: Baseline CSim
    if not validate_candidate(state, state.kernel, stage="baseline"):
        return
    r = server.csim(state.kernel)
    state.results.append(r)
    state.csim_ok = r.ok
    state.log(f"csim: {r.brief()}")

    # Stage 2: Repair (if needed)
    if mode in ("auto", "repair", "full") and not state.csim_ok:
        try:
            from agent.agents.repair import RepairAgent
            agent = RepairAgent(llm=llm, max_attempts=config.max_repair_attempts)
            agent.run(state)
        except ImportError as exc:
            state.log(f"repair: RepairAgent import failed: {exc}")
            state.metadata.setdefault("infrastructure_errors", []).append({
                "step": "repair", "error": f"ImportError: {exc}",
            })
        except Exception as exc:
            state.log(f"repair: RepairAgent crashed: {type(exc).__name__}: {exc}")
            state.metadata.setdefault("infrastructure_errors", []).append({
                "step": "repair", "error": f"{type(exc).__name__}: {exc}",
            })

    # Stage 3: Synthesis
    if state.csim_ok:
        r = server.synth(state.kernel)
        state.results.append(r)
        state.synth_ok = r.ok
        record_synth_gates(state, r, stage="pipeline_synth")
        state.log(f"synth: {r.brief()}")

    # Synth repair
    if mode in ("auto", "repair", "full") and state.csim_ok and not state.synth_ok:
        try:
            from agent.agents.repair import RepairAgent
            agent = RepairAgent(llm=llm, max_attempts=config.max_repair_attempts)
            agent.run(state)
        except ImportError as exc:
            state.log(f"synth_repair: RepairAgent import failed: {exc}")
            state.metadata.setdefault("infrastructure_errors", []).append({
                "step": "synth_repair", "error": f"ImportError: {exc}",
            })
        except Exception as exc:
            state.log(f"synth_repair: RepairAgent crashed: {type(exc).__name__}: {exc}")
            state.metadata.setdefault("infrastructure_errors", []).append({
                "step": "synth_repair", "error": f"{type(exc).__name__}: {exc}",
            })

    # Stage 4: CoSim (structural only)
    if task.requires_cosim and state.synth_ok:
        r = server.cosim(state.kernel)
        state.results.append(r)
        record_cosim_gate(state, r, stage="pipeline_cosim", source_code=state.kernel)
        state.log(f"cosim: {r.brief()}")

    # Structural repair
    if task.requires_cosim and mode in ("auto", "structural", "full") and not state.cosim_ok:
        try:
            from agent.agents.structural import StructuralRepairAgent
            agent = StructuralRepairAgent(llm=llm, max_attempts=config.max_structural_attempts)
            agent.run(state)
        except ImportError as exc:
            state.log(f"structural_repair: StructuralRepairAgent import failed: {exc}")
            state.metadata.setdefault("infrastructure_errors", []).append({
                "step": "structural_repair", "error": f"ImportError: {exc}",
            })
        except Exception as exc:
            state.log(f"structural_repair: StructuralRepairAgent crashed: {type(exc).__name__}: {exc}")
            state.metadata.setdefault("infrastructure_errors", []).append({
                "step": "structural_repair", "error": f"{type(exc).__name__}: {exc}",
            })

    # Stage 5: Optimization
    gates_ok = (state.csim_ok and state.synth_ok and state.interface_ok
                and state.frequency_ok and state.resource_ok
                and (not task.requires_cosim or state.cosim_ok))
    if mode in ("auto", "optimize", "full") and gates_ok:
        try:
            if config.competition:
                from agent.agents.competition import DiverseOptimizationStage

                agent = DiverseOptimizationStage(
                    llm=llm,
                    max_candidates=min(3, config.max_optimization_rounds),
                    scoring_profile=getattr(
                        config, "scoring_profile", "balanced"
                    ),
                )
            else:
                from agent.agents.optimize import OptimizeAgent

                agent = OptimizeAgent(
                    llm=llm,
                    max_rounds=config.max_optimization_rounds,
                    scoring_profile=getattr(
                        config, "scoring_profile", "balanced"
                    ),
                )
            agent.run(state)
        except ImportError as exc:
            state.log(f"optimize: OptimizeAgent import failed: {exc}")
            state.metadata.setdefault("infrastructure_errors", []).append({
                "step": "optimize", "error": f"ImportError: {exc}",
            })

    # Stage 6: Public acceptance
    failures = []
    if not state.interface_ok:
        failures.append("interface_failed")
    if not state.csim_ok:
        failures.append("csim_failed")
    if not state.synth_ok:
        failures.append("synth_failed")
    if not state.frequency_ok:
        failures.append("frequency_failed")
    if not state.resource_ok:
        failures.append("resource_failed")
    if task.requires_cosim and not state.cosim_ok:
        failures.append("cosim_failed")

    if failures:
        state.status = "failed"
        state.stop_reason = failures[0]
        state.metadata["public_acceptance"] = {"ok": False, "failures": failures}
    else:
        mark_fully_verified(state)
        state.status = "completed"
        state.stop_reason = ""
        state.metadata["public_acceptance"] = {"ok": True, "failures": []}


def _finalize(state: RunState) -> None:
    """Persist final kernel and mark as finalized."""
    if getattr(state, "last_verified_kernel", None) is not None:
        state.kernel = state.last_verified_kernel
    elif state.status in ("failed", "budget_exceeded", "infrastructure_error"):
        if getattr(state, "safe_fallback_kernel", None) is not None:
            state.kernel = state.safe_fallback_kernel

    # ── Detect zero-API-response catastrophic failure ─────────────────
    _token_usage = _get_token_usage_snapshot(state)
    _all_api_failed = (
        _token_usage is not None
        and _token_usage.get("failed_request_count", 0) > 0
        and _token_usage.get("response_count", 0) == 0
    )
    if _all_api_failed:
        state.log(
            f"finalize: all {_token_usage['failed_request_count']} API "
            "requests failed with zero responses — infrastructure error"
        )
        state.status = "infrastructure_error"
        state.stop_reason = "all_api_requests_failed"
        state.metadata["infrastructure_errors"] = state.metadata.get(
            "infrastructure_errors", []
        ) + [
            {
                "step": "finalize",
                "error": (
                    f"all {_token_usage['failed_request_count']} LLM API "
                    "requests returned zero responses"
                ),
            }
        ]
        # For compile_repair tasks, strip the intentional #error so the
        # reference code at least compiles rather than submitting a
        # guaranteed-to-fail baseline.
        if _has_compile_error_baseline(state.kernel):
            state.kernel = _strip_compile_error_baseline(state.kernel)
            state.log("finalize: stripped compile-error baseline from fallback kernel")
            state.metadata["fallback_kernel_stripped_compile_error"] = True

    out = Path(state.config.output_root) / state.task.id
    out.mkdir(parents=True, exist_ok=True)
    kernel_path = out / f"final_{state.task.kernel_name}"
    kernel_path.write_text(state.kernel, encoding="utf-8")
    state.log(f"final kernel → {kernel_path}")
    state.metadata["finalized"] = True
    state.metadata["final_kernel_path"] = str(kernel_path)


def _get_token_usage_snapshot(state: RunState) -> dict | None:
    """Extract token usage snapshot from the LLM client if available."""
    llm = getattr(state, "llm", None)
    if llm is None:
        return None
    token_usage = getattr(llm, "token_usage", None)
    if token_usage is None:
        return None
    try:
        return token_usage.snapshot()
    except Exception:
        return None


def _has_compile_error_baseline(kernel: str) -> bool:
    """Check if kernel source starts with a preprocessor #error directive."""
    stripped = kernel.lstrip()
    return stripped.startswith("#error")


def _strip_compile_error_baseline(kernel: str) -> str:
    """Remove the leading #error directive inserted by Track-A task builder.

    Only removes a single ``#error`` line (and its trailing newline) that was
    injected as the *first* non-whitespace content.  Does NOT strip
    intentionally faulty functional variants like early-return injections.
    """
    import re

    return re.sub(r'^\s*#error\s+TRACK_A_INTENTIONAL_COMPILE_FAILURE\s*\n+', '', kernel, count=1)


# ── Backward-compat step functions for workflow.py re-exports ───────────

def _run_pipeline_step_csim(state):
    if not _validate_candidate(state, code=state.kernel, stage="baseline"):
        return state
    r = state.server.csim(state.kernel)
    state.results.append(r)
    state.csim_ok = r.ok
    state.log(f"csim: {r.brief()}")
    return state

def _run_pipeline_step_synth(state):
    if not state.csim_ok:
        state.log("synth: skipped (csim not ok)")
        return state
    # Reuse adjacent upstream successful synth result
    previous = state.results[-1] if state.results else None
    if (state.synth_ok and getattr(previous, "kind", None) == "synth"
            and getattr(previous, "ok", False) and getattr(previous, "report", None) is not None):
        r = previous
        state.log("synth: reusing upstream successful synth report")
    else:
        r = state.server.synth(state.kernel)
        state.results.append(r)
    state.synth_ok = r.ok
    from agent.candidate.validator import record_synth_gates, _latency_from_report
    record_synth_gates(state, r, stage="pipeline_synth")
    lat = _latency_from_report(r.report if r.ok else None)
    if lat is not None: state.best_latency = lat
    state.log(f"synth: {r.brief()}  latency={lat}")
    if not state.task.requires_cosim:
        from agent.candidate.validator import _mark_fully_verified
        _mark_fully_verified(state)
    return state

def _run_pipeline_step_cosim(state):
    if not state.task.requires_cosim:
        state.cosim_ok = True
        return state
    r = state.server.cosim(state.kernel)
    state.results.append(r)
    if r.report is not None:
        state.synth_ok = True
        from agent.candidate.validator import _latency_from_report
        lat = _latency_from_report(r.report)
        if lat is not None: state.best_latency = lat
    from agent.candidate.validator import record_cosim_gate
    record_cosim_gate(state, r, stage="pipeline_cosim", source_code=state.kernel)
    state.log(f"cosim: {r.brief()}")
    from agent.candidate.validator import _mark_fully_verified
    _mark_fully_verified(state)
    return state

def _validate_candidate(state, code, stage):
    from agent.candidate.validator import validate_candidate as _vc
    return _vc(state, code, stage=stage)


def _build_compat_pipeline(*, config, task, server, llm, Step, Pipeline, **steps):
    """Build a backward-compat Pipeline for old callers."""
    mode = config.mode
    pipeline = Pipeline(name=f"fpt26-v3/{mode}")
    pipeline.steps.append(Step("init", lambda s: s, desc="initialise run state"))
    pipeline.steps.append(Step("csim", steps["step_csim"], desc="C simulation"))
    if mode in ("auto", "repair", "full"):
        pipeline.steps.append(Step("repair", steps["step_repair"],
                                   condition=lambda s: not s.csim_ok,
                                   desc="LLM repair loop"))
    pipeline.steps.append(Step("synth", steps["step_synth"], desc="C synthesis"))
    if mode in ("auto", "repair", "full"):
        pipeline.steps.append(Step("synth_repair", steps["step_repair"],
                                   condition=lambda s: s.csim_ok and not s.synth_ok,
                                   desc="LLM synthesis-repair"))
    if task.requires_cosim:
        pipeline.steps.append(Step("cosim", steps["step_cosim"], desc="C/RTL co-simulation"))
    if task.requires_cosim and mode in ("auto", "structural", "full"):
        pipeline.steps.append(Step("structural_repair", steps["step_structural_repair"],
                                   condition=lambda s: not s.cosim_ok,
                                   desc="Structural repair"))
    if mode in ("auto", "optimize", "full"):
        pipeline.steps.append(Step("optimize", steps["step_optimize"],
                                   condition=lambda s: (s.csim_ok and s.synth_ok and s.interface_ok
                                                        and s.frequency_ok and s.resource_ok
                                                        and (not s.task.requires_cosim or s.cosim_ok)),
                                   desc="LLM optimization"))
    pipeline.steps.append(Step("public_acceptance", steps["step_public_acceptance"],
                               desc="Acceptance gates"))
    pipeline.steps.append(Step("finalize", steps["step_finalize"], desc="Persist final kernel"))
    return pipeline
