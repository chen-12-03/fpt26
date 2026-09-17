import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "tools"
    / "compare_track_a_v4_reproduction.py"
)
SPEC = importlib.util.spec_from_file_location("reproduction_comparison", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)


def _record(task_id: str, outcome: str, score: float, digest: str) -> dict:
    return {
        "task_id": task_id,
        "outcome": outcome,
        "submission": {
            "final_kernel_sha256": digest,
            "api": {
                "observed_total_tokens": 100,
                "observed_prompt_tokens": 80,
                "observed_completion_tokens": 20,
                "request_count": 1,
                "response_count": 1,
                "failed_request_count": 0,
            },
            "credits_spent": 1,
            "tool_calls": 2,
        },
        "evaluator": {"score": score},
    }


def test_task_comparison_uses_symmetric_relative_tolerance() -> None:
    paper = [_record("ta2_qo_001", "completed", 100.0, "same")]
    rerun = [_record("ta2_qo_001", "completed", 96.0, "same")]

    result = comparison.compare_tasks(paper, rerun, 0.05)

    assert result["score_within_tolerance_count"] == 1
    assert result["kernel_hash_match_count"] == 1
    assert result["rows"][0]["relative_score_difference"] == 0.04


def test_contract_normalization_expands_launcher_default() -> None:
    canonical = {"model": "m", "competition": False}
    observed = {"model": "m"}

    assert comparison.normalized_contract(canonical) == comparison.normalized_contract(
        observed
    )
