"""RepairAgent — LLM-driven repair loop for C-simulation failures.

Open this file to understand the core repair logic::

    for attempt in 1..max_attempts:
        csim(current_kernel)          → ToolResult  (simulate)
        if pass → done                → read result  (read result)
        if fail:
            normalize log             → clean up output
            classify issue            → what kind of failure?
            build prompt              → pack context + error
            llm.complete(prompt)      → LLM modifies code
            extract_code(response)    → parse new kernel
            loop back to csim         → simulate again (decide: retry or stop)
"""

from __future__ import annotations

import re
from typing import Any

from agent.agents.base import RunState
from agent.analysis.issue_classifier import IssueClassifier
from agent.analysis.log_normalizer import LogNormalizer
from agent.prompts import REPAIR_SYSTEM, build_repair_prompt

# Regex to extract ```cpp fenced code blocks from LLM output
_CODE_RE = re.compile(r"```(?:cpp|c\+\+|c)?\s*\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str | None:
    """Extract kernel source from an LLM response."""
    blocks = _CODE_RE.findall(text)
    if blocks:
        return blocks[0].strip() + "\n"
    stripped = text.strip()
    return stripped + "\n" if stripped else None


class RepairAgent:
    """Iteratively repair a kernel that fails C-simulation.

    The loop::

        1. reuse pipeline failed csim, or csim(current_kernel) → ToolResult
        2. if pass → done (repair succeeded)
        3. if fail → normalize log, classify issue
        4. build prompt with error context
        5. llm.complete(system, prompt) → get LLM response
        6. extract_code(response) → new kernel
        7. goto 1 (up to max_attempts)

    This is intentionally explicit — no hidden abstractions.
    """

    def __init__(
        self,
        llm: Any,
        max_attempts: int = 3,
    ) -> None:
        self.llm = llm
        self.max_attempts = max_attempts
        self.log_normalizer = LogNormalizer()
        self.issue_classifier = IssueClassifier()

    def run(self, state: RunState) -> RunState:
        """Run the repair loop. Returns updated RunState."""
        task = state.task
        server = state.server
        code = state.kernel

        # The repair pipeline invokes this agent immediately after baseline
        # C-sim failed.  Reuse that adjacent result for the first diagnosis;
        # standalone calls without such an upstream result still run C-sim.
        initial_csim = state.results[-1] if state.results else None
        reuse_initial_csim = (
            getattr(initial_csim, "kind", None) == "csim"
            and not getattr(initial_csim, "ok", False)
        )

        for attempt in range(1, self.max_attempts + 1):
            # ── 1. C-simulate current code ────────────────────────────────
            if attempt == 1 and reuse_initial_csim:
                r = initial_csim
                state.log("repair: reusing pipeline C-sim failure")
            else:
                r = server.csim(code)
                state.results.append(r)
            state.log(f"repair attempt {attempt}: {r.brief()}")

            if r.ok:
                # ── 2. C-sim passed! Verify synth too ─────────────────────
                sr = server.synth(code)
                state.results.append(sr)
                if sr.ok:
                    state.kernel = code
                    state.csim_ok = True
                    state.synth_ok = True
                    state.status = "completed"
                    state.log(f"repair: succeeded on attempt {attempt}")
                    return state
                # Synth failed — continue to LLM repair with synth error
                r = sr  # use synth failure as the error context

            # ── 3. Read result → normalize log → classify issue ───────────
            log_text = getattr(r, "log", "") or ""
            phase = getattr(r, "phase", "unknown") or "unknown"
            kind = getattr(r, "kind", "csim") or "csim"

            normalized = self.log_normalizer.normalize(kind, phase, log_text)
            issue = self.issue_classifier.classify(r, normalized)

            # ── 4. Build prompt with error context ────────────────────────
            prompt = build_repair_prompt(
                task=task,
                current_kernel=code,
                normalized_log=normalized,
                issue=issue,
                attempt_feedback=(
                    {"attempt": attempt, "phase": phase}
                    if attempt > 1 else None
                ),
            )

            # ── 5. LLM modifies code ──────────────────────────────────────
            response = self.llm.complete(REPAIR_SYSTEM, prompt)
            new_code = extract_code(response)
            if new_code is None or new_code.strip() == code.strip():
                state.log(f"repair attempt {attempt}: LLM returned no change")
                continue

            # ── 6. Update code and loop back ──────────────────────────────
            code = new_code

        # Max attempts exhausted
        state.kernel = code
        state.status = "repair_failed"
        state.log(f"repair: failed after {self.max_attempts} attempts")
        return state
