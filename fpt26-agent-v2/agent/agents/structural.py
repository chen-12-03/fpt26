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

        1. cosim(current_kernel) → get ToolResult
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

        for attempt in range(1, self.max_attempts + 1):
            # ── 1. Run cosim ─────────────────────────────────────────
            r = server.cosim(code)
            state.results.append(r)
            state.log(f"structural repair attempt {attempt}: cosim {r.brief()}")

            if r.ok:
                state.kernel = code
                state.cosim_ok = True
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
