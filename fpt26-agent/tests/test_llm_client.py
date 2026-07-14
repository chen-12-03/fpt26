import json
import socket
import unittest
import urllib.error
from unittest import mock

from agent.llm_client import (
    LLMConfig,
    LLMConfigError,
    LLMHTTPError,
    LLMResponseError,
    LLMTimeoutError,
    call_chat_completion,
)


BASE_ENV = {
    "LLM_BASE_URL": "http://localhost:8000/v1",
    "LLM_MODEL": "open-source-model",
    "LLM_API_KEY": "secret-token",
    "LLM_TIMEOUT_SECONDS": "7.5",
    "LLM_MAX_OUTPUT_TOKENS": "256",
}


class FakeHTTPResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.body


def response_body(*, content: str = "{}", usage=None) -> str:
    data = {
        "choices": [
            {
                "message": {
                    "content": content,
                },
            }
        ],
    }
    if usage is not None:
        data["usage"] = usage
    return json.dumps(data)


class LLMClientTests(unittest.TestCase):
    def test_from_env_reads_required_configuration(self):
        config = LLMConfig.from_env(BASE_ENV)

        self.assertEqual(config.base_url, "http://localhost:8000/v1")
        self.assertEqual(config.chat_completions_url, "http://localhost:8000/v1/chat/completions")
        self.assertEqual(config.model, "open-source-model")
        self.assertEqual(config.api_key, "secret-token")
        self.assertEqual(config.timeout_seconds, 7.5)
        self.assertEqual(config.max_output_tokens, 256)

    def test_missing_required_env_fails_clearly(self):
        env = dict(BASE_ENV)
        del env["LLM_MODEL"]

        with self.assertRaises(LLMConfigError) as ctx:
            LLMConfig.from_env(env)

        self.assertIn("missing required environment variable: LLM_MODEL", str(ctx.exception))
        self.assertNotIn("secret-token", str(ctx.exception))

    def test_success_response_returns_text_usage_elapsed_and_prompt_hash(self):
        config = LLMConfig.from_env(BASE_ENV)
        body = response_body(
            content='{"task_id":"vector_add"}',
            usage={"prompt_tokens": 11, "completion_tokens": 13, "total_tokens": 24},
        )

        with mock.patch("agent.llm_client.urllib.request.urlopen") as urlopen:
            with mock.patch("agent.llm_client.time.perf_counter", side_effect=[10.0, 10.25]):
                urlopen.return_value = FakeHTTPResponse(body)
                result = call_chat_completion("extract a vector add IR", config=config)

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))

        self.assertEqual(urlopen.call_args.kwargs["timeout"], 7.5)
        self.assertEqual(request.full_url, "http://localhost:8000/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-token")
        self.assertEqual(payload["model"], "open-source-model")
        self.assertEqual(payload["max_tokens"], 256)
        self.assertEqual(payload["messages"], [{"role": "user", "content": "extract a vector add IR"}])
        self.assertEqual(result.model, "open-source-model")
        self.assertEqual(result.response_text, '{"task_id":"vector_add"}')
        self.assertEqual(result.input_tokens, 11)
        self.assertEqual(result.output_tokens, 13)
        self.assertEqual(result.total_tokens, 24)
        self.assertEqual(result.elapsed_seconds, 0.25)
        self.assertEqual(len(result.prompt_hash), 64)
        self.assertNotIn("secret-token", json.dumps(result.to_dict()))

    def test_missing_usage_leaves_token_fields_null(self):
        config = LLMConfig.from_env(BASE_ENV)

        with mock.patch("agent.llm_client.urllib.request.urlopen") as urlopen:
            urlopen.return_value = FakeHTTPResponse(response_body(content="ok"))
            result = call_chat_completion("hello", config=config)

        self.assertIsNone(result.input_tokens)
        self.assertIsNone(result.output_tokens)
        self.assertIsNone(result.total_tokens)

    def test_timeout_is_reported_without_api_key(self):
        config = LLMConfig.from_env(BASE_ENV)

        with mock.patch("agent.llm_client.urllib.request.urlopen", side_effect=socket.timeout()):
            with self.assertRaises(LLMTimeoutError) as ctx:
                call_chat_completion("hello", config=config)

        self.assertIn("timed out", str(ctx.exception))
        self.assertNotIn("secret-token", str(ctx.exception))

    def test_http_error_is_reported_without_api_key(self):
        config = LLMConfig.from_env(BASE_ENV)
        error = urllib.error.HTTPError(
            url=config.chat_completions_url,
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=None,
        )

        with mock.patch("agent.llm_client.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(LLMHTTPError) as ctx:
                call_chat_completion("hello", config=config)

        self.assertIn("HTTP 503", str(ctx.exception))
        self.assertNotIn("secret-token", str(ctx.exception))

    def test_invalid_json_response_fails_clearly(self):
        config = LLMConfig.from_env(BASE_ENV)

        with mock.patch("agent.llm_client.urllib.request.urlopen") as urlopen:
            urlopen.return_value = FakeHTTPResponse("not json")
            with self.assertRaises(LLMResponseError) as ctx:
                call_chat_completion("hello", config=config)

        self.assertIn("invalid JSON", str(ctx.exception))

    def test_missing_choices_response_fails_clearly(self):
        config = LLMConfig.from_env(BASE_ENV)

        with mock.patch("agent.llm_client.urllib.request.urlopen") as urlopen:
            urlopen.return_value = FakeHTTPResponse("{}")
            with self.assertRaises(LLMResponseError) as ctx:
                call_chat_completion("hello", config=config)

        self.assertIn("missing choices", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
