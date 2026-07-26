from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.validation import (
    CandidateValidator,
    extract_code,
    frequency_gate,
    resource_gate,
    validate_candidate,
)
from llm4hls.task import Task


_STARTER = """\
#include "kernel.h"
static int helper(int x) { return x; }
void kernel(const int input[4], int *output, int &status) {
    output[0] = helper(input[0]);
    status = 1;
}
"""


def _task() -> Task:
    return Task(
        dir=None,
        id="validator",
        type="repair",
        difficulty=1,
        top="kernel",
        budget=20,
        part="xcu55c-fsvh2892-2L-e",
        clock_ns=5.0,
        requires_cosim=False,
        initial_condition="",
        description="",
        kernel_name="kernel.cpp",
        kernel_code=_STARTER,
        headers={"kernel.h": "void kernel(const int input[4], int *output, int &status);\n"},
        public_tb_name="kernel_tb.cpp",
        public_tb_code="int main() { return 0; }\n",
    )


def test_candidate_body_change_preserves_interface() -> None:
    validator = CandidateValidator.from_task(_task())
    result = validator.validate(_STARTER.replace("status = 1", "status = 2"))
    assert result.ok
    assert result.fingerprint == validator.contract.fingerprint


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("void kernel", "int kernel"),
        ("const int input[4]", "const int input[8]"),
        ("int *output, int &status", "int &status, int *output"),
        ("int *output", "long *output"),
        ("int &status", "int status"),
        ("void kernel", "void changed"),
    ],
)
def test_candidate_interface_changes_fail(old: str, new: str) -> None:
    validator = CandidateValidator.from_task(_task())
    result = validator.validate(_STARTER.replace(old, new))
    assert not result.ok
    assert result.reason in {"top_interface_changed", "top_function_missing"}


def test_candidate_required_include_removal_fails() -> None:
    result = CandidateValidator.from_task(_task()).validate(
        _STARTER.replace('#include "kernel.h"\n', "")
    )
    assert not result.ok
    assert result.reason == "required_include_removed"


def test_candidate_hidden_reference_embedding_fails() -> None:
    result = CandidateValidator.from_task(_task()).validate(
        _STARTER.replace("status = 1", 'status = 1; /* reference/kernel.cpp */')
    )
    assert not result.ok
    assert result.reason == "hidden_or_reference_embedding"


@pytest.mark.parametrize(
    "response",
    [
        f"```CPP\n{_STARTER}```",
        f"```cxx\r\n{_STARTER}```",
        f"```cpp {_STARTER}```",
        f"```cpp title=kernel.cpp\n{_STARTER}```",
        f"```cpp\n{_STARTER}",
    ],
)
def test_extract_code_accepts_common_markdown_fence_variants(response: str) -> None:
    code = extract_code(response)
    assert code is not None
    assert "```" not in code
    assert CandidateValidator.from_task(_task()).validate(code).ok


def test_interface_failure_records_bounded_source_diagnostics() -> None:
    state = SimpleNamespace(
        task=_task(),
        kernel=_STARTER,
        metadata={},
        log=lambda message: None,
    )
    candidate = f"```cpp\n{_STARTER}"

    assert not validate_candidate(
        state, candidate, stage="optimize_candidate_1", current_best=False
    )

    record = state.metadata["interface_validations"][-1]
    diagnostics = record["source_diagnostics"]
    assert record["reason"] == "markdown_fence_in_candidate"
    assert diagnostics["char_count"] == len(candidate)
    assert diagnostics["markdown_fence_count"] == 1
    assert diagnostics["first_markdown_fence_offset"] == 0
    assert diagnostics["starts_with_markdown_fence"] is True
    assert diagnostics["has_top_function_token"] is True
    assert "source_sha256" in diagnostics


@pytest.mark.parametrize("period", [9.99, 10.0])
def test_frequency_gate_accepts_at_least_100mhz(period: float) -> None:
    gate = frequency_gate(SimpleNamespace(clock_period_ns=period), 5.0)
    assert gate.ok
    assert gate.frequency_mhz >= 100.0


@pytest.mark.parametrize("period", [10.01, None, float("nan"), 0.0, -1.0])
def test_frequency_gate_fails_closed(period: float | None) -> None:
    gate = frequency_gate(SimpleNamespace(clock_period_ns=period), 5.0)
    assert not gate.ok


def test_resource_gate_requires_complete_capacity_and_rejects_overflow() -> None:
    resources = {"LUT": 11, "FF": 2, "DSP": 1, "BRAM_18K": 0, "URAM": 0}
    available = {"LUT": 10, "FF": 20, "DSP": 10, "BRAM_18K": 10, "URAM": 10}
    assert not resource_gate(
        SimpleNamespace(resources=resources, available=available)
    ).ok
    assert not resource_gate(
        SimpleNamespace(resources=resources, available={"LUT": 100})
    ).ok
