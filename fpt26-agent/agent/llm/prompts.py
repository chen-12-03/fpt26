from __future__ import annotations

import json
from typing import Any

from agent.analysis.issue_classifier import IssueClassification
from agent.analysis.log_normalizer import NormalizedLog
from agent.analysis.cosim_analyzer import CoSimDiagnosis
from agent.analysis.stream_analyzer import StreamAnalysis
from agent.core.task_context import TaskContext


REPAIR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["diagnosis", "replacement_kernel", "changes", "confidence"],
    "additionalProperties": False,
    "properties": {
        "diagnosis": {"type": "string", "minLength": 1},
        "replacement_kernel": {"type": "string", "minLength": 1},
        "changes": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
}


STRUCTURAL_REPAIR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "diagnosis",
        "repair_strategy",
        "affected_streams",
        "replacement_kernel",
        "changes",
        "confidence",
    ],
    "additionalProperties": False,
    "properties": {
        "diagnosis": {"type": "string", "minLength": 1},
        "repair_strategy": {"type": "string", "minLength": 1},
        "affected_streams": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "replacement_kernel": {"type": "string", "minLength": 1},
        "changes": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
}


OPTIMIZATION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "diagnosis",
        "optimization_strategy",
        "replacement_kernel",
        "changes",
        "expected_latency_impact",
        "confidence",
    ],
    "additionalProperties": False,
    "properties": {
        "diagnosis": {"type": "string", "minLength": 1},
        "optimization_strategy": {"type": "string", "minLength": 1},
        "replacement_kernel": {"type": "string", "minLength": 1},
        "changes": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "expected_latency_impact": {"type": "string", "minLength": 1},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
}


def build_repair_messages(
    *,
    task_context: TaskContext,
    current_kernel: str,
    normalized_log: NormalizedLog,
    issue: IssueClassification,
    attempt_feedback: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    system = (
        "You are repairing a single HLS C/C++ kernel for an LLM4HLS task. "
        "Return only JSON matching the provided schema. Do not modify headers, "
        "testbenches, build scripts, the top function name, or the top function signature. "
        "The replacement_kernel field must be a complete C/C++ source file containing "
        "the unchanged top function signature and full function body, not prose or a patch."
    )
    payload = {
        "task": {
            "task_id": task_context.task_id,
            "task_type": task_context.task_type,
            "description": task_context.description,
            "top_function": task_context.top_function,
            "numeric_tolerance": task_context.numeric_tolerance,
            "design_constraints": task_context.design_constraints,
            "requires_cosim": task_context.requires_cosim,
        },
        "editable_kernel": current_kernel,
        "diagnostics": {
            "stage": normalized_log.stage,
            "status": normalized_log.status,
            "error_summary": normalized_log.error_summary,
            "warnings": normalized_log.warnings[:10],
            "key_lines": normalized_log.key_lines[:10],
            "issue_category": issue.issue_category,
            "evidence": issue.evidence[:5],
            "recommended_action": issue.recommended_action,
            "previous_attempt_feedback": attempt_feedback,
        },
        "instructions": [
            "Return one complete replacement kernel source file.",
            "The replacement_kernel string must contain the full top function definition.",
            "Keep the top function name and complete function signature unchanged.",
            "Only modify the kernel implementation.",
            "Do not introduce new local include files.",
            "Do not include Markdown code fences.",
            "Use plain ASCII quotes for #include directives and preserve newlines around comments and code.",
        ],
    }
    user = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_optimization_messages(
    *,
    task_context: TaskContext,
    current_kernel: str,
    baseline_metrics: dict[str, Any],
    current_metrics: dict[str, Any],
    bottleneck_hints: list[str],
    budget_summary: dict[str, Any],
    attempt_feedback: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    system = (
        "You are optimizing a single functionally correct HLS C/C++ kernel for an "
        "LLM4HLS task. Return only JSON matching the provided schema. Do not modify "
        "headers, testbenches, build scripts, the top function name, or the top "
        "function signature. Optimize for lower latency while preserving functional "
        "correctness and synthesizability on AMD Vitis HLS 2025.2."
    )
    payload = {
        "task": {
            "task_id": task_context.task_id,
            "task_type": task_context.task_type,
            "description": task_context.description,
            "top_function": task_context.top_function,
            "interface_contract": task_context.interface_contract,
            "numeric_tolerance": task_context.numeric_tolerance,
            "design_constraints": task_context.design_constraints,
            "requires_cosim": task_context.requires_cosim,
        },
        "editable_kernel": current_kernel,
        "baseline_synth_metrics": baseline_metrics,
        "current_best_synth_metrics": current_metrics,
        "bottleneck_hints": bottleneck_hints,
        "budget": budget_summary,
        "scoring_policy": {
            "correctness_gate": "candidate must pass public csim and synth before selection",
            "ppa_proxy": "prefer lower synthesis latency; official grade uses baseline_latency / candidate_latency",
            "acceleration_cap": 8.0,
        },
        "previous_attempt_feedback": attempt_feedback,
        "instructions": [
            "Return one complete replacement kernel source file.",
            "Keep the top function name and complete top signature unchanged.",
            "Only modify the kernel implementation file.",
            "Do not introduce new local include files.",
            "Do not include Markdown code fences.",
            "Prefer low-risk HLS techniques such as PIPELINE, UNROLL, ARRAY_PARTITION, DATAFLOW, and loop restructuring.",
            "Do not sacrifice correctness for latency.",
        ],
    }
    user = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_structural_repair_messages(
    *,
    task_context: TaskContext,
    current_kernel: str,
    stream_analysis: StreamAnalysis,
    cosim_diagnosis: CoSimDiagnosis,
    budget_summary: dict[str, Any],
) -> list[dict[str, str]]:
    system = (
        "You are repairing one HLS C/C++ kernel for an LLM4HLS structural "
        "Co-simulation failure. Return only JSON matching the provided schema. "
        "Do not modify headers, testbenches, build scripts, the top function "
        "name, or the top function signature. Do not include Markdown fences."
    )
    payload = {
        "task": {
            "task_id": task_context.task_id,
            "task_type": task_context.task_type,
            "description": task_context.description,
            "top_function": task_context.top_function,
            "interface_contract": task_context.interface_contract,
            "numeric_tolerance": task_context.numeric_tolerance,
            "design_constraints": task_context.design_constraints,
            "requires_cosim": task_context.requires_cosim,
        },
        "editable_kernel": current_kernel,
        "stream_structure_summary": stream_analysis.to_dict(),
        "cosim_diagnosis": {
            "status": cosim_diagnosis.status,
            "category": cosim_diagnosis.category,
            "confidence": cosim_diagnosis.confidence,
            "summary": cosim_diagnosis.summary,
            "evidence": cosim_diagnosis.evidence[:8],
            "affected_streams": cosim_diagnosis.affected_streams,
            "recommended_action": cosim_diagnosis.recommended_action,
        },
        "budget": budget_summary,
        "allowed_reasoning_scope": [
            "producer/consumer count mismatch",
            "conditional branches that leave streams unread or unwritten",
            "read ordering that creates circular waiting",
            "dataflow task boundary problems",
            "insufficient FIFO depth when it is a general safe fix",
            "incorrect stream bypass or residual path scheduling",
        ],
        "instructions": [
            "Return one complete replacement kernel source file.",
            "Only modify the kernel implementation file.",
            "Keep the top function name and complete top signature unchanged.",
            "Do not introduce new local include files.",
            "Do not modify or quote the public testbench.",
            "Prefer a minimal structural change that resolves Co-sim deadlock while preserving C-sim behavior.",
        ],
    }
    user = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
