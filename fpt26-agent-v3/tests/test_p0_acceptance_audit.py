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


def test_observation_notes_explain_outcomes_without_calling_them_errors() -> None:
    from scoring.audit_p0_acceptance import _observation_notes

    submission = {
        "toolchain": {"observed_parts": []},
    }
    evaluator = {
        "execution_trace": {
            "grading_results": [
                {"stage": "hidden_csim", "ok": False},
                {"stage": "candidate_synth", "ok": False},
            ]
        }
    }

    notes = _observation_notes(submission, evaluator)

    assert notes == [
        "toolchain_part_unverified",
        "hidden_csim_failed",
        "candidate_synth_failed",
    ]


def test_observation_notes_are_empty_for_a_clean_task() -> None:
    from scoring.audit_p0_acceptance import _observation_notes

    submission = {"toolchain": {"observed_parts": ["xcu55c-fsvh2892-2L-e"]}}
    evaluator = {
        "execution_trace": {
            "grading_results": [
                {"stage": "hidden_csim", "ok": True},
                {"stage": "candidate_synth", "ok": True},
            ]
        }
    }

    assert _observation_notes(submission, evaluator) == []
