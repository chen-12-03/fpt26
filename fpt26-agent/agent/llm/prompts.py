from __future__ import annotations

import json
from typing import Any

from agent.analysis.issue_classifier import IssueClassification
from agent.analysis.log_normalizer import NormalizedLog
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


def build_repair_messages(
    *,
    task_context: TaskContext,
    current_kernel: str,
    normalized_log: NormalizedLog,
    issue: IssueClassification,
) -> list[dict[str, str]]:
    system = (
        "You are repairing a single HLS C/C++ kernel for an LLM4HLS task. "
        "Return only JSON matching the provided schema. Do not modify headers, "
        "testbenches, build scripts, the top function name, or the top function signature."
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
        },
        "instructions": [
            "Return one complete replacement kernel source file.",
            "Keep the top function name and complete function signature unchanged.",
            "Only modify the kernel implementation.",
            "Do not introduce new local include files.",
            "Do not include Markdown code fences.",
        ],
    }
    user = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
