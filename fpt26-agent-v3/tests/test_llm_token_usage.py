from llm4hls.llm import TokenUsage

from agent.integrations.llm.protocol import LLMConfig, LLMExecutor
from agent.reporting.metrics import _llm_summary


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
