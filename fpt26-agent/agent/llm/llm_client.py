from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any

from agent.llm.config import LLMConfig, LLMConfigError
from agent.llm.schemas import (
    LLMCallRecord,
    LLMResponse,
    LLMResponseError,
    parse_structured_json,
    prompt_sha256,
    validate_json_schema,
)
from agent.llm.token_tracker import TokenLimitError, TokenTracker


class LLMClientError(Exception):
    pass


class LLMTimeoutError(LLMClientError):
    pass


class LLMHTTPError(LLMClientError):
    pass


class LLMConnectionError(LLMClientError):
    pass


class LLMClient:
    def __init__(
        self,
        *,
        config: LLMConfig | None = None,
        token_tracker: TokenTracker | None = None,
    ) -> None:
        self.config = config or LLMConfig.from_env()
        self.token_tracker = token_tracker or TokenTracker(
            max_call_total_tokens=self.config.max_call_total_tokens,
            max_total_tokens=self.config.max_total_tokens,
        )

    def generate(
        self,
        messages: list[dict[str, Any]],
        response_schema: dict[str, Any] | None = None,
        purpose: str | None = None,
    ) -> LLMResponse:
        _validate_messages(messages)
        prompt_hash = prompt_sha256(messages)
        started = time.perf_counter()
        try:
            self.token_tracker.ensure_can_call(max_output_tokens=self.config.max_output_tokens)
        except TokenLimitError as exc:
            return self._error_response(
                purpose=purpose,
                prompt_hash=prompt_hash,
                attempt_records=[],
                attempt_count=0,
                started=started,
                error_type="TokenLimitError",
                error_message=str(exc),
            )

        payload = self._payload(messages, response_schema)
        attempt_records: list[LLMCallRecord] = []
        last_error_type: str | None = None
        last_error_message: str | None = None

        for attempt_index in range(1, self.config.max_retries + 2):
            request_started = time.perf_counter()
            try:
                data, http_status = self._post(payload)
                elapsed = time.perf_counter() - request_started
                content = _extract_response_text(data)
                usage = _extract_usage(data)
                parsed = None
                if response_schema is not None:
                    parsed = parse_structured_json(content)
                    validate_json_schema(parsed, response_schema)

                record = self._record(
                    purpose=purpose,
                    prompt_hash=prompt_hash,
                    attempt_index=attempt_index,
                    status="ok",
                    http_status=http_status,
                    usage=usage,
                    elapsed_seconds=elapsed,
                    error_type=None,
                    error_message=None,
                )
                attempt_records.append(record)
                self.token_tracker.record(record)
                return LLMResponse(
                    status="ok",
                    content=content,
                    parsed=parsed,
                    model=self.config.model,
                    model_version=self.config.model_version,
                    license=self.config.license,
                    source=self.config.source,
                    purpose=purpose,
                    prompt_sha256=prompt_hash,
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    total_tokens=usage["total_tokens"],
                    usage_source=usage["usage_source"],
                    elapsed_seconds=time.perf_counter() - started,
                    attempt_count=attempt_index,
                    error_type=None,
                    error_message=None,
                    attempts=attempt_records,
                )
            except LLMResponseError as exc:
                elapsed = time.perf_counter() - request_started
                record = self._record_error(
                    purpose,
                    prompt_hash,
                    attempt_index,
                    "LLMResponseError",
                    str(exc),
                    elapsed,
                    http_status=None,
                )
                attempt_records.append(record)
                self.token_tracker.record(record)
                last_error_type = "LLMResponseError"
                last_error_message = str(exc)
                break
            except LLMHTTPError as exc:
                elapsed = time.perf_counter() - request_started
                http_status = getattr(exc, "http_status", None)
                retryable = http_status == 429 or (isinstance(http_status, int) and http_status >= 500)
                record = self._record_error(
                    purpose,
                    prompt_hash,
                    attempt_index,
                    "LLMHTTPError",
                    str(exc),
                    elapsed,
                    http_status=http_status,
                )
                attempt_records.append(record)
                self.token_tracker.record(record)
                last_error_type = "LLMHTTPError"
                last_error_message = str(exc)
                if not retryable or attempt_index > self.config.max_retries:
                    break
            except (LLMTimeoutError, LLMConnectionError) as exc:
                elapsed = time.perf_counter() - request_started
                record = self._record_error(
                    purpose,
                    prompt_hash,
                    attempt_index,
                    type(exc).__name__,
                    str(exc),
                    elapsed,
                    http_status=None,
                )
                attempt_records.append(record)
                self.token_tracker.record(record)
                last_error_type = type(exc).__name__
                last_error_message = str(exc)
                if attempt_index > self.config.max_retries:
                    break

        return self._error_response(
            purpose=purpose,
            prompt_hash=prompt_hash,
            attempt_records=attempt_records,
            attempt_count=len(attempt_records),
            started=started,
            error_type=last_error_type or "LLMClientError",
            error_message=last_error_message or "LLM call failed",
        )

    def _payload(self, messages: list[dict[str, Any]], response_schema: dict[str, Any] | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_output_tokens,
            "temperature": self.config.temperature,
        }
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "fpt26_response",
                    "schema": response_schema,
                    "strict": True,
                },
            }
        return payload

    def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        request = self._build_request(payload)
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
                status = getattr(response, "status", 200)
        except TimeoutError as exc:
            raise LLMTimeoutError(f"LLM request timed out after {self.config.timeout_seconds} seconds") from exc
        except socket.timeout as exc:
            raise LLMTimeoutError(f"LLM request timed out after {self.config.timeout_seconds} seconds") from exc
        except urllib.error.HTTPError as exc:
            raise _http_error(exc) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, socket.timeout):
                raise LLMTimeoutError(f"LLM request timed out after {self.config.timeout_seconds} seconds") from exc
            raise LLMConnectionError(f"LLM request failed: {reason}") from exc

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise LLMResponseError("LLM service returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise LLMResponseError("LLM service response must be a JSON object")
        return data, int(status)

    def _build_request(self, payload: dict[str, Any]) -> urllib.request.Request:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return urllib.request.Request(
            self.config.chat_completions_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    def _record(
        self,
        *,
        purpose: str | None,
        prompt_hash: str,
        attempt_index: int,
        status: str,
        http_status: int | None,
        usage: dict[str, int | str | None],
        elapsed_seconds: float | None,
        error_type: str | None,
        error_message: str | None,
    ) -> LLMCallRecord:
        return LLMCallRecord(
            purpose=purpose,
            model=self.config.model,
            model_version=self.config.model_version,
            license=self.config.license,
            source=self.config.source,
            prompt_sha256=prompt_hash,
            attempt_index=attempt_index,
            status=status,
            http_status=http_status,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            total_tokens=usage["total_tokens"],
            usage_source=str(usage["usage_source"]),
            elapsed_seconds=elapsed_seconds,
            error_type=error_type,
            error_message=error_message,
        )

    def _record_error(
        self,
        purpose: str | None,
        prompt_hash: str,
        attempt_index: int,
        error_type: str,
        error_message: str,
        elapsed_seconds: float | None,
        *,
        http_status: int | None,
    ) -> LLMCallRecord:
        return self._record(
            purpose=purpose,
            prompt_hash=prompt_hash,
            attempt_index=attempt_index,
            status="error",
            http_status=http_status,
            usage=_empty_usage(),
            elapsed_seconds=elapsed_seconds,
            error_type=error_type,
            error_message=error_message,
        )

    def _error_response(
        self,
        *,
        purpose: str | None,
        prompt_hash: str,
        attempt_records: list[LLMCallRecord],
        attempt_count: int,
        started: float,
        error_type: str,
        error_message: str,
    ) -> LLMResponse:
        return LLMResponse(
            status="error",
            content=None,
            parsed=None,
            model=self.config.model,
            model_version=self.config.model_version,
            license=self.config.license,
            source=self.config.source,
            purpose=purpose,
            prompt_sha256=prompt_hash,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            usage_source="missing",
            elapsed_seconds=time.perf_counter() - started,
            attempt_count=attempt_count,
            error_type=error_type,
            error_message=error_message,
            attempts=attempt_records,
        )


def _validate_messages(messages: list[dict[str, Any]]) -> None:
    if not isinstance(messages, list) or not messages:
        raise LLMConfigError("messages must be a non-empty list")
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise LLMConfigError(f"messages[{index}] must be an object")
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"}:
            raise LLMConfigError(f"messages[{index}].role is invalid")
        if not isinstance(content, str) or not content:
            raise LLMConfigError(f"messages[{index}].content must be a non-empty string")


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


def _extract_usage(data: dict[str, Any]) -> dict[str, int | str | None]:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return _empty_usage()
    return {
        "input_tokens": _optional_int(usage.get("prompt_tokens")),
        "output_tokens": _optional_int(usage.get("completion_tokens")),
        "total_tokens": _optional_int(usage.get("total_tokens")),
        "usage_source": "api",
    }


def _empty_usage() -> dict[str, int | str | None]:
    return {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "usage_source": "missing",
    }


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    return None


def _http_error(exc: urllib.error.HTTPError) -> LLMHTTPError:
    reason = getattr(exc, "reason", exc.msg)
    error = LLMHTTPError(f"LLM service returned HTTP {exc.code}: {reason}")
    setattr(error, "http_status", exc.code)
    return error
