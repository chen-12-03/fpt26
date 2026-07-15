from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from llm4hls import config as official_harness_config


CHAT_COMPLETIONS_PATH = "/chat/completions"
DEFAULT_BASE_URL = official_harness_config.OPENROUTER_BASE_URL
DEFAULT_MODEL = official_harness_config.DEFAULT_LLM_MODEL
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_OUTPUT_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.7
DEFAULT_LICENSE = "Open-source model required by LLM4HLS Track-A"
DEFAULT_SOURCE = "OpenRouter"
DEFAULT_MAX_RETRIES = 0


class LLMConfigError(ValueError):
    pass


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    api_key: str | None
    timeout_seconds: float
    max_output_tokens: int
    temperature: float
    license: str
    source: str
    model_version: str | None = None
    max_retries: int = DEFAULT_MAX_RETRIES
    max_call_total_tokens: int | None = None
    max_total_tokens: int | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LLMConfig":
        source = os.environ if env is None else env
        errors: list[str] = []
        base_url = _value_or_default(source, "FPT26_LLM_BASE_URL", DEFAULT_BASE_URL)
        model = _value_or_default(source, "FPT26_LLM_MODEL", DEFAULT_MODEL)
        timeout = _positive_float(
            _value_or_default(source, "FPT26_LLM_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)),
            "FPT26_LLM_TIMEOUT_SECONDS",
            errors,
        )
        max_output = _positive_int(
            _value_or_default(source, "FPT26_LLM_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS)),
            "FPT26_LLM_MAX_OUTPUT_TOKENS",
            errors,
        )
        temperature = _non_negative_float(
            _value_or_default(source, "FPT26_LLM_TEMPERATURE", str(DEFAULT_TEMPERATURE)),
            "FPT26_LLM_TEMPERATURE",
            errors,
        )
        license_text = _value_or_default(source, "FPT26_LLM_LICENSE", DEFAULT_LICENSE)
        model_source = _value_or_default(source, "FPT26_LLM_SOURCE", DEFAULT_SOURCE)
        api_key = _optional(source, "FPT26_LLM_API_KEY") or _optional(source, "OPENROUTER_API_KEY")
        model_version = _optional(source, "FPT26_LLM_MODEL_VERSION")
        max_retries = _non_negative_int(
            _value_or_default(source, "FPT26_LLM_MAX_RETRIES", str(DEFAULT_MAX_RETRIES)),
            "FPT26_LLM_MAX_RETRIES",
            errors,
        )
        max_call_total = _optional_positive_int(source, "FPT26_LLM_MAX_CALL_TOTAL_TOKENS", errors)
        max_total = _optional_positive_int(source, "FPT26_LLM_MAX_TOTAL_TOKENS", errors)

        if _is_official_openrouter_base(base_url) and api_key is None:
            errors.append("missing OpenRouter token: set FPT26_LLM_API_KEY or OPENROUTER_API_KEY")

        if errors:
            raise LLMConfigError("; ".join(errors))

        return cls(
            base_url=base_url.rstrip("/"),
            model=model,
            api_key=api_key,
            timeout_seconds=timeout,
            max_output_tokens=max_output,
            temperature=temperature,
            license=license_text,
            source=model_source,
            model_version=model_version,
            max_retries=max_retries,
            max_call_total_tokens=max_call_total,
            max_total_tokens=max_total,
        )

    @property
    def chat_completions_url(self) -> str:
        if self.base_url.endswith(CHAT_COMPLETIONS_PATH):
            return self.base_url
        return f"{self.base_url}{CHAT_COMPLETIONS_PATH}"

    def metadata_dict(self) -> dict[str, str | None]:
        return {
            "model": self.model,
            "model_version": self.model_version,
            "license": self.license,
            "source": self.source,
        }


def _value_or_default(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _optional(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _positive_float(value: str, name: str, errors: list[str]) -> float:
    try:
        parsed = float(value)
    except ValueError:
        errors.append(f"{name} must be a positive number")
        return 0.0
    if parsed <= 0:
        errors.append(f"{name} must be a positive number")
    return parsed


def _non_negative_float(value: str, name: str, errors: list[str]) -> float:
    try:
        parsed = float(value)
    except ValueError:
        errors.append(f"{name} must be a non-negative number")
        return 0.0
    if parsed < 0:
        errors.append(f"{name} must be a non-negative number")
    return parsed


def _positive_int(value: str, name: str, errors: list[str]) -> int:
    try:
        parsed = int(value)
    except ValueError:
        errors.append(f"{name} must be a positive integer")
        return 0
    if parsed <= 0:
        errors.append(f"{name} must be a positive integer")
    return parsed


def _non_negative_int(value: str, name: str, errors: list[str]) -> int:
    try:
        parsed = int(value)
    except ValueError:
        errors.append(f"{name} must be a non-negative integer")
        return 0
    if parsed < 0:
        errors.append(f"{name} must be a non-negative integer")
    return parsed


def _optional_positive_int(env: Mapping[str, str], name: str, errors: list[str]) -> int | None:
    value = _optional(env, name)
    if value is None:
        return None
    return _positive_int(value, name, errors)


def _is_official_openrouter_base(base_url: str) -> bool:
    return base_url.rstrip("/") == DEFAULT_BASE_URL.rstrip("/")
