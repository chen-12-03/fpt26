"""LLM backend factory — returns :class:`LLMExecutor` wrappers.

Thin wrapper around ``llm4hls.llm.create_llm()`` so agent code doesn't
need to know which backend is active.  All production paths should obtain
their LLM through ``create_llm()`` or ``create_scripted_client()``.
"""

from __future__ import annotations

import os

from llm4hls.llm import (
    LLMClient,
    OpenAICompatClient,
    OpenRouterClient,
    ScriptedClient,
    create_llm as _official_create_llm,
)
from agent.integrations.llm.protocol import LLMExecutor, LLMConfig


def create_llm(backend: str = "auto") -> LLMExecutor:
    """Create an LLM executor based on environment or explicit choice.

    Returns an :class:`LLMExecutor` wrapping the raw client with retry,
    timeout, and token-budget tracking.  The underlying client is still
    a ``llm4hls.llm.LLMClient`` for backward compatibility.
    """
    raw = _official_create_llm(backend)
    cfg = LLMConfig(
        model=getattr(raw, "model", "") or os.environ.get("FPT26_LLM_MODEL", ""),
        temperature=float(os.environ.get("FPT26_LLM_TEMPERATURE", "0.7")),
        max_tokens=int(os.environ.get("FPT26_LLM_MAX_TOKENS", "4096")),
        timeout_s=float(os.environ.get("FPT26_LLM_TIMEOUT_SECONDS", "180")),
        max_retries=int(os.environ.get("FPT26_LLM_MAX_RETRIES", "2")),
    )
    return LLMExecutor(raw, cfg)


def create_scripted_client(responses: list[str]) -> LLMExecutor:
    """Create an offline executor that replays canned responses in order."""
    from agent.integrations.llm.scripted import ScriptedLLM
    return LLMExecutor(ScriptedLLM(responses), LLMConfig(model="scripted"))
