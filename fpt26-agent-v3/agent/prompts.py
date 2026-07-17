"""Role-scoped prompts driven by real tool results."""
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
   The objective is the current unified hardware quality, NOT cycle latency alone. Effective latency is `max(target clock, estimated clock) × worst-case cycles`; area quality is limited by the WORST resource growth across LUT, FF, DSP, BRAM_18K, and URAM. Equal proportional speedup and resource growth cancel out (neutral Q_HW); you must achieve speedup ratio > worst-growth ratio to exceed baseline quality. A lower cycle count can be a worse design when clock period or any resource explodes.
2. **Diagnose the bottleneck precisely:**
   - Loop PipelineII violation → timing? recurrence? memory-port pressure? interface bandwidth? The top-function transaction Interval is NOT a loop's achieved II. For nested loops with II>1, always try PIPELINE II=1 on the innermost loop first before considering UNROLL or ARRAY_PARTITION.
   - High latency → which loop dominates? For nested loops: PIPELINE the innermost loop first (best ROI). If outer loop dominates, pipeline the outer loop (forces inner concurrency — check memory ports).
   - Resource explosion → FF/LUT > 5x usually means over-unrolling. Reduce UNROLL factor.
   - Cosim DEADLOCK → stream depth, DATAFLOW ordering, producer/consumer rate balance.
3. **Apply ONE pragma class per iteration.** Re-synthesize and compare reports against previous run.
4. **If a directive does NOT improve the limiting metric, REMOVE or revise it.** Do not accumulate ineffective directives.
5. **Never apply both ARRAY_PARTITION and ARRAY_RESHAPE to the same variable.**
6. **DATAFLOW regions need explicit stream depths** for cosim safety.
7. Prefer a conservative partial UNROLL first for long loops. Add matching partial ARRAY_PARTITION only after Vitis reports memory-port pressure; never speculatively partition large top-level arrays. Never fully unroll a long reduction just to minimize cycle count; keep the worst resource growth controlled and check estimated clock after synthesis.

## Pipeline & II Rules
- PIPELINE II=<n> on the loop/function that directly controls throughput.
- A loop-scoped PIPELINE or UNROLL directive belongs inside the loop body immediately after its opening brace. A PIPELINE at function-body scope pipelines the function and may flatten/auto-unroll contained loops.
- If a loop already reports PipelineII=1, do not add another PIPELINE or infer a memory-port problem from the top-function transaction Interval.
- If II=1 fails: classify cause (timing/recurrence/memory-port/bandwidth) before adding more pragmas.
- Pipelining an outer loop forces inner-loop concurrency — this is an architectural decision that can expose memory bandwidth bottlenecks.

## Array Partition & Reshape
- ARRAY_PARTITION: creates parallel banks/elements for concurrent access. Grows LUT/FF/BRAM.
- ARRAY_RESHAPE: widens storage word while preserving packed view. Use when adjacent elements move together.
- Match dim, type, factor to the access pattern in the bottleneck.
- For a long vector reduction already at PipelineII=1: first test a small loop-local partial UNROLL factor such as 2 while leaving top-level arrays unchanged. Add banking only if the next Vitis report proves port pressure.

## Dataflow & Streaming
- DATAFLOW: use after design has clear producer/compute/consumer stages.
- Connect stages via hls::stream<T> with explicit .depth(N) for every inter-stage channel.
- **Critical cosim rule:** never write one entire stream before touching another stream in the same producer stage. Always interleave writes to all streams in a single loop body.
- C-simulation CANNOT detect streaming deadlocks — only cosim reveals them.

## Stopping Criteria
- Three consecutive rounds with no scoring_v3 Q_HW improvement → stop and submit best candidate. You have up to 3 attempts to find one improvement; use each round to try a different pragma class or factor.
- Reject a candidate when reduced cycles are outweighed by clock-period or worst-resource growth.
- If Q_HW cannot be improved without breaking csim/cosim → stop and submit current best."""

REPAIR_SYSTEM = """You are an expert AMD-Xilinx Vitis HLS C/C++ repair engineer.

Output ONLY the full kernel source inside a ```cpp fenced block.
Do NOT modify the top function signature, headers, or testbenches.

The public C-simulation failed. Read the provided failure log and make the smallest functional correction supported by that evidence. Preserve every unrelated branch, expression, type, interface, and comment when practical. Common defects are a missing arithmetic term, wrong variable, wrong branch formula, or off-by-one bound.

Do NOT add, remove, or tune HLS pragmas while repairing functional correctness. Do not optimize latency, resources, or style. If a prior attempt failed, change the bug hypothesis rather than accumulating edits. Return the complete corrected kernel source."""

STRUCTURAL_REPAIR_SYSTEM = """You are an expert AMD-Xilinx Vitis HLS streaming and DATAFLOW repair engineer.

Output ONLY the full kernel source inside a ```cpp fenced block.
Do NOT modify the top function signature, headers, or testbenches.

C-simulation passed but real RTL co-simulation deadlocked or timed out. C-sim hls::stream FIFOs are unbounded and can hide this bug; RTL FIFOs are bounded. Diagnose producer/consumer ordering and rate balance from the kernel and cosim log. The primary fix for sibling-stream bursts is to interleave writes to all sibling streams in one producer loop. Never produce an entire sibling stream before touching the others in the same DATAFLOW path.

If streams already have explicit positive depths, preserve those depth pragmas exactly. Do NOT increase FIFO depth to mask sequential producer ordering: it adds FF/LUT and leaves the structural cause in place. Consider a depth change only when ordering and rates are already balanced and the log/kernel proves an unavoidable bounded burst.

Make only the minimal structural fix. Preserve arithmetic, interfaces, and unrelated pragmas; do not perform QoR optimization. Return the complete corrected kernel source."""

# OptimizeAgent retains the full scorer-aware HLS discipline.
OPTIMIZE_SYSTEM = _SYS
SYSTEM = OPTIMIZE_SYSTEM

_PROMPT_CODE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".inc",
    ".ipp",
    ".tpp",
}


def _prompt_header_context(headers: dict[str, str]) -> tuple[str, list[str]]:
    """Expose interface code to the LLM without serializing data attachments."""
    code_headers: list[str] = []
    omitted: list[str] = []
    for name, code in headers.items():
        suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if suffix in _PROMPT_CODE_SUFFIXES:
            code_headers.append(f"// {name}\n{code}")
        else:
            omitted.append(name)
    return "\n".join(code_headers), omitted


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
    rejection_feedback: dict[str, Any] | None = None,
    action_contract: dict[str, Any] | None = None,
) -> str:
    header_text, omitted_attachments = _prompt_header_context(task.headers)

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

    if omitted_attachments:
        payload["omitted_non_code_attachments"] = sorted(omitted_attachments)

    if bottleneck_hint:
        payload["bottleneck_diagnosis"] = bottleneck_hint
    if knowledge_hint:
        payload["optimization_patterns"] = knowledge_hint
    if resource_delta:
        payload["resource_trend"] = resource_delta
    if rejection_feedback:
        payload["previous_candidate_feedback"] = rejection_feedback
    if action_contract:
        payload["measured_action_contract"] = action_contract

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
        "- If all PASSED: apply ONE pragma class to improve scoring_v3 Q_HW, guided by bottleneck diagnosis. "
        "Balance effective latency (clock period × cycles) against the worst resource growth; "
        "do not optimize cycle count alone. Prefer a small loop-local partial unroll first; add array partition only for measured port pressure.\n"
        "- If previous_candidate_feedback.status starts with REJECTED_BY_CSIM: use its exact compiler/runtime evidence "
        "and failed_candidate_diff. Apply required_next_action before considering any new architecture; never blindly "
        "repeat the failed source.\n"
        "- If previous_candidate_feedback.status is REJECTED_BY_SYNTH_EVIDENCE_INTENT: no candidate tool was run because the pragma-only action contradicted a measured HLS bottleneck. Address its exact array/resource evidence with matched banking or real locality code; do not repeat standalone PIPELINE/UNROLL.\n"
        "- If measured_action_contract is present: treat its target, required_candidate_delta, forbidden_as_non_responsive, dimension policy, and verification as hard planning constraints. Implement one recommended minimal trial only when the editable source proves the required dimension; otherwise use its locality alternative or return editable_kernel unchanged.\n"
        "- For other previous_candidate_feedback: the prior candidate was measured and rejected by scoring. "
        "Do NOT repeat its pragma set or architecture. Obey directional_constraint and required_next_action; never "
        "increase a factor when measured resource growth outweighed speedup. If there is no report-supported "
        "resource-neutral alternative, return editable_kernel unchanged.\n"
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
