#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.llm.config import LLMConfig, LLMConfigError
from agent.llm.llm_client import LLMClient, LLMClientError, LLMConnectionError, LLMHTTPError, LLMTimeoutError
from agent.llm.schemas import LLMResponseError, prompt_sha256


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
    messages = _build_messages(prompt, system_prompt)
    response = LLMClient(config=config).generate(messages, purpose="legacy_call_chat_completion")
    if response.status != "ok":
        _raise_legacy_error(response.error_type, response.error_message)
    return LLMCallResult(
        model=response.model,
        response_text=response.content or "",
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        total_tokens=response.total_tokens,
        elapsed_seconds=response.elapsed_seconds or 0.0,
        prompt_hash=response.prompt_sha256,
    )


def prompt_hash(prompt: str, *, system_prompt: str | None = None) -> str:
    return prompt_sha256(_build_messages(prompt, system_prompt))


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


def _raise_legacy_error(error_type: str | None, error_message: str | None) -> None:
    message = error_message or "LLM call failed"
    if error_type == "LLMTimeoutError":
        raise LLMTimeoutError(message)
    if error_type == "LLMHTTPError":
        raise LLMHTTPError(message)
    if error_type == "LLMConnectionError":
        raise LLMConnectionError(message)
    if error_type == "LLMResponseError":
        raise LLMResponseError(message)
    raise LLMClientError(message)
