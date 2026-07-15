"""LLM backend factory.

Thin wrapper around ``llm4hls.llm.create_llm()`` so agent code doesn't
need to know which backend is active.
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


def create_llm(backend: str = "auto") -> LLMClient:
    """Create an LLM client based on environment or explicit choice.

    Backend selection (``backend`` parameter):
    * ``"auto"`` — auto-detect from environment variables
    * ``"openrouter"`` — force OpenRouter
    * ``"custom"`` — force custom OpenAI-compatible endpoint
    * ``"scripted"`` — offline canned responses

    Environment variables for custom backend:
    * ``FPT26_LLM_BASE_URL`` — base URL (e.g. http://localhost:8000/v1)
    * ``FPT26_LLM_API_KEY`` — API key (optional)
    * ``FPT26_LLM_MODEL`` — model name
    """
    return _official_create_llm(backend)


def create_scripted_client(responses: list[str]) -> ScriptedClient:
    """Create an offline client that replays canned responses in order."""
    return ScriptedClient(responses)
