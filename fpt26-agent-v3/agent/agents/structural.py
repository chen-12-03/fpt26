"""StructuralRepairAgent — fix streaming/dataflow deadlocks caught by cosim.

C-simulation uses unbounded FIFOs, so streaming deadlocks only appear in
C/RTL co-simulation (bounded depth-2 FIFOs).  This agent runs when cosim
fails on a structural task.
"""

from __future__ import annotations

from typing import Any

from agent.integrations.harness import Task

from agent.agents.base import RunState
from agent.candidate.validator import extract_code  # single authority
from agent.prompts import STRUCTURAL_REPAIR_SYSTEM, build_structural_repair_prompt
from agent.validation import can_afford_validation


class StructuralRepairAgent:
    """Fix streaming/dataflow deadlocks in structural HLS tasks.

    The loop::

        1. reuse the pipeline's failed cosim result, or run cosim(current_kernel)
        2. if pass → done
        3. if fail → build prompt with cosim log
        4. llm.complete(prompt) → get response
        5. extract_code → new kernel
        6. csim(new) → cosim(new) → verify
        7. goto 1 (up to max_attempts)
    """

    def __init__(self, llm: Any, max_attempts: int = 3) -> None:
        self.llm = llm
        self.max_attempts = max_attempts

    def run(self, state: RunState) -> RunState:
        task = state.task
        server = state.server
        stable_code = state.kernel

        # The workflow invokes this agent immediately after step_cosim failed.
        # Reuse that result for the first prompt instead of spending another
        # 20 credits to cosim the same, unchanged kernel a second time.  When
        # the agent is used standalone (or the latest result is not a failed
        # cosim), it retains the original behavior and runs cosim itself.
        initial_cosim = state.results[-1] if state.results else None
        reuse_initial_cosim = (
            getattr(initial_cosim, "kind", None) == "cosim"
            and not getattr(initial_cosim, "ok", False)
        )

        if reuse_initial_cosim:
            failure_result = initial_cosim
            state.log("structural repair: reusing pipeline cosim failure")
        else:
            failure_result = server.cosim(stable_code)
            state.results.append(failure_result)

        for attempt in range(1, self.max_attempts + 1):
            # Use the latest real CoSim evidence. Do not re-run an unchanged
            # baseline merely to build another prompt.
            r = failure_result
            state.log(f"structural repair attempt {attempt}: cosim {r.brief()}")

            initial_cosim_report = getattr(r, "cosim", None)
            if (
                r.ok
                and initial_cosim_report is not None
                and getattr(initial_cosim_report, "passed", False)
            ):
                state.kernel = stable_code
                state.cosim_ok = True
                if r.report is not None:
                    state.synth_ok = True
                    latency = (
                        r.report.latency_worst
                        if r.report.latency_worst is not None
                        else r.report.latency_avg
                    )
                    if latency is not None:
                        state.best_latency = latency
                state.status = "running"
                state.log("structural repair: cosim passed")
                return state

            # ── 2. Build prompt with cosim failure log ────────────────
            log_text = getattr(r, "log", "") or ""
            prompt = build_structural_repair_prompt(
                task=task,
                current_kernel=stable_code,
                cosim_log=log_text,
            )

            # ── 3. LLM proposes fix ──────────────────────────────────
            response = self.llm.complete(STRUCTURAL_REPAIR_SYSTEM, prompt)
            new_code = extract_code(
                response,
                required_token=str(getattr(task, "top", "") or ""),
            )
            if new_code is None or new_code.strip() == stable_code.strip():
                state.log(f"structural repair attempt {attempt}: no change proposed")
                continue

            from agent.candidate.validator import (
                mark_fully_verified,
                record_cosim_gate,
                record_synth_gates,
                validate_candidate,
            )

            if not validate_candidate(
                state,
                new_code,
                stage=f"structural_candidate_{attempt}",
                current_best=False,
            ):
                continue
            if not can_afford_validation(
                getattr(server, "budget", None), requires_cosim=True
            ):
                state.status = "budget_exceeded"
                state.stop_reason = "insufficient_budget_for_candidate_validation"
                state.kernel = stable_code
                state.log(
                    "structural repair: preserving prior kernel because the "
                    "remaining budget cannot fund CSim+Synth+CoSim"
                )
                return state

            # ── 4. Full candidate gate: CSim → Synth → CoSim ─────────
            cr = server.csim(new_code)
            state.results.append(cr)
            if not cr.ok:
                state.log(f"structural repair attempt {attempt}: broke csim — discard")
                continue

            sr = server.synth(new_code)
            state.results.append(sr)
            if not sr.ok:
                state.log(
                    f"structural repair attempt {attempt}: synth failed — discard"
                )
                continue
            if not record_synth_gates(
                state,
                sr,
                stage=f"structural_candidate_{attempt}",
                current_best=False,
            ):
                state.log(
                    f"structural repair attempt {attempt}: target gate failed — discard"
                )
                continue

            rr = server.cosim(new_code)
            state.results.append(rr)
            if not record_cosim_gate(
                state,
                rr,
                stage=f"structural_candidate_{attempt}",
                current_best=False,
                source_code=new_code,
            ):
                failure_result = rr
                state.log(
                    f"structural repair attempt {attempt}: cosim failed — discard"
                )
                continue

            stable_code = new_code
            state.kernel = stable_code
            state.csim_ok = True
            state.synth_ok = True
            state.cosim_ok = True
            state.interface_ok = True
            record_synth_gates(
                state,
                sr,
                stage=f"structural_candidate_{attempt}_accepted",
            )
            record_cosim_gate(
                state,
                rr,
                stage=f"structural_candidate_{attempt}_accepted",
                source_code=new_code,
            )
            latency = (
                sr.report.latency_worst
                if sr.report and sr.report.latency_worst is not None
                else (sr.report.latency_avg if sr.report else None)
            )
            if latency is not None:
                state.best_latency = latency
            state.status = "running"
            state.stop_reason = ""
            mark_fully_verified(state)
            state.log("structural repair: full candidate acceptance passed")
            return state

        state.kernel = stable_code
        state.status = "failed"
        state.stop_reason = "structural_repair_failed"
        state.log(f"structural repair: failed after {self.max_attempts} attempts")
        return state
