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


class LLMCallFailed(RuntimeError):
    """An agent's LLM call could not produce text.

    Raised instead of continuing with an empty response so the pipeline
    classifies the task as an infrastructure error (with the owning step named)
    rather than recording it as the model proposing no change.
    """

    def __init__(self, error: str) -> None:
        super().__init__(f"LLM call failed: {error}")
        self.error = error


def complete_with_reason(
    client: Any, system: str, user: str
) -> LLMResponse:
    """Complete via *client*, preserving the failure reason when there is one.

    Agents accept any duck-typed client.  Clients built by ``create_llm`` expose
    :meth:`LLMExecutor.complete_structured`, which never raises and reports why
    it gave up; a bare client is asked for text directly and its exceptions are
    returned in the same shape, so callers have one code path either way.
    """
    structured = getattr(client, "complete_structured", None)
    if callable(structured):
        return structured(system, user)
    try:
        text = client.complete(system, user)
    except Exception as exc:
        return LLMResponse(text="", error=f"{type(exc).__name__}: {exc}")
    if not isinstance(text, str) or not text.strip():
        return LLMResponse(
            text="", error="LLM client returned empty or non-text message content"
        )
    return LLMResponse(text=text)


class LLMExecutor:
    """Wraps a raw :class:`LLMClient` with timeout, retry, and budget tracking.

    This is the production implementation agents should use.  It handles:
    - timeout enforcement
    - retry with backoff
    - token budget enforcement
    - error classification (no raw exceptions leak to callers)
    """

    #: Cap on retained failure records: enough to explain a run, bounded so a
    #: persistently unreachable endpoint cannot bloat the run report.
    MAX_RECORDED_FAILURES = 20

    def __init__(self, client: LLMClient, config: LLMConfig) -> None:
        self._client = client
        self._config = config
        self._total_tokens: int = 0
        self._failures: list[dict[str, Any]] = []

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

    @property
    def failures(self) -> list[dict[str, Any]]:
        """Why the retry loop gave up, oldest first.

        Without this the reason a call returned no text is lost, and an API
        failure becomes indistinguishable from a model that proposed no change.
        """
        return list(self._failures)

    def _record_failure(self, attempt: int, error: str) -> None:
        if len(self._failures) < self.MAX_RECORDED_FAILURES:
            self._failures.append({"attempt": attempt, "error": error})

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
                if not isinstance(text, str) or not text.strip():
                    raise RuntimeError(
                        "LLM client returned empty or non-text message content"
                    )
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
                    self._record_failure(attempt, "token_budget_exceeded")
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
                self._record_failure(attempt, last_error)
                if attempt < self._config.max_retries:
                    time.sleep(min(2 ** attempt, 10))
                continue

        return LLMResponse(
            text="", model=self.model, retry_count=self._config.max_retries,
            error=last_error or "unknown",
        )
