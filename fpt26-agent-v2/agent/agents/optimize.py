"""OptimizeAgent — LLM-driven optimization loop for latency reduction.

Open this file to understand the optimization logic::

    for round in 1..max_rounds:
        LLM proposes optimized kernel   → LLM modifies code
        csim(candidate)                 → check correctness
        if fail → discard, next round
        synth(candidate)                → get latency
        if latency improved → accept
        else → stop (no further improvement)
"""

from __future__ import annotations

import re
from typing import Any

from llm4hls.task import Task

from agent.agents.base import RunState
from agent.prompts import OPTIMIZE_SYSTEM, build_optimize_prompt

_CODE_RE = re.compile(r"```(?:cpp|c\+\+|c)?\s*\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str | None:
    blocks = _CODE_RE.findall(text)
    if blocks:
        return blocks[0].strip() + "\n"
    stripped = text.strip()
    return stripped + "\n" if stripped else None


def _latency(result: Any) -> int | None:
    """Extract worst-case latency from a synthesis ToolResult."""
    if result is None or result.report is None:
        return None
    rep = result.report
    return rep.latency_worst if rep.latency_worst is not None else rep.latency_avg


class OptimizeAgent:
    """LLM-driven optimization loop for HLS kernel latency.

    The loop::

        1. LLM proposes optimized code based on current best
        2. csim(candidate) — must pass correctness
        3. synth(candidate) — get latency
        4. if latency < best_latency → accept as new best
        5. else → stop (no improvement, avoid wasting budget)

    Also supports deterministic pragma transforms as a lightweight fallback.
    """

    def __init__(
        self,
        llm: Any,
        max_rounds: int = 5,
    ) -> None:
        self.llm = llm
        self.max_rounds = max_rounds

    def run(self, state: RunState) -> RunState:
        task = state.task
        server = state.server
        best = state.kernel
        best_lat = state.best_latency

        # Phase A: LLM-driven optimization rounds
        for round_idx in range(1, self.max_rounds + 1):
            # ── 1. LLM proposes optimized code ─────────────────────────
            prompt = build_optimize_prompt(
                task=task,
                current_kernel=best,
                best_latency=best_lat,
            )
            response = self.llm.complete(OPTIMIZE_SYSTEM, prompt)
            candidate = extract_code(response)

            if candidate is None or candidate.strip() == best.strip():
                state.log(f"optimize round {round_idx}: no change proposed — stopping")
                break

            # ── 2. C-sim: must pass correctness ─────────────────────────
            cr = server.csim(candidate)
            state.results.append(cr)
            if not cr.ok:
                state.log(f"optimize round {round_idx}: broke correctness ({cr.brief()}) — discard")
                continue

            # ── 3. Synth: get latency ───────────────────────────────────
            sr = server.synth(candidate)
            state.results.append(sr)
            if not sr.ok:
                state.log(f"optimize round {round_idx}: synth failed ({sr.brief()}) — discard")
                continue

            lat = _latency(sr)
            state.log(f"optimize round {round_idx}: latency {best_lat} -> {lat}")

            # ── 4. Compare: accept if improved ──────────────────────────
            if lat is not None and (best_lat is None or lat < best_lat):
                best = candidate
                best_lat = lat
                state.log(f"optimize round {round_idx}: ACCEPTED (latency improved)")
            else:
                state.log(f"optimize round {round_idx}: no improvement — stopping")
                break

        # Phase B: Deterministic pragma transforms (lightweight fallback)
        try:
            from agent.transform.transformer import DeterministicTransformer, TransformError
            from agent.transform.actions import TransformAction

            transformer = DeterministicTransformer()
            arrays = transformer.discover_array_parameters(task, best)
            actions: list[TransformAction] = []

            # Discover loops for pipeline/unroll
            loops = _discover_loops(best)
            for loop in loops[:2]:  # max 2 loop targets
                if not loop.get("has_pipeline"):
                    actions.append(TransformAction(
                        action_type="pipeline_loop",
                        target=loop["target"],
                        ii=1,
                    ))
                if not loop.get("has_unroll"):
                    actions.append(TransformAction(
                        action_type="unroll_loop",
                        target=loop["target"],
                        factor=2,
                    ))

            for arr in arrays[:2]:  # max 2 array targets
                actions.append(TransformAction(
                    action_type="array_partition",
                    target=arr,
                    factor=2,
                    dimension=1,
                    partition_mode="cyclic",
                ))

            for action in actions:
                transform_result = transformer.apply(task, best, action)
                if transform_result.status != "pass" or transform_result.kernel_code is None:
                    continue
                transformed_code = transform_result.kernel_code
                # Validate the transformed code
                cr = server.csim(transformed_code)
                state.results.append(cr)
                if not cr.ok:
                    continue
                sr = server.synth(transformed_code)
                state.results.append(sr)
                if not sr.ok:
                    continue
                lat = _latency(sr)
                if lat is not None and (best_lat is None or lat < best_lat):
                    best = transformed_code
                    best_lat = lat
                    state.log(f"optimize: deterministic {action.action_type} improved latency to {lat}")

        except Exception:
            pass  # deterministic transforms are optional; never block the pipeline

        state.kernel = best
        state.best_latency = best_lat
        return state


def _discover_loops(code: str) -> list[dict[str, Any]]:
    """Simple loop discovery: find for-loops with labels."""
    pattern = re.compile(
        r'(?:(\w+)\s*:\s*)?for\s*\(\s*(?:int|unsigned|size_t|ap_uint<\d+>|auto)\s+(\w+)\s*[=;]',
        re.MULTILINE,
    )
    loops: list[dict[str, Any]] = []
    for match in pattern.finditer(code):
        label = match.group(1)
        iterator = match.group(2)
        # Check for existing pragmas near this loop
        start = max(0, match.start() - 200)
        prefix = code[start:match.start()]
        loops.append({
            "target": label or iterator,
            "iterator": iterator,
            "has_pipeline": "PIPELINE" in prefix,
            "has_unroll": "UNROLL" in prefix,
        })
    return loops
