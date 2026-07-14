#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.ir import HLSIR, HLSIRValidationError
from agent.llm_client import LLMCallResult, LLMClientError, call_chat_completion


IR_FILENAME = "ir.json"
LLM_METADATA_FILENAME = "llm_call.json"

SYSTEM_PROMPT = """You extract structured HLS task specifications.
Return only JSON that conforms to schema_version hls-ir-v1.
Do not include Markdown, prose, comments, or generated HLS source code.
Use input_mode "natural_language" for natural-language specifications.
If source_file or testbench_file are not materialized yet, set them to null and record that in inferred_fields.
The JSON must include schema_version, task_id, input_mode, top_function, source_file, testbench_file, inputs, outputs, clock_period_ns, hls_part, verification, and inferred_fields."""

USER_PROMPT_TEMPLATE = """Extract a normalized hls-ir-v1 JSON object from this natural-language HLS specification:

{spec_text}
"""


class SpecExtractionError(Exception):
    """Base class for natural-language spec extraction failures."""


class SpecExtractionJSONError(SpecExtractionError):
    """Raised when the LLM response does not contain valid JSON."""


class SpecExtractionValidationError(SpecExtractionError):
    """Raised when extracted JSON is not a valid HLS IR."""


class SpecExtractionLLMError(SpecExtractionError):
    """Raised when the LLM client fails."""


@dataclass(frozen=True)
class SpecExtractionResult:
    ir: HLSIR
    ir_path: Path
    metadata_path: Path
    llm: LLMCallResult


def extract_spec_to_ir(spec_text: str, output_dir: str | Path) -> SpecExtractionResult:
    if not isinstance(spec_text, str) or not spec_text.strip():
        raise SpecExtractionError("spec_text must be a non-empty string")

    prompt = USER_PROMPT_TEMPLATE.format(spec_text=spec_text.strip())
    try:
        llm_result = call_chat_completion(prompt, system_prompt=SYSTEM_PROMPT)
    except LLMClientError as exc:
        raise SpecExtractionLLMError(f"LLM call failed: {exc}") from exc

    data = extract_json_object(llm_result.response_text)
    try:
        ir = HLSIR.from_dict(data)
    except HLSIRValidationError as exc:
        raise SpecExtractionValidationError(f"extracted IR is invalid: {exc}") from exc

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    ir_path = output_path / IR_FILENAME
    metadata_path = output_path / LLM_METADATA_FILENAME
    ir.save(ir_path)
    metadata_path.write_text(
        json.dumps(_metadata_dict(llm_result), indent=2) + "\n",
        encoding="utf-8",
    )

    return SpecExtractionResult(
        ir=ir,
        ir_path=ir_path,
        metadata_path=metadata_path,
        llm=llm_result,
    )


def extract_json_object(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise SpecExtractionJSONError("LLM response text is empty")

    candidate = text.strip()
    if candidate.startswith("{"):
        return _loads_json_object(candidate)

    fenced = _extract_fenced_json(candidate)
    if fenced is not None:
        return _loads_json_object(fenced)

    raise SpecExtractionJSONError("LLM response did not contain a JSON object")


def _extract_fenced_json(text: str) -> str | None:
    pattern = re.compile(r"```\s*(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1).strip()


def _loads_json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SpecExtractionJSONError(f"LLM response JSON is invalid: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise SpecExtractionJSONError("LLM response JSON must be an object")
    return data


def _metadata_dict(llm_result: LLMCallResult) -> dict[str, Any]:
    return {
        "model": llm_result.model,
        "prompt_hash": llm_result.prompt_hash,
        "input_tokens": llm_result.input_tokens,
        "output_tokens": llm_result.output_tokens,
        "total_tokens": llm_result.total_tokens,
        "elapsed_seconds": llm_result.elapsed_seconds,
    }
