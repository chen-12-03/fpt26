"""StructuralRepairAgent — fix streaming/dataflow deadlocks caught by cosim.

C-simulation uses unbounded FIFOs, so streaming deadlocks only appear in
C/RTL co-simulation (bounded depth-2 FIFOs).  This agent runs when cosim
fails on a structural task.
"""

from __future__ import annotations

import re
from typing import Any

from llm4hls.task import Task

from agent.agents.base import RunState
from agent.prompts import STRUCTURAL_REPAIR_SYSTEM, build_structural_repair_prompt

_CODE_RE = re.compile(r"```(?:cpp|c\+\+|c)?\s*\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str | None:
    blocks = _CODE_RE.findall(text)
    if blocks:
        return blocks[0].strip() + "\n"
    stripped = text.strip()
    return stripped + "\n" if stripped else None


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
        code = state.kernel

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

        for attempt in range(1, self.max_attempts + 1):
            # ── 1. Run cosim ─────────────────────────────────────────
            if attempt == 1 and reuse_initial_cosim:
                r = initial_cosim
                state.log("structural repair: reusing pipeline cosim failure")
            else:
                r = server.cosim(code)
                state.results.append(r)
            state.log(f"structural repair attempt {attempt}: cosim {r.brief()}")

            if r.ok:
                state.kernel = code
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
                state.status = "completed"
                state.log("structural repair: cosim passed")
                return state

            # ── 2. Build prompt with cosim failure log ────────────────
            log_text = getattr(r, "log", "") or ""
            prompt = build_structural_repair_prompt(
                task=task,
                current_kernel=code,
                cosim_log=log_text,
            )

            # ── 3. LLM proposes fix ──────────────────────────────────
            response = self.llm.complete(STRUCTURAL_REPAIR_SYSTEM, prompt)
            new_code = extract_code(response)
            if new_code is None or new_code.strip() == code.strip():
                state.log(f"structural repair attempt {attempt}: no change proposed")
                continue

            # ── 4. Quick csim check before expensive cosim ───────────
            cr = server.csim(new_code)
            state.results.append(cr)
            if not cr.ok:
                state.log(f"structural repair attempt {attempt}: broke csim — discard")
                continue

            code = new_code

        state.kernel = code
        state.status = "structural_repair_failed"
        state.log(f"structural repair: failed after {self.max_attempts} attempts")
        return state
