from types import SimpleNamespace

from agent.agents.optimize import OptimizeAgent
from agent.agents.optimization.strategies import (
    _candidate_fingerprint,
    _top_function_inline_noop,
)


def test_candidate_fingerprint_ignores_optional_single_for_body_braces() -> None:
    unbraced = """
for (int i = 0; i < n; ++i)
    out[i] = in[i] + 1;
"""
    braced = """
for (int i = 0; i < n; ++i) {
    out[i] = in[i] + 1;
}
"""
    materially_different = braced.replace(
        "out[i] = in[i] + 1;",
        "out[i] = in[i] + 1;\n    sum += out[i];",
    )

    assert _candidate_fingerprint(unbraced) == _candidate_fingerprint(braced)
    assert (
        _candidate_fingerprint(unbraced)
        != _candidate_fingerprint(materially_different)
    )


def test_top_function_inline_only_edit_is_deterministic_noop() -> None:
    best = '#include "top.h"\nvoid top(int *out) { *out = 1; }\n'
    candidate = best.replace(
        "{ *out", "{\n#pragma HLS INLINE\n *out"
    )
    helper_inline = (
        '#include "top.h"\n'
        'static void helper(int *out) {\n#pragma HLS INLINE\n*out = 1;\n}\n'
        'void top(int *out) { helper(out); }\n'
    )

    assert _top_function_inline_noop(best, candidate, "top") is True
    assert _top_function_inline_noop(best, helper_inline, "top") is False


def test_top_function_inline_noop_skips_candidate_tools_and_converges() -> None:
    best = '#include "top.h"\nvoid top(int *out) { *out = 1; }\n'
    candidate = best.replace(
        "{ *out", "{\n#pragma HLS INLINE\n *out"
    )
    report = SimpleNamespace(
        latency_worst=10,
        latency_avg=10,
        interval_max=10,
        clock_period_ns=5.0,
        resources={
            "LUT": 10,
            "FF": 10,
            "DSP": 0,
            "BRAM_18K": 0,
            "URAM": 0,
        },
        available={
            "LUT": 1000,
            "FF": 1000,
            "DSP": 1000,
            "BRAM_18K": 1000,
            "URAM": 1000,
        },
        loop_metrics=[],
        pipeline_type="none",
    )

    class Llm:
        calls = 0

        def complete(self, system, prompt):
            self.calls += 1
            return candidate

    class Server:
        def csim(self, kernel):
            raise AssertionError("top INLINE no-op must skip candidate CSim")

        def synth(self, kernel):
            raise AssertionError("top INLINE no-op must skip candidate Synth")

    task = SimpleNamespace(
        id="top_inline",
        type="optimize",
        difficulty=1,
        requires_cosim=False,
        budget=40,
        clock_ns=5.0,
        description="",
        headers={"top.h": "void top(int *out);"},
        top="top",
        kernel_name="top.cpp",
    )
    state = SimpleNamespace(
        task=task,
        server=Server(),
        kernel=best,
        best_latency=10,
        results=[
            SimpleNamespace(
                kind="synth",
                ok=True,
                phase="pass",
                report=report,
                log="",
            )
        ],
        metadata={},
        log=lambda message: None,
    )
    llm = Llm()

    result = OptimizeAgent(llm, max_rounds=3).run(state)

    assert result.kernel == best
    assert llm.calls == 1
    assert result.metadata["semantic_current_best_skips"] == 1
