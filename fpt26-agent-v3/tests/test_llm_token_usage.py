from llm4hls.llm import (
    OpenAICompatClient,
    OpenRouterClient,
    TokenUsage,
    chat_completions_url,
    create_llm,
)

from agent.integrations.llm.protocol import LLMConfig, LLMExecutor
from agent.reporting.metrics import _llm_summary
import agent.backends as agent_backends


def test_token_usage_reports_exact_totals_when_all_responses_include_usage() -> None:
    usage = TokenUsage()
    usage.begin_request()
    usage.record_response(
        {"usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
    )
    usage.begin_request()
    usage.record_response(
        {"usage": {"prompt_tokens": 60, "completion_tokens": 15, "total_tokens": 75}}
    )

    assert usage.snapshot() == {
        "request_count": 2,
        "response_count": 2,
        "reported_usage_count": 2,
        "unreported_response_count": 0,
        "failed_request_count": 0,
        "prompt_tokens": 160,
        "completion_tokens": 35,
        "total_tokens": 195,
        "observed_prompt_tokens": 160,
        "observed_completion_tokens": 35,
        "observed_total_tokens": 195,
        "complete": True,
    }


def test_token_usage_does_not_present_partial_observations_as_exact() -> None:
    usage = TokenUsage()
    usage.begin_request()
    usage.record_response(
        {"usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
    )
    usage.begin_request()
    usage.record_response({"choices": []})

    snapshot = usage.snapshot()
    assert snapshot["prompt_tokens"] is None
    assert snapshot["completion_tokens"] is None
    assert snapshot["total_tokens"] is None
    assert snapshot["observed_total_tokens"] == 120
    assert snapshot["complete"] is False
    assert snapshot["unreported_response_count"] == 1


def test_llm_executor_forwards_backend_identity_config_and_exact_usage() -> None:
    class RawClient:
        model = "open-model"

        def __init__(self) -> None:
            self.token_usage = TokenUsage()

        def complete(self, system: str, user: str) -> str:
            self.token_usage.begin_request()
            self.token_usage.record_response(
                {
                    "usage": {
                        "prompt_tokens": 120,
                        "completion_tokens": 30,
                        "total_tokens": 150,
                    }
                }
            )
            return "response"

    raw = RawClient()
    executor = LLMExecutor(
        raw,
        LLMConfig(
            model="open-model",
            temperature=0.2,
            max_tokens=2048,
        ),
    )
    assert executor.complete("system", "user") == "response"
    state = type("State", (), {"llm": executor})()

    summary = _llm_summary(state)

    assert summary["client"] == "RawClient"
    assert summary["model"] == "open-model"
    assert summary["temperature"] == 0.2
    assert summary["max_tokens"] == 2048
    assert summary["token_usage"]["request_count"] == 1
    assert summary["token_usage"]["total_tokens"] == 150


def test_chat_completion_url_accepts_api_base_or_full_endpoint() -> None:
    assert (
        chat_completions_url("https://openrouter.ai/api/v1")
        == "https://openrouter.ai/api/v1/chat/completions"
    )
    assert (
        chat_completions_url("https://openrouter.ai/api/v1/chat/completions")
        == "https://openrouter.ai/api/v1/chat/completions"
    )
    assert (
        chat_completions_url(" https://dashscope.aliyuncs.com/compatible-mode/v1/ ")
        == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )


def test_openai_compat_client_normalizes_custom_full_endpoint() -> None:
    client = OpenAICompatClient(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        api_key="test-key",
        model="qwen3-coder-plus",
    )

    assert (
        client.base_url
        == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    assert client.model == "qwen3-coder-plus"


def test_openrouter_client_normalizes_configured_api_base(monkeypatch) -> None:
    from llm4hls import config

    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-router-key")
    monkeypatch.setattr(config, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    client = OpenRouterClient(model="qwen/qwen-2.5-coder-32b-instruct")

    assert client.base_url == "https://openrouter.ai/api/v1/chat/completions"


def test_create_llm_auto_prefers_custom_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("FPT26_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("FPT26_LLM_API_KEY", "test-key")
    monkeypatch.setenv("FPT26_LLM_MODEL", "qwen3-coder-plus")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-router-key")

    client = create_llm("auto")

    assert isinstance(client, OpenAICompatClient)
    assert (
        client.base_url
        == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    assert client.model == "qwen3-coder-plus"


def test_create_llm_openrouter_backend_uses_openrouter_client(monkeypatch) -> None:
    from llm4hls import config

    monkeypatch.delenv("FPT26_LLM_BASE_URL", raising=False)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-router-key")
    monkeypatch.setattr(config, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    client = create_llm("openrouter")

    assert isinstance(client, OpenRouterClient)
    assert client.base_url == "https://openrouter.ai/api/v1/chat/completions"


def test_agent_backend_applies_reported_request_parameters_to_raw_client(
    monkeypatch,
) -> None:
    class RawClient:
        model = "qwen/qwen3-coder"
        temperature = 0.7
        max_tokens = 4096

    raw = RawClient()
    monkeypatch.setattr(
        agent_backends, "_official_create_llm", lambda backend: raw
    )
    monkeypatch.setenv("FPT26_LLM_TEMPERATURE", "0.15")
    monkeypatch.setenv("FPT26_LLM_MAX_TOKENS", "6144")

    executor = agent_backends.create_llm("openrouter")

    assert raw.temperature == 0.15
    assert raw.max_tokens == 6144
    assert executor.temperature == raw.temperature
    assert executor.max_tokens == raw.max_tokens


def test_llm_executor_retries_null_message_content(monkeypatch) -> None:
    import time

    class RawClient:
        model = "deepseek/deepseek-v4-pro"

        def __init__(self) -> None:
            self.responses = [None, "valid response"]

        def complete(self, system: str, user: str):
            return self.responses.pop(0)

    monkeypatch.setattr(time, "sleep", lambda _: None)
    executor = LLMExecutor(
        RawClient(),
        LLMConfig(model="deepseek/deepseek-v4-pro", max_retries=1),
    )

    response = executor.complete_structured("system", "user")

    assert response.text == "valid response"
    assert response.retry_count == 1
    assert response.error is None


def test_llm_executor_returns_canonical_empty_string_after_null_content() -> None:
    class RawClient:
        model = "deepseek/deepseek-v4-pro"

        def complete(self, system: str, user: str):
            return None

    executor = LLMExecutor(
        RawClient(),
        LLMConfig(model="deepseek/deepseek-v4-pro", max_retries=0),
    )

    response = executor.complete_structured("system", "user")

    assert response.text == ""
    assert "empty or non-text" in str(response.error)
