from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from llm4hls import config as official_harness_config

from agent.llm import LLMClient, LLMConfig, LLMConfigError, TokenTracker, prompt_sha256


SCHEMA = {
    "type": "object",
    "required": ["task_id", "ok"],
    "additionalProperties": False,
    "properties": {
        "task_id": {"type": "string"},
        "ok": {"type": "boolean"},
    },
}


BASE_ENV = {
    "FPT26_LLM_BASE_URL": "http://127.0.0.1:1/v1",
    "FPT26_LLM_MODEL": "qwen2.5-coder-7b-instruct",
    "FPT26_LLM_MODEL_VERSION": "2025-01-local",
    "FPT26_LLM_API_KEY": "secret-token",
    "FPT26_LLM_TIMEOUT_SECONDS": "2.0",
    "FPT26_LLM_MAX_OUTPUT_TOKENS": "64",
    "FPT26_LLM_TEMPERATURE": "0",
    "FPT26_LLM_LICENSE": "Apache-2.0",
    "FPT26_LLM_SOURCE": "local-test-server",
}


class FakeLLMHandler(BaseHTTPRequestHandler):
    responses: list[dict] = []
    requests: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        self.__class__.requests.append(
            {
                "path": self.path,
                "headers": {key: value for key, value in self.headers.items()},
                "body": json.loads(body),
            }
        )
        spec = self.__class__.responses.pop(0)
        delay = spec.get("delay", 0)
        if delay:
            time.sleep(delay)
        status = spec.get("status", 200)
        payload = spec.get("payload", {})
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(raw.encode("utf-8"))
        except BrokenPipeError:
            pass

    def log_message(self, fmt, *args):
        return


class FakeLLMServer:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self):
        FakeLLMHandler.responses = list(self.responses)
        FakeLLMHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeLLMHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        assert self.server is not None
        self.server.shutdown()
        self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)

    @property
    def base_url(self) -> str:
        assert self.server is not None
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1"

    @property
    def requests(self) -> list[dict]:
        return FakeLLMHandler.requests


def chat_payload(content: str, usage: dict | None = None) -> dict:
    payload = {"choices": [{"message": {"content": content}}]}
    if usage is not None:
        payload["usage"] = usage
    return payload


def config(base_url: str, **overrides) -> LLMConfig:
    data = {
        "base_url": base_url,
        "model": "qwen2.5-coder-7b-instruct",
        "api_key": "secret-token",
        "timeout_seconds": 2.0,
        "max_output_tokens": 64,
        "temperature": 0.0,
        "license": "Apache-2.0",
        "source": "local-test-server",
        "model_version": "2025-01-local",
        "max_retries": 1,
        "max_call_total_tokens": None,
        "max_total_tokens": None,
    }
    data.update(overrides)
    return LLMConfig(**data)


def messages() -> list[dict[str, str]]:
    return [{"role": "user", "content": "return JSON"}]


class LLMConfigTests(unittest.TestCase):
    def test_from_env_defaults_to_official_openrouter_config(self):
        loaded = LLMConfig.from_env({"OPENROUTER_API_KEY": "official-token"})

        self.assertEqual(loaded.chat_completions_url, official_harness_config.OPENROUTER_BASE_URL)
        self.assertEqual(loaded.model, official_harness_config.DEFAULT_LLM_MODEL)
        self.assertEqual(loaded.api_key, "official-token")
        self.assertEqual(loaded.timeout_seconds, 180.0)
        self.assertEqual(loaded.max_output_tokens, 4096)
        self.assertEqual(loaded.temperature, 0.7)
        self.assertEqual(loaded.max_retries, 0)
        self.assertEqual(loaded.source, "OpenRouter")

    def test_official_openrouter_default_requires_token(self):
        with self.assertRaises(LLMConfigError) as ctx:
            LLMConfig.from_env({})

        self.assertIn("OPENROUTER_API_KEY", str(ctx.exception))

    def test_from_env_reads_metadata_and_does_not_require_api_key(self):
        env = dict(BASE_ENV)
        env["FPT26_LLM_API_KEY"] = ""
        loaded = LLMConfig.from_env(env)

        self.assertEqual(loaded.chat_completions_url, "http://127.0.0.1:1/v1/chat/completions")
        self.assertEqual(loaded.model, "qwen2.5-coder-7b-instruct")
        self.assertEqual(loaded.api_key, None)
        self.assertEqual(loaded.license, "Apache-2.0")
        self.assertEqual(loaded.source, "local-test-server")
        self.assertEqual(loaded.model_version, "2025-01-local")

    def test_invalid_open_source_metadata_fails_without_api_key_leak(self):
        env = dict(BASE_ENV)
        env["FPT26_LLM_MAX_RETRIES"] = "bad"
        with self.assertRaises(LLMConfigError) as ctx:
            LLMConfig.from_env(env)
        self.assertIn("FPT26_LLM_MAX_RETRIES", str(ctx.exception))
        self.assertNotIn("secret-token", str(ctx.exception))


class LLMClientFakeServerTests(unittest.TestCase):
    def test_prompt_hash_is_stable(self):
        first = prompt_sha256(messages())
        second = prompt_sha256([{"content": "return JSON", "role": "user"}])
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_structured_response_usage_and_request_payload(self):
        with FakeLLMServer(
            [
                {
                    "payload": chat_payload(
                        '{"task_id":"vector_add","ok":true}',
                        usage={"prompt_tokens": 10, "completion_tokens": 7, "total_tokens": 17},
                    )
                }
            ]
        ) as server:
            tracker = TokenTracker()
            response = LLMClient(config=config(server.base_url), token_tracker=tracker).generate(
                messages(),
                response_schema=SCHEMA,
                purpose="spec_extract",
            )

        request = server.requests[0]
        self.assertEqual(request["path"], "/v1/chat/completions")
        self.assertEqual(request["headers"]["Authorization"], "Bearer secret-token")
        self.assertEqual(request["body"]["model"], "qwen2.5-coder-7b-instruct")
        self.assertEqual(request["body"]["temperature"], 0.0)
        self.assertIn("response_format", request["body"])
        self.assertEqual(response.status, "ok")
        self.assertEqual(response.parsed, {"task_id": "vector_add", "ok": True})
        self.assertEqual(response.input_tokens, 10)
        self.assertEqual(response.output_tokens, 7)
        self.assertEqual(response.total_tokens, 17)
        self.assertEqual(response.usage_source, "api")
        self.assertEqual(tracker.summary()["total_tokens"], 17)
        self.assertNotIn("secret-token", json.dumps(response.to_dict()))

    def test_code_fence_json_is_extracted(self):
        with FakeLLMServer([{"payload": chat_payload('```json\n{"task_id":"vadd","ok":true}\n```')}]) as server:
            response = LLMClient(config=config(server.base_url)).generate(messages(), response_schema=SCHEMA)

        self.assertEqual(response.status, "ok")
        self.assertEqual(response.parsed["task_id"], "vadd")

    def test_malformed_json_and_schema_failure_do_not_retry(self):
        with FakeLLMServer([{"payload": chat_payload("not json")}]) as server:
            malformed = LLMClient(config=config(server.base_url, max_retries=3)).generate(
                messages(),
                response_schema=SCHEMA,
            )
        with FakeLLMServer([{"payload": chat_payload('{"task_id":"vadd"}')}]) as server2:
            schema_failure = LLMClient(config=config(server2.base_url, max_retries=3)).generate(
                messages(),
                response_schema=SCHEMA,
            )

        self.assertEqual(malformed.status, "error")
        self.assertEqual(malformed.error_type, "LLMResponseError")
        self.assertEqual(malformed.attempt_count, 1)
        self.assertEqual(schema_failure.status, "error")
        self.assertIn("schema validation failed", schema_failure.error_message)
        self.assertEqual(schema_failure.attempt_count, 1)

    def test_multiple_json_objects_fail(self):
        content = 'first {"task_id":"a","ok":true} second {"task_id":"b","ok":true}'
        with FakeLLMServer([{"payload": chat_payload(content)}]) as server:
            response = LLMClient(config=config(server.base_url)).generate(messages(), response_schema=SCHEMA)

        self.assertEqual(response.status, "error")
        self.assertIn("multiple JSON", response.error_message)
        self.assertEqual(response.attempt_count, 1)

    def test_timeout_429_and_500_are_retryable(self):
        success = chat_payload('{"task_id":"ok","ok":true}', usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
        with FakeLLMServer([{"delay": 0.2, "payload": success}, {"payload": success}]) as server:
            timeout_response = LLMClient(config=config(server.base_url, timeout_seconds=0.05, max_retries=1)).generate(
                messages(),
                response_schema=SCHEMA,
            )
        with FakeLLMServer([{"status": 429, "payload": {"error": "slow down"}}, {"payload": success}]) as server2:
            rate_limit_response = LLMClient(config=config(server2.base_url, max_retries=1)).generate(
                messages(),
                response_schema=SCHEMA,
            )
        with FakeLLMServer([{"status": 500, "payload": {"error": "boom"}}, {"payload": success}]) as server3:
            server_error_response = LLMClient(config=config(server3.base_url, max_retries=1)).generate(
                messages(),
                response_schema=SCHEMA,
            )

        self.assertEqual(timeout_response.status, "ok")
        self.assertEqual(timeout_response.attempt_count, 2)
        self.assertEqual(rate_limit_response.status, "ok")
        self.assertEqual(rate_limit_response.attempt_count, 2)
        self.assertEqual(server_error_response.status, "ok")
        self.assertEqual(server_error_response.attempt_count, 2)

    def test_non_retryable_4xx_stops_after_one_attempt(self):
        with FakeLLMServer([{"status": 400, "payload": {"error": "bad request"}}]) as server:
            response = LLMClient(config=config(server.base_url, max_retries=3)).generate(messages(), response_schema=SCHEMA)

        self.assertEqual(response.status, "error")
        self.assertEqual(response.error_type, "LLMHTTPError")
        self.assertEqual(response.attempt_count, 1)
        self.assertEqual(len(server.requests), 1)

    def test_usage_missing_remains_null(self):
        with FakeLLMServer([{"payload": chat_payload('{"task_id":"vadd","ok":true}')}]) as server:
            response = LLMClient(config=config(server.base_url)).generate(messages(), response_schema=SCHEMA)

        self.assertEqual(response.status, "ok")
        self.assertIsNone(response.input_tokens)
        self.assertIsNone(response.output_tokens)
        self.assertIsNone(response.total_tokens)
        self.assertEqual(response.usage_source, "missing")

    def test_single_and_cumulative_token_limits_block_before_request(self):
        with FakeLLMServer([{"payload": chat_payload('{"task_id":"vadd","ok":true}')}]) as server:
            blocked = LLMClient(config=config(server.base_url, max_output_tokens=64, max_call_total_tokens=32)).generate(
                messages(),
                response_schema=SCHEMA,
            )
            blocked_request_count = len(server.requests)
        success = chat_payload('{"task_id":"vadd","ok":true}', usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 10})
        with FakeLLMServer([{"payload": success}]) as server2:
            tracker = TokenTracker(max_total_tokens=15)
            client = LLMClient(config=config(server2.base_url, max_output_tokens=10), token_tracker=tracker)
            first = client.generate(messages(), response_schema=SCHEMA)
            second = client.generate(messages(), response_schema=SCHEMA)

        self.assertEqual(blocked.status, "error")
        self.assertEqual(blocked.attempt_count, 0)
        self.assertEqual(blocked_request_count, 0)
        self.assertEqual(first.status, "ok")
        self.assertEqual(second.status, "error")
        self.assertEqual(second.attempt_count, 0)
        self.assertEqual(len(server2.requests), 1)

    def test_jsonl_and_summary_persistence_are_stable_and_secret_free(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            persist_dir = Path(tmp_name) / "llm"
            with FakeLLMServer(
                [
                    {
                        "payload": chat_payload(
                            '{"task_id":"vadd","ok":true}',
                            usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
                        )
                    }
                ]
            ) as server:
                tracker = TokenTracker(persist_dir=persist_dir)
                response = LLMClient(config=config(server.base_url), token_tracker=tracker).generate(
                    messages(),
                    response_schema=SCHEMA,
                    purpose="spec_extract",
                )

            calls_text = (persist_dir / "calls.jsonl").read_text(encoding="utf-8")
            summary = json.loads((persist_dir / "token_summary.json").read_text(encoding="utf-8"))

        self.assertEqual(response.status, "ok")
        self.assertEqual(len(calls_text.strip().splitlines()), 1)
        self.assertEqual(summary["total_tokens"], 7)
        self.assertEqual(summary["by_purpose"]["spec_extract"]["total_tokens"], 7)
        self.assertNotIn("secret-token", calls_text)
        self.assertNotIn("secret-token", json.dumps(summary))


@unittest.skipUnless(os.environ.get("FPT26_RUN_LLM_TESTS") == "1", "set FPT26_RUN_LLM_TESTS=1 to run real LLM API tests")
class RealLLMOptInTests(unittest.TestCase):
    def test_real_endpoint_smoke(self):
        response = LLMClient().generate(
            messages(),
            response_schema=SCHEMA,
            purpose="real_llm_smoke",
        )
        self.assertEqual(response.status, "ok")


if __name__ == "__main__":
    unittest.main()
