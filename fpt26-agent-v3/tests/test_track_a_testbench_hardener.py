"""Regression tests for generated Track-A transcript oracles."""

import re

from harden_track_a_testbench_transcripts import (
    _add_observation_footer,
    _wrap_with_golden_checks,
)


def test_observation_and_golden_footer_precede_terminal_ternary_return() -> None:
    source = """
int main() {
    int output[2] = {1, 2};
    bool pass = output[0] == 1;
    return pass ? 0 : 1;
}
"""

    observed, arrays = _add_observation_footer(source)
    wrapped = _wrap_with_golden_checks(observed, [], namespace="hidden")

    assert arrays == ["output"]
    assert "int track_a_pre_observation_status = (pass ? 0 : 1);" in wrapped
    assert (
        "int track_a_pre_golden_status = (track_a_pre_observation_status);"
        in wrapped
    )
    assert not re.search(r"\breturn\s+[^;]+;\s*std::f(?:flush|printf)", wrapped, re.S)
    assert "track_a_pre_golden_status != 0 || track_a_mismatch != 0" in wrapped


def test_inner_early_return_is_not_rewritten() -> None:
    source = """
int main() {
    int output[1] = {0};
    if (output[0] != 0) return 7;
    return 0;
}
"""

    observed, _ = _add_observation_footer(source)

    assert "if (output[0] != 0) return 7;" in observed
    assert "int track_a_pre_observation_status = (0);" in observed
