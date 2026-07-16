from agent.prompts import (
    OPTIMIZE_SYSTEM,
    REPAIR_SYSTEM,
    STRUCTURAL_REPAIR_SYSTEM,
)


def test_role_system_prompts_have_distinct_responsibilities() -> None:
    assert len({REPAIR_SYSTEM, STRUCTURAL_REPAIR_SYSTEM, OPTIMIZE_SYSTEM}) == 3

    assert "C-simulation failed" in REPAIR_SYSTEM
    assert "Do NOT add, remove, or tune HLS pragmas" in REPAIR_SYSTEM
    assert "ARRAY_PARTITION" not in REPAIR_SYSTEM

    assert "RTL co-simulation deadlocked" in STRUCTURAL_REPAIR_SYSTEM
    assert "unbounded" in STRUCTURAL_REPAIR_SYSTEM
    assert "interleave writes" in STRUCTURAL_REPAIR_SYSTEM
    assert "preserve those depth pragmas exactly" in STRUCTURAL_REPAIR_SYSTEM
    assert "Do NOT increase FIFO depth" in STRUCTURAL_REPAIR_SYSTEM
    assert "Q_HW" not in STRUCTURAL_REPAIR_SYSTEM
    assert "UNROLL" not in STRUCTURAL_REPAIR_SYSTEM

    assert "scoring_v3 Q_HW" in OPTIMIZE_SYSTEM
    assert "ARRAY_PARTITION" in OPTIMIZE_SYSTEM


def test_all_role_prompts_preserve_output_contract() -> None:
    for prompt in (REPAIR_SYSTEM, STRUCTURAL_REPAIR_SYSTEM, OPTIMIZE_SYSTEM):
        assert "Output ONLY the full kernel source" in prompt
        assert "Do NOT modify the top function signature" in prompt
