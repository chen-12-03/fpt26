from pathlib import Path

from scoring.audit_p0_acceptance import (
    _add_tokens,
    _json,
    _path,
    _record_can_be_replaced,
)


def test_token_aggregation_uses_only_integer_evidence() -> None:
    totals = {
        "request_count": 0,
        "response_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "failed_request_count": 0,
        "unreported_response_count": 0,
    }

    _add_tokens(
        totals,
        {
            "request_count": 2,
            "response_count": 2,
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "failed_request_count": 0,
            "unreported_response_count": 0,
        },
    )

    assert totals["request_count"] == 2
    assert totals["total_tokens"] == 120


def test_missing_json_is_explicit_none(tmp_path) -> None:
    assert _path(None) is None
    assert _json(tmp_path / "missing.json") is None
    assert _path(str(Path("/workspace/result.json"))) == Path(
        "/workspace/result.json"
    )


def test_only_failed_evidence_records_can_be_replaced() -> None:
    assert _record_can_be_replaced({"outcome": "infrastructure_error"})
    assert _record_can_be_replaced(
        {"outcome": "completed", "audit_errors": ["real_api_usage_incomplete"]}
    )
    assert not _record_can_be_replaced(
        {"outcome": "completed", "audit_errors": []}
    )
