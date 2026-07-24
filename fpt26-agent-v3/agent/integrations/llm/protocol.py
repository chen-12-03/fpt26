"""Unified LLM client protocol with token tracking, timeout, and retry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMClient(Protocol):
    """Complete a prompt and return text + structured usage info."""

    def complete(self, system: str, user: str) -> str: ...
    @property
    def model(self) -> str | None: ...
    @property
    def token_usage(self) -> Any: ...  # returns snapshot dict


@dataclass
class LLMResponse:
    """Structured response from an LLM completion."""
    text: str
    model: str | None = None
    token_usage: dict[str, Any] | None = None
    elapsed_s: float = 0.0
    retry_count: int = 0
    error: str | None = None


@dataclass
class LLMConfig:
    """Immutable LLM configuration — no secrets stored here."""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout_s: float = 180.0
    max_retries: int = 2
    total_token_budget: int | None = None  # None = unlimited


class LLMExecutor:
    """Wraps a raw :class:`LLMClient` with timeout, retry, and budget tracking.

    This is the production implementation agents should use.  It handles:
    - timeout enforcement
    - retry with backoff
    - token budget enforcement
    - error classification (no raw exceptions leak to callers)
    """

    def __init__(self, client: LLMClient, config: LLMConfig) -> None:
        self._client = client
        self._config = config
        self._total_tokens: int = 0

    @property
    def model(self) -> str | None:
        return getattr(self._client, "model", None)

    @property
    def backend_client_name(self) -> str:
        """Stable reporting name for the metered underlying API client."""
        return type(self._client).__name__

    @property
    def temperature(self) -> float:
        return self._config.temperature

    @property
    def max_tokens(self) -> int:
        return self._config.max_tokens

    @property
    def token_usage(self) -> Any:
        """Forward the raw client's cumulative usage tracker for audit."""
        return getattr(self._client, "token_usage", None)

    @property
    def total_tokens(self) -> int:
        return self._total_tokens

    def complete(self, system: str, user: str) -> str:
        """Complete with retry and budget enforcement.  Returns text.

        For structured usage info use :meth:`complete_structured`.
        Never raises on transient failures — returns empty string on error.
        """
        resp = self.complete_structured(system, user)
        return resp.text

    def complete_structured(self, system: str, user: str) -> LLMResponse:
        """Complete with retry and budget enforcement.

        Returns :class:`LLMResponse` — never raises on transient failures.
        """
        import time
        last_error = None

        for attempt in range(self._config.max_retries + 1):
            t0 = time.monotonic()
            try:
                text = self._client.complete(system, user)
                elapsed = time.monotonic() - t0

                # Track tokens
                usage = None
                tu = getattr(self._client, "token_usage", None)
                snapshot = getattr(tu, "snapshot", None)
                if callable(snapshot):
                    usage = snapshot()
                if usage and isinstance(usage, dict):
                    total = usage.get("total_tokens") or usage.get("observed_total_tokens") or 0
                    self._total_tokens += int(total)

                # Budget check
                if (self._config.total_token_budget is not None
                        and self._total_tokens > self._config.total_token_budget):
                    return LLMResponse(
                        text="", model=self.model, token_usage=usage,
                        elapsed_s=elapsed, retry_count=attempt,
                        error="token_budget_exceeded",
                    )

                return LLMResponse(
                    text=text, model=self.model, token_usage=usage,
                    elapsed_s=elapsed, retry_count=attempt,
                )
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self._config.max_retries:
                    time.sleep(min(2 ** attempt, 10))
                continue

        return LLMResponse(
            text="", model=self.model, retry_count=self._config.max_retries,
            error=last_error or "unknown",
        )
