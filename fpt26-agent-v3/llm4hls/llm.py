"""Pluggable LLM backend for the reference agent.

- OpenRouterClient: real backend via OpenRouter (OpenAI-compatible HTTP API).
  The contest mandates OPEN-SOURCE models, so the default is an open-weight
  coder model; pick any open model on OpenRouter with LLM4HLS_MODEL.
- ScriptedClient : replays canned answers in order, ignoring the prompt, so the
  full harness/agent loop is demonstrable offline with no token.

Interface is a single `complete(system, user) -> str`; the agent packs all
context (task + attempt history + latest tool log) into `user` each turn, so
the two clients are interchangeable. Stdlib-only (urllib), no SDK to install.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol

from . import config


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class ScriptedClient:
    """Deterministic offline backend: returns the next canned response."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._i = 0

    def complete(self, system: str, user: str) -> str:
        if not self._responses:
            return ""
        resp = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return resp


class OpenRouterClient:
    """Real backend via OpenRouter's OpenAI-compatible chat-completions API."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> None:
        self.api_key = api_key or config.OPENROUTER_API_KEY
        if not self.api_key:
            raise RuntimeError(
                "OpenRouter token missing. Set OPENROUTER_API_KEY in the environment "
                "or fill OPENROUTER_API_KEY in llm4hls/config.py."
            )
        self.model = model or config.DEFAULT_LLM_MODEL
        self.base_url = config.OPENROUTER_BASE_URL
        self.temperature = temperature
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self.base_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                # Optional attribution headers accepted by OpenRouter:
                "HTTP-Referer": "https://llm4hls.local",
                "X-Title": "LLM4HLS Track A",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"OpenRouter HTTP {e.code}: {e.read().decode('utf-8', 'replace')}"
            ) from e
        return body["choices"][0]["message"]["content"]


class OpenAICompatClient:
    """LLM client for any OpenAI-compatible API endpoint.

    Reads configuration from FPT26_LLM_* environment variables, falling back
    to OpenRouter defaults.  Implements the same ``complete(system, user) -> str``
    protocol so it is a drop-in replacement for OpenRouterClient.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> None:
        resolved_base = (
            base_url
            or os.environ.get("FPT26_LLM_BASE_URL")
            or config.OPENROUTER_BASE_URL
        ).rstrip("/")
        self.base_url = f"{resolved_base}/chat/completions"
        self.api_key = (
            api_key
            or os.environ.get("FPT26_LLM_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or ""
        )
        self.model = (
            model
            or os.environ.get("FPT26_LLM_MODEL")
            or config.DEFAULT_LLM_MODEL
        )
        self.temperature = temperature
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        data = json.dumps(payload).encode("utf-8")
        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(
            self.base_url,
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"LLM HTTP {e.code}: {e.read().decode('utf-8', 'replace')}"
            ) from e
        return body["choices"][0]["message"]["content"]


def create_llm(backend: str = "auto") -> "LLMClient":
    """Factory: returns the right LLM client based on environment or explicit choice.

    * ``"openrouter"`` — always use OpenRouter.
    * ``"custom"``    — always use the OpenAI-compatible custom endpoint.
    * ``"scripted"``  — offline scripted client (canned responses).
    * ``"auto"``      — detect: if FPT26_LLM_BASE_URL is set use custom,
                        elif OPENROUTER_API_KEY is set use OpenRouter,
                        else raise.
    """
    if backend == "scripted":
        return ScriptedClient([])

    if backend == "custom":
        return OpenAICompatClient()

    if backend == "openrouter":
        return OpenRouterClient()

    # auto-detect
    if os.environ.get("FPT26_LLM_BASE_URL"):
        return OpenAICompatClient()
    if os.environ.get("OPENROUTER_API_KEY") or config.OPENROUTER_API_KEY:
        return OpenRouterClient()

    raise RuntimeError(
        "No LLM backend configured. Set FPT26_LLM_BASE_URL for a custom "
        "OpenAI-compatible endpoint, or OPENROUTER_API_KEY for OpenRouter."
    )
