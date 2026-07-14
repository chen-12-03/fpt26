from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any


class LLMResponseError(ValueError):
    pass


@dataclass(frozen=True)
class LLMCallRecord:
    purpose: str | None
    model: str
    model_version: str | None
    license: str
    source: str
    prompt_sha256: str
    attempt_index: int
    status: str
    http_status: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    usage_source: str
    elapsed_seconds: float | None
    error_type: str | None
    error_message: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "model": self.model,
            "model_version": self.model_version,
            "license": self.license,
            "source": self.source,
            "prompt_sha256": self.prompt_sha256,
            "attempt_index": self.attempt_index,
            "status": self.status,
            "http_status": self.http_status,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "usage_source": self.usage_source,
            "elapsed_seconds": self.elapsed_seconds,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class LLMResponse:
    status: str
    content: str | None
    parsed: Any
    model: str
    purpose: str | None
    prompt_sha256: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    usage_source: str
    elapsed_seconds: float | None
    attempt_count: int
    error_type: str | None
    error_message: str | None
    model_version: str | None = None
    license: str | None = None
    source: str | None = None
    attempts: list[LLMCallRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "content": self.content,
            "parsed": self.parsed,
            "model": self.model,
            "model_version": self.model_version,
            "license": self.license,
            "source": self.source,
            "purpose": self.purpose,
            "prompt_sha256": self.prompt_sha256,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "usage_source": self.usage_source,
            "elapsed_seconds": self.elapsed_seconds,
            "attempt_count": self.attempt_count,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }


def prompt_sha256(messages: list[dict[str, Any]]) -> str:
    canonical = json.dumps(messages, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_structured_json(content: str) -> Any:
    text = content.strip()
    if not text:
        raise LLMResponseError("LLM response content is empty")

    fences = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    non_empty_fences = [fence.strip() for fence in fences if fence.strip()]
    if len(non_empty_fences) > 1:
        raise LLMResponseError("LLM response contained multiple JSON code fences")
    if len(non_empty_fences) == 1:
        return _loads_json(non_empty_fences[0])

    try:
        return _loads_json(text)
    except LLMResponseError:
        fragments = _json_fragments(text)
        if len(fragments) == 1:
            return _loads_json(fragments[0])
        if len(fragments) > 1:
            raise LLMResponseError("LLM response contained multiple JSON objects")
        raise


def validate_json_schema(value: Any, schema: dict[str, Any]) -> None:
    errors: list[str] = []
    _validate(value, schema, "$", errors)
    if errors:
        raise LLMResponseError("schema validation failed: " + "; ".join(errors))


def _loads_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMResponseError(f"LLM response JSON is invalid: {exc.msg}") from exc


def _json_fragments(text: str) -> list[str]:
    decoder = json.JSONDecoder()
    fragments: list[str] = []
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            _value, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        fragments.append(text[index : index + end])
    return fragments


def _validate(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if not isinstance(schema, dict):
        errors.append(f"{path}: schema must be an object")
        return

    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or value not in enum:
            errors.append(f"{path}: value is not in enum")
            return

    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if not any(_type_matches(value, item) for item in expected_type):
            errors.append(f"{path}: expected one of {expected_type}")
            return
    elif isinstance(expected_type, str):
        if not _type_matches(value, expected_type):
            errors.append(f"{path}: expected {expected_type}")
            return

    if expected_type == "object" or isinstance(value, dict):
        if not isinstance(value, dict):
            return
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if key not in value:
                    errors.append(f"{path}.{key}: missing required field")
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if key in value:
                    _validate(value[key], child_schema, f"{path}.{key}", errors)
        if schema.get("additionalProperties") is False and isinstance(properties, dict):
            extra = sorted(set(value) - set(properties))
            for key in extra:
                errors.append(f"{path}.{key}: unexpected field")

    if expected_type == "array" or isinstance(value, list):
        if not isinstance(value, list):
            return
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate(item, item_schema, f"{path}[{index}]", errors)


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True
