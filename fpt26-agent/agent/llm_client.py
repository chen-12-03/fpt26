#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


CHAT_COMPLETIONS_PATH = "/chat/completions"


class LLMClientError(Exception):
    """Base class for LLM client failures."""


class LLMConfigError(LLMClientError):
    """Raised when required LLM configuration is missing or invalid."""


class LLMTimeoutError(LLMClientError):
    """Raised when the LLM request times out."""


class LLMHTTPError(LLMClientError):
    """Raised when the LLM service returns a non-2xx HTTP response."""


class LLMResponseError(LLMClientError):
    """Raised when the LLM service response is malformed."""


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    api_key: str | None
    timeout_seconds: float
    max_output_tokens: int

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LLMConfig":
        source = os.environ if env is None else env
        errors: list[str] = []

        base_url = _required_env(source, "LLM_BASE_URL", errors)
        model = _required_env(source, "LLM_MODEL", errors)
        timeout_text = _required_env(source, "LLM_TIMEOUT_SECONDS", errors)
        max_output_text = _required_env(source, "LLM_MAX_OUTPUT_TOKENS", errors)
        api_key = _optional_env(source, "LLM_API_KEY")

        timeout_seconds = _parse_positive_float(timeout_text, "LLM_TIMEOUT_SECONDS", errors)
        max_output_tokens = _parse_positive_int(max_output_text, "LLM_MAX_OUTPUT_TOKENS", errors)

        if errors:
            raise LLMConfigError("; ".join(errors))

        return cls(
            base_url=base_url.rstrip("/"),
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
        )

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url}{CHAT_COMPLETIONS_PATH}"


@dataclass(frozen=True)
class LLMCallResult:
    model: str
    response_text: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    elapsed_seconds: float
    prompt_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "response_text": self.response_text,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "elapsed_seconds": self.elapsed_seconds,
            "prompt_hash": self.prompt_hash,
        }


def call_chat_completion(
    prompt: str,
    *,
    system_prompt: str | None = None,
    config: LLMConfig | None = None,
) -> LLMCallResult:
    active_config = LLMConfig.from_env() if config is None else config
    messages = _build_messages(prompt, system_prompt)
    payload = {
        "model": active_config.model,
        "messages": messages,
        "max_tokens": active_config.max_output_tokens,
    }
    request = _build_request(active_config, payload)
    started = time.perf_counter()

    try:
        with urllib.request.urlopen(request, timeout=active_config.timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
    except TimeoutError as exc:
        raise LLMTimeoutError(f"LLM request timed out after {active_config.timeout_seconds} seconds") from exc
    except socket.timeout as exc:
        raise LLMTimeoutError(f"LLM request timed out after {active_config.timeout_seconds} seconds") from exc
    except urllib.error.HTTPError as exc:
        reason = getattr(exc, "reason", exc.msg)
        raise LLMHTTPError(f"LLM service returned HTTP {exc.code}: {reason}") from exc
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, socket.timeout):
            raise LLMTimeoutError(f"LLM request timed out after {active_config.timeout_seconds} seconds") from exc
        raise LLMHTTPError(f"LLM request failed: {reason}") from exc

    elapsed_seconds = time.perf_counter() - started
    data = _parse_response_json(response_body)
    response_text = _extract_response_text(data)
    usage = data.get("usage")
    usage_data = usage if isinstance(usage, dict) else {}

    return LLMCallResult(
        model=active_config.model,
        response_text=response_text,
        input_tokens=_optional_int(usage_data.get("prompt_tokens")),
        output_tokens=_optional_int(usage_data.get("completion_tokens")),
        total_tokens=_optional_int(usage_data.get("total_tokens")),
        elapsed_seconds=elapsed_seconds,
        prompt_hash=prompt_hash(prompt, system_prompt=system_prompt),
    )


def prompt_hash(prompt: str, *, system_prompt: str | None = None) -> str:
    messages = _build_messages(prompt, system_prompt)
    canonical = json.dumps(messages, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_messages(prompt: str, system_prompt: str | None) -> list[dict[str, str]]:
    if not isinstance(prompt, str) or not prompt:
        raise LLMConfigError("prompt must be a non-empty string")
    messages: list[dict[str, str]] = []
    if system_prompt is not None:
        if not isinstance(system_prompt, str) or not system_prompt:
            raise LLMConfigError("system_prompt must be a non-empty string when provided")
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages


def _build_request(config: LLMConfig, payload: dict[str, Any]) -> urllib.request.Request:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    body = json.dumps(payload).encode("utf-8")
    return urllib.request.Request(
        config.chat_completions_url,
        data=body,
        headers=headers,
        method="POST",
    )


def _parse_response_json(response_body: str) -> dict[str, Any]:
    try:
        data = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise LLMResponseError("LLM service returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise LLMResponseError("LLM service response must be a JSON object")
    return data


def _extract_response_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMResponseError("LLM response missing choices")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise LLMResponseError("LLM response choice must be a JSON object")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise LLMResponseError("LLM response choice missing message")
    content = message.get("content")
    if not isinstance(content, str):
        raise LLMResponseError("LLM response message content must be a string")
    return content


def _required_env(env: Mapping[str, str], name: str, errors: list[str]) -> str:
    value = env.get(name)
    if value is None or not value.strip():
        errors.append(f"missing required environment variable: {name}")
        return ""
    return value.strip()


def _optional_env(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _parse_positive_float(value: str, name: str, errors: list[str]) -> float:
    if not value:
        return 0.0
    try:
        parsed = float(value)
    except ValueError:
        errors.append(f"{name} must be a positive number")
        return 0.0
    if parsed <= 0:
        errors.append(f"{name} must be a positive number")
    return parsed


def _parse_positive_int(value: str, name: str, errors: list[str]) -> int:
    if not value:
        return 0
    try:
        parsed = int(value)
    except ValueError:
        errors.append(f"{name} must be a positive integer")
        return 0
    if parsed <= 0:
        errors.append(f"{name} must be a positive integer")
    return parsed


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    return None
