"""LLM prompt builders for the v2 agent.

Adapted from v1, but accepting the official ``Task`` object instead of
the v1-specific ``TaskContext``.  See the migration notes in roadmap.md
for the field mapping.
"""

from __future__ import annotations

import json
from typing import Any

from llm4hls.task import Task

from agent.analysis.issue_classifier import IssueClassification
from agent.analysis.log_normalizer import NormalizedLog

# ── System prompts ──────────────────────────────────────────────────────

REPAIR_SYSTEM = (
    "You are an expert FPGA/HLS engineer repairing a single HLS C/C++ kernel. "
    "Output ONLY the full kernel source inside a ```cpp fenced block. "
    "Do NOT modify the top function signature, headers, or testbenches. "
    "Focus on fixing the reported error while preserving functional correctness."
)

OPTIMIZE_SYSTEM = (
    "You are an expert FPGA/HLS engineer optimizing a correct HLS C/C++ kernel. "
    "Output ONLY the full kernel source inside a ```cpp fenced block. "
    "Do NOT modify the top function signature, headers, or testbenches. "
    "Target lower latency while preserving correctness. "
    "Prefer PIPELINE, UNROLL, ARRAY_PARTITION, DATAFLOW pragmas."
)

STRUCTURAL_REPAIR_SYSTEM = (
    "You are an expert FPGA/HLS engineer fixing a streaming/dataflow deadlock "
    "in an HLS C/C++ kernel. Output ONLY the full kernel source inside a ```cpp "
    "fenced block. Do NOT modify the top function signature, headers, or "
    "testbenches. Focus on rate-balancing producer/consumer streams."
)


# ── Prompt builders ─────────────────────────────────────────────────────


def build_repair_prompt(
    task: Task,
    current_kernel: str,
    normalized_log: NormalizedLog,
    issue: IssueClassification,
    attempt_feedback: dict[str, Any] | None = None,
) -> str:
    """Build a repair prompt for the LLM.

    Returns a JSON string the LLM should complete with diagnosis +
    replacement_kernel.
    """
    header_text = "\n".join(
        f"// {name}\n{code}" for name, code in task.headers.items()
    )
    payload: dict[str, Any] = {
        "task": {
            "task_id": task.id,
            "task_type": task.type,
            "description": task.description,
            "top_function": task.top,
            "requires_cosim": task.requires_cosim,
        },
        "headers": header_text,
        "editable_kernel": f"// {task.kernel_name}\n{current_kernel}",
        "diagnostics": {
            "stage": normalized_log.stage,
            "status": normalized_log.status,
            "error_summary": normalized_log.error_summary,
            "key_lines": normalized_log.key_lines[:10],
            "warnings": normalized_log.warnings[:10],
            "issue_category": issue.issue_category,
            "evidence": issue.evidence[:5],
            "recommended_action": issue.recommended_action,
            "previous_attempt_feedback": attempt_feedback,
        },
        "instruction": (
            "Return the FULL corrected kernel source file. "
            "The replacement_kernel must contain the complete top function definition. "
            "Keep the top function name and signature UNCHANGED. "
            "Do NOT include Markdown code fences in the replacement_kernel field."
        ),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def build_optimize_prompt(
    task: Task,
    current_kernel: str,
    best_latency: int | None,
    baseline_metrics: dict[str, Any] | None = None,
) -> str:
    """Build an optimization prompt for the LLM."""
    header_text = "\n".join(
        f"// {name}\n{code}" for name, code in task.headers.items()
    )
    payload: dict[str, Any] = {
        "task": {
            "task_id": task.id,
            "task_type": task.type,
            "description": task.description,
            "top_function": task.top,
            "requires_cosim": task.requires_cosim,
        },
        "headers": header_text,
        "editable_kernel": f"// {task.kernel_name}\n{current_kernel}",
        "current_best_latency": f"{best_latency} cycles" if best_latency is not None else "unknown",
        "baseline_metrics": baseline_metrics or {},
        "scoring_policy": {
            "correctness_gate": "candidate must pass csim and synth",
            "ppa_proxy": "baseline_latency / candidate_latency (capped at 8x)",
        },
        "instruction": (
            "Return the FULL optimized kernel source file. "
            "Keep the top function name and signature UNCHANGED. "
            "Optimize for LOWER latency. Prefer PIPELINE, UNROLL, ARRAY_PARTITION. "
            "Do NOT sacrifice functional correctness."
        ),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def build_structural_repair_prompt(
    task: Task,
    current_kernel: str,
    cosim_log: str,
) -> str:
    """Build a structural repair prompt for streaming/dataflow deadlocks."""
    header_text = "\n".join(
        f"// {name}\n{code}" for name, code in task.headers.items()
    )
    payload = {
        "task": {
            "task_id": task.id,
            "task_type": task.type,
            "description": task.description,
            "top_function": task.top,
            "requires_cosim": task.requires_cosim,
        },
        "headers": header_text,
        "editable_kernel": f"// {task.kernel_name}\n{current_kernel}",
        "cosim_failure_log_tail": cosim_log[-3000:],
        "instruction": (
            "The design DEADLOCKS in C/RTL co-simulation (likely a streaming/dataflow "
            "issue: bounded RTL FIFOs deadlock while unbounded C-sim FIFOs pass). "
            "Fix the streaming imbalance (e.g. interleave reads/writes, balance "
            "producer/consumer rates). Return the FULL corrected kernel source."
        ),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
