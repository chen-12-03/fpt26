"""Iter3 Unified prompts — agent self-determines action from tool results only."""
from __future__ import annotations
import json
from typing import Any
from llm4hls.task import Task
from agent.analysis.issue_classifier import IssueClassification
from agent.analysis.log_normalizer import NormalizedLog

_SYS = """You are an expert AMD-Xilinx Vitis HLS engineer optimizing C/C++ kernels for an Alveo U55C (xcu55c-fsvh2892-2L-e, 200 MHz, Vitis 2025.2).

Output ONLY the full kernel source inside a ```cpp fenced block.
Do NOT modify the top function signature, headers, or testbenches.

## Decision Rules (determined by tool results only)
- If csim FAILS: diagnose the functional bug from the error log. Fix ONLY the bug. Do NOT add pragmas. Common bugs: wrong branch formula, missing term in sum, wrong variable name, off-by-one.
- If csim PASSES but cosim DEADLOCKS/TIMEOUT: fix streaming imbalance. C-sim FIFOs are UNBOUNDED (hide deadlocks); RTL cosim FIFOs default to depth 2. The #1 cause: writing one entire stream before touching another in a DATAFLOW region. Fix: interleave writes to ALL streams in a SINGLE loop, OR add explicit stream.depth(N) on every hls::stream.
- If csim AND cosim both PASS (or cosim not needed): optimize for lower latency following the discipline below.

## HLS Optimization Discipline (from hls-generator)
1. **Read synthesis report BEFORE proposing changes.** Inspect: target II, achieved II, latency, loop interval, timing slack, LUT/FF/DSP/BRAM counts.
2. **Diagnose the bottleneck precisely:**
   - II violation → timing? recurrence? memory-port pressure? interface bandwidth?
   - High latency → which loop dominates? Try PIPELINE on that loop.
   - Resource explosion → FF/LUT > 5x usually means over-unrolling. Reduce UNROLL factor.
   - Cosim DEADLOCK → stream depth, DATAFLOW ordering, producer/consumer rate balance.
3. **Apply ONE pragma class per iteration.** Re-synthesize and compare reports against previous run.
4. **If a directive does NOT improve the limiting metric, REMOVE or revise it.** Do not accumulate ineffective directives.
5. **Never apply both ARRAY_PARTITION and ARRAY_RESHAPE to the same variable.**
6. **DATAFLOW regions need explicit stream depths** for cosim safety.

## Pipeline & II Rules
- PIPELINE II=<n> on the loop/function that directly controls throughput.
- If II=1 fails: classify cause (timing/recurrence/memory-port/bandwidth) before adding more pragmas.
- Pipelining an outer loop forces inner-loop concurrency — this is an architectural decision that can expose memory bandwidth bottlenecks.

## Array Partition & Reshape
- ARRAY_PARTITION: creates parallel banks/elements for concurrent access. Grows LUT/FF/BRAM.
- ARRAY_RESHAPE: widens storage word while preserving packed view. Use when adjacent elements move together.
- Match dim, type, factor to the access pattern in the bottleneck.
- For long vector reduction loops: tiled loop + ARRAY_PARTITION cyclic + PIPELINE II=1 on the tiled outer loop is the canonical high-efficiency pattern. Check headers for any available parallel-factor constants.

## Dataflow & Streaming
- DATAFLOW: use after design has clear producer/compute/consumer stages.
- Connect stages via hls::stream<T> with explicit .depth(N) for every inter-stage channel.
- **Critical cosim rule:** never write one entire stream before touching another stream in the same producer stage. Always interleave writes to all streams in a single loop body.
- C-simulation CANNOT detect streaming deadlocks — only cosim reveals them.

## Stopping Criteria
- Two consecutive rounds with no latency improvement → stop and submit best candidate.
- If latency cannot be reduced without breaking csim/cosim → stop and submit current best."""

# Unified — all modes use the same system prompt
SYSTEM = _SYS
REPAIR_SYSTEM = _SYS
OPTIMIZE_SYSTEM = _SYS
STRUCTURAL_REPAIR_SYSTEM = _SYS


def build_prompt(
    task: Task,
    current_kernel: str,
    *,
    csim_result: str = "",
    synth_result: str = "",
    cosim_result: str = "",
    best_latency: int | None = None,
    bottleneck_hint: str = "",
    knowledge_hint: str = "",
    attempt: int = 0,
    resource_delta: str = "",
) -> str:
    header_text = "\n".join(f"// {name}\n{code}" for name, code in task.headers.items())

    payload: dict[str, Any] = {
        "task_id": task.id,
        "description": task.description,
        "top_function": task.top,
        "headers": header_text,
        "editable_kernel": f"// {task.kernel_name}\n{current_kernel}",
        "tool_results": {
            "csim": csim_result or "(not run)",
            "synth": synth_result or "(not run)",
            "cosim": cosim_result or "(not run / N/A)",
        },
        "current_best_latency": f"{best_latency} cycles" if best_latency is not None else "unknown",
    }

    if bottleneck_hint:
        payload["bottleneck_diagnosis"] = bottleneck_hint
    if knowledge_hint:
        payload["optimization_patterns"] = knowledge_hint
    if resource_delta:
        payload["resource_trend"] = resource_delta

    # Streaming context — derived from task properties, not task type label
    if task.requires_cosim:
        payload["cosim_required"] = True
        payload["streaming_warning"] = (
            "C-simulation FIFOs are UNBOUNDED — they hide deadlocks. "
            "RTL cosim FIFOs default to depth 2 and CANNOT buffer large bursts. "
            "If cosim deadlocks: interleave writes to ALL streams in a SINGLE loop, "
            "or add explicit .depth(N) on every hls::stream declaration."
        )

    payload["instruction"] = (
        "Read tool_results carefully. Determine the situation from results alone:\n"
        "- If csim FAILED: fix the functional bug. Do NOT add pragmas.\n"
        "- If cosim DEADLOCKS/TIMEOUT: fix streaming imbalance (interleave writes, add stream depths).\n"
        "- If all PASSED: apply ONE pragma class to optimize latency, guided by bottleneck diagnosis.\n"
        "Return the FULL kernel source code. Keep the top function signature UNCHANGED."
    )
    return json.dumps(payload, indent=2, ensure_ascii=False)


# ── Convenience builders ──────────────────────────────────────────────────

def build_repair_prompt(
    task: Task,
    current_kernel: str,
    normalized_log: NormalizedLog,
    issue: IssueClassification,
    attempt_feedback: dict | None = None,
) -> str:
    extra = ""
    if attempt_feedback and attempt_feedback.get("attempt", 1) > 1:
        extra = (
            "\n[Previous attempt did not fix the issue. "
            "Try a DIFFERENT hypothesis. Re-read the error log carefully.]"
        )
    return build_prompt(
        task=task,
        current_kernel=current_kernel,
        csim_result=f"FAIL: {normalized_log.error_summary}{extra}",
        attempt=attempt_feedback.get("attempt", 1) if attempt_feedback else 1,
    )


def build_optimize_prompt(
    task: Task,
    current_kernel: str,
    best_latency: int | None,
    baseline_metrics: dict | None = None,
    resource_history: str = "",
) -> str:
    synth_str = "PASS"
    if baseline_metrics:
        synth_str = json.dumps(baseline_metrics)
    return build_prompt(
        task=task,
        current_kernel=current_kernel,
        csim_result="PASS",
        synth_result=synth_str,
        best_latency=best_latency,
        resource_delta=resource_history,
    )


def build_structural_repair_prompt(
    task: Task,
    current_kernel: str,
    cosim_log: str,
) -> str:
    return build_prompt(
        task=task,
        current_kernel=current_kernel,
        csim_result="PASS (unbounded FIFOs may hide streaming bugs)",
        cosim_result=f"DEADLOCK/TIMEOUT (bounded RTL FIFOs): {cosim_log[-4000:]}",
    )
