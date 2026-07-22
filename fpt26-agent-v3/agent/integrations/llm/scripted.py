"""Scripted (offline) LLM client — replays canned responses for testing."""

from __future__ import annotations

from agent.integrations.llm.protocol import LLMConfig


class ScriptedTokenUsage:
    """Fake token usage tracker for scripted clients."""
    def snapshot(self) -> dict:
        return {"request_count": 1, "total_tokens": 0, "complete": True}


class ScriptedLLM:
    """Deterministic offline backend: returns the next canned response.

    Use via ``LLMExecutor(ScriptedLLM(responses), config)`` for integration tests.
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._i = 0
        self.model = "scripted"
        self.token_usage = ScriptedTokenUsage()

    def complete(self, system: str, user: str) -> str:
        if not self._responses:
            return ""
        resp = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return resp


class FailingLLM:
    """Always raises the given exception — for testing error paths."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.model = "failing"
        self.token_usage = ScriptedTokenUsage()

    def complete(self, system: str, user: str) -> str:
        raise self._exc
