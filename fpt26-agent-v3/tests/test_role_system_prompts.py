import json
from types import SimpleNamespace

from agent.prompts import (
    OPTIMIZE_SYSTEM,
    REPAIR_SYSTEM,
    STRUCTURAL_REPAIR_SYSTEM,
    build_prompt,
)


def test_role_system_prompts_share_one_tool_result_driven_policy() -> None:
    assert REPAIR_SYSTEM == STRUCTURAL_REPAIR_SYSTEM == OPTIMIZE_SYSTEM
    assert "If csim FAILS" in OPTIMIZE_SYSTEM
    assert "cosim DEADLOCKS/TIMEOUT" in OPTIMIZE_SYSTEM
    assert "scoring_v3 Q_HW" in OPTIMIZE_SYSTEM
    assert "ARRAY_PARTITION" in OPTIMIZE_SYSTEM


def test_all_role_prompts_preserve_output_contract() -> None:
    for prompt in (REPAIR_SYSTEM, STRUCTURAL_REPAIR_SYSTEM, OPTIMIZE_SYSTEM):
        assert "Output ONLY the full kernel source" in prompt
        assert "Do NOT modify the top function signature" in prompt


def test_prompt_omits_non_code_task_attachments() -> None:
    task = SimpleNamespace(
        id="asset_filter",
        description="Optimize the kernel.",
        top="top",
        headers={
            "top.h": "void top(int *out);",
            "helpers.inc": "#define SCALE 2",
            "input.data": "SECRET_INPUT_PAYLOAD",
            "check.data": "SECRET_CHECK_PAYLOAD",
        },
        kernel_name="top.cpp",
        requires_cosim=False,
    )

    prompt = build_prompt(task, "void top(int *out) { *out = SCALE; }")
    payload = json.loads(prompt)

    assert "void top(int *out);" in payload["headers"]
    assert "#define SCALE 2" in payload["headers"]
    assert "SECRET_INPUT_PAYLOAD" not in prompt
    assert "SECRET_CHECK_PAYLOAD" not in prompt
    assert payload["omitted_non_code_attachments"] == [
        "check.data",
        "input.data",
    ]
