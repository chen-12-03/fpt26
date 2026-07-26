from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from agent.agents.base import AgentConfig, RunState
from agent.agents.optimize import OptimizeAgent
from agent.agents.repair import RepairAgent
from agent.workflow import build_pipeline, step_finalize
import agent.main as agent_main
from llm4hls.budget import Budget
from llm4hls.task import Task
from llm4hls.tools import ToolResult


_AVAILABLE = {
    "LUT": 1_303_680,
    "FF": 2_607_360,
    "DSP": 9_024,
    "BRAM_18K": 4_032,
    "URAM": 960,
}
_STARTER = '#include "top.h"\nint top(int *a) { return a[0]; }\n'
_FIXED = '#include "top.h"\nint top(int *a) { return a[0] + 1; }\n'
_OPTIMIZED = (
    '#include "top.h"\n'
    "int top(int *a) {\n"
    "#pragma HLS PIPELINE II=1\n"
    "  return a[0];\n"
    "}\n"
)


def _report(*, latency: int = 100, clock_ns: float = 5.0):
    return SimpleNamespace(
        latency_worst=latency,
        latency_avg=latency,
        interval_max=latency,
        clock_period_ns=clock_ns,
        resources={
            "LUT": 100,
            "FF": 100,
            "DSP": 1,
            "BRAM_18K": 0,
            "URAM": 0,
        },
        available=dict(_AVAILABLE),
        pipeline_type="loop",
        loop_metrics=[],
    )


def _result(
    kind: str,
    ok: bool,
    *,
    phase: str | None = None,
    report=None,
    cosim=None,
    log: str = "",
) -> ToolResult:
    result = ToolResult(
        kind=kind,
        ok=ok,
        phase=phase or ("pass" if ok else f"{kind}_fail"),
        return_code=0 if ok else 1,
        log=log,
        elapsed_s=0.01,
        report=report,
        cosim=cosim,
    )
    result.brief = lambda: f"[{kind}] {result.phase}"
    return result


def _task(tmp_path: Path, *, requires_cosim: bool = False, budget: int = 40) -> Task:
    return Task(
        dir=tmp_path,
        id="p0_route",
        type="repair",
        difficulty=1,
        top="top",
        budget=budget,
        part="xcu55c-fsvh2892-2L-e",
        clock_ns=5.0,
        requires_cosim=requires_cosim,
        initial_condition="",
        description="Repair or optimize from real tool feedback.",
        kernel_name="top.cpp",
        kernel_code=_STARTER,
        headers={"top.h": "int top(int *a);\n"},
        public_tb_name="top_tb.cpp",
        public_tb_code="int main() { return 0; }\n",
    )


class _Llm:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        response = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        if isinstance(response, BaseException):
            raise response
        return response


class _Server:
    def __init__(self, budget: int, csim, synth, cosim=None):
        self.budget = Budget(total=budget)
        self._csim_fn = csim
        self._synth_fn = synth
        self._cosim_fn = cosim
        self.calls: list[tuple[str, str]] = []
        self.transcript = []
        self.run_root = Path("/tmp/p0-route")

    def csim(self, code):
        self.budget.charge("csim")
        self.calls.append(("csim", code))
        return self._csim_fn(code)

    def synth(self, code):
        self.budget.charge("synth")
        self.calls.append(("synth", code))
        return self._synth_fn(code)

    def cosim(self, code):
        self.budget.charge("cosim")
        self.calls.append(("cosim", code))
        assert self._cosim_fn is not None
        return self._cosim_fn(code)


def _run_auto(tmp_path, task, server, llm, **config_overrides):
    config = AgentConfig(
        mode="auto",
        output_root=str(tmp_path / "runs"),
        verbose=False,
        max_repair_attempts=config_overrides.get("max_repair_attempts", 1),
        max_structural_attempts=config_overrides.get(
            "max_structural_attempts", 1
        ),
        max_optimization_rounds=config_overrides.get(
            "max_optimization_rounds", 0
        ),
    )
    state = RunState(
        task=task,
        server=server,
        llm=llm,
        config=config,
        kernel=task.kernel_code,
        safe_fallback_kernel=task.kernel_code,
    )
    state = build_pipeline(
        config=config, task=task, server=server, llm=llm
    ).run(state)
    if not state.metadata.get("finalized"):
        state = step_finalize(state)
    return state


def test_cli_defaults_to_auto_and_preserves_legacy_modes() -> None:
    default = agent_main.parse_args(["--task", "/tmp/task"])
    assert default.mode == "auto"
    assert default.run_role == "submission"

    for mode in (
        "baseline",
        "repair",
        "optimize",
        "structural",
        "full",
    ):
        assert agent_main.parse_args(
            ["--task", "/tmp/task", "--mode", mode]
        ).mode == mode


@pytest.mark.parametrize("budget", ["0", "21"])
def test_submission_budget_override_fails_with_report(
    tmp_path: Path, budget: str
) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "task.toml").write_text(
        "\n".join(
            [
                'task_id = "budget_guard"',
                'top = "top"',
                'kernel_file = "top.cpp"',
                'header_files = ["top.h"]',
                'public_tb = "top_tb.cpp"',
                "budget = 20",
                "[target]",
                'part = "xcu55c-fsvh2892-2L-e"',
                "clock_ns = 5.0",
            ]
        )
        + "\n"
    )
    (task_dir / "top.cpp").write_text(_STARTER)
    (task_dir / "top.h").write_text("int top(int *a);\n")
    (task_dir / "top_tb.cpp").write_text("int main() { return 0; }\n")
    output = tmp_path / "runs"

    rc = agent_main.main(
        [
            "--task",
            str(task_dir),
            "--mode",
            "baseline",
            "--budget",
            budget,
            "--output-root",
            str(output),
            "--quiet",
        ]
    )

    report = json.loads(
        (output / "budget_guard" / "run_report.json").read_text()
    )
    assert rc == 4
    assert report["status"] == "failed"
    assert report["stop_reason"] == "budget_override_invalid"


@pytest.mark.parametrize("phase", ["compile_error", "runtime_fail"])
def test_auto_routes_csim_failure_to_full_repair(tmp_path, phase) -> None:
    task = _task(tmp_path)
    server = _Server(
        task.budget,
        lambda code: _result(
            "csim",
            code == _FIXED,
            phase="pass" if code == _FIXED else phase,
            log="compile/function failure",
        ),
        lambda code: _result("synth", True, report=_report()),
    )
    llm = _Llm([_FIXED])

    state = _run_auto(tmp_path, task, server, llm)

    assert state.status == "completed"
    assert state.kernel == _FIXED
    assert [kind for kind, _ in server.calls] == ["csim", "csim", "synth"]
    assert state.last_verified_kernel == _FIXED


def test_auto_routes_synth_failure_to_synthesis_repair(tmp_path) -> None:
    task = _task(tmp_path)
    server = _Server(
        task.budget,
        lambda code: _result("csim", True),
        lambda code: _result(
            "synth",
            code == _FIXED,
            phase="pass" if code == _FIXED else "synth_error",
            report=_report() if code == _FIXED else None,
            log="unsupported construct",
        ),
    )

    state = _run_auto(tmp_path, task, server, _Llm([_FIXED]))

    assert state.status == "completed"
    assert state.kernel == _FIXED
    assert [kind for kind, _ in server.calls] == [
        "csim",
        "synth",
        "csim",
        "synth",
    ]


def test_interface_rejection_calls_no_candidate_tool_and_preserves_starter(
    tmp_path,
) -> None:
    task = _task(tmp_path)
    prior = _result("csim", False, phase="compile_error")

    class NoCandidateTools:
        def csim(self, code):
            raise AssertionError("interface-invalid candidate reached CSim")

        def synth(self, code):
            raise AssertionError("interface-invalid candidate reached Synth")

    config = AgentConfig(output_root=str(tmp_path), verbose=False)
    state = RunState(
        task=task,
        server=NoCandidateTools(),
        llm=_Llm(['#include "top.h"\nlong top(int *a) { return a[0]; }\n']),
        config=config,
        kernel=_STARTER,
        safe_fallback_kernel=_STARTER,
        results=[prior],
    )

    state = RepairAgent(state.llm, max_attempts=1).run(state)
    state = step_finalize(state)

    assert state.status == "failed"
    assert state.stop_reason == "repair_failed"
    assert state.kernel == _STARTER
    assert state.metadata["interface_validations"][-1]["ok"] is False


def test_rejected_optimize_candidate_does_not_poison_final_interface_gate(
    tmp_path,
) -> None:
    task = _task(tmp_path)
    malformed = """int helper(int x) {
  if (x > 0) {
    return x + 1;
"""

    server = _Server(
        task.budget,
        csim=lambda code: _result("csim", True),
        synth=lambda code: _result("synth", True, report=_report()),
    )

    state = _run_auto(
        tmp_path,
        task,
        server,
        _Llm([malformed, malformed]),
        max_optimization_rounds=2,
    )

    assert state.status == "completed"
    assert state.stop_reason == ""
    assert state.kernel == _STARTER
    assert state.interface_ok is True
    assert state.metadata["interface_gate"]["ok"] is True
    assert state.metadata["public_acceptance"] == {"ok": True, "failures": []}
    assert state.metadata["interface_validations"][-1]["ok"] is False
    assert state.metadata["interface_validations"][-1]["reason"] == (
        "unbalanced_cpp_delimiters"
    )
    assert state.metadata["semantic_duplicate_skips"] == 1


def test_auto_structural_candidate_repeats_full_cosim_gate(tmp_path) -> None:
    task = _task(tmp_path, requires_cosim=True, budget=80)

    def cosim(code):
        passed = code == _FIXED
        return _result(
            "cosim",
            passed,
            phase="pass" if passed else "timeout",
            report=_report(latency=80 if passed else 100),
            cosim=SimpleNamespace(
                passed=passed,
                latency_max=80 if passed else None,
            ),
        )

    server = _Server(
        task.budget,
        lambda code: _result("csim", True),
        lambda code: _result("synth", True, report=_report()),
        cosim,
    )
    state = _run_auto(tmp_path, task, server, _Llm([_FIXED]))

    assert state.status == "completed"
    assert state.kernel == _FIXED
    assert [kind for kind, _ in server.calls] == [
        "csim",
        "synth",
        "cosim",
        "csim",
        "synth",
        "cosim",
    ]
    assert state.cosim_ok is True


def test_low_latency_candidate_with_failed_cosim_is_rejected(tmp_path) -> None:
    task = _task(tmp_path, requires_cosim=True, budget=40)
    baseline_synth = _result("synth", True, report=_report(latency=100))
    server = _Server(
        30,
        lambda code: _result("csim", True),
        lambda code: _result("synth", True, report=_report(latency=10)),
        lambda code: _result(
            "cosim",
            False,
            phase="timeout",
            report=_report(latency=10),
            cosim=SimpleNamespace(passed=False, latency_max=None),
        ),
    )
    state = RunState(
        task=task,
        server=server,
        llm=_Llm([_OPTIMIZED]),
        config=AgentConfig(mode="auto", output_root=str(tmp_path), verbose=False),
        kernel=_STARTER,
        safe_fallback_kernel=_STARTER,
        last_verified_kernel=_STARTER,
        results=[baseline_synth],
        csim_ok=True,
        synth_ok=True,
        cosim_ok=True,
        interface_ok=True,
        frequency_ok=True,
        resource_ok=True,
        best_latency=100,
        best_synth_result=baseline_synth,
    )

    state = OptimizeAgent(state.llm, max_rounds=1).run(state)

    assert state.kernel == _STARTER
    assert state.last_verified_kernel == _STARTER
    assert [kind for kind, _ in server.calls] == ["csim", "synth", "cosim"]


def test_structural_budget_shortfall_keeps_fallback_and_stops_safely(
    tmp_path,
) -> None:
    task = _task(tmp_path, requires_cosim=True, budget=40)
    server = _Server(
        task.budget,
        lambda code: _result("csim", True),
        lambda code: _result("synth", True, report=_report()),
        lambda code: _result(
            "cosim",
            False,
            phase="timeout",
            report=_report(),
            cosim=SimpleNamespace(passed=False, latency_max=None),
        ),
    )

    state = _run_auto(tmp_path, task, server, _Llm([_FIXED]))

    assert state.status == "budget_exceeded"
    assert state.stop_reason == "insufficient_budget_for_candidate_validation"
    assert state.kernel == _STARTER
    assert [kind for kind, _ in server.calls] == ["csim", "synth", "cosim"]


def test_api_exception_is_infrastructure_error_without_unverified_output(
    tmp_path,
) -> None:
    task = _task(tmp_path)
    server = _Server(
        task.budget,
        lambda code: _result("csim", False, phase="runtime_fail"),
        lambda code: _result("synth", True, report=_report()),
    )

    state = _run_auto(
        tmp_path,
        task,
        server,
        _Llm([RuntimeError("API unavailable")]),
    )

    assert state.status == "infrastructure_error"
    assert state.kernel == _STARTER
    assert state.scorecard is None
    assert state.metadata["infrastructure_error"]["step"] == "repair"


def test_noop_repair_fails_without_extra_tools_or_scoring(tmp_path) -> None:
    task = _task(tmp_path)
    server = _Server(
        task.budget,
        lambda code: _result("csim", False, phase="runtime_fail"),
        lambda code: _result("synth", True, report=_report()),
    )

    state = _run_auto(tmp_path, task, server, _Llm([_STARTER]))

    assert state.status == "failed"
    assert state.kernel == _STARTER
    assert state.scorecard is None
    assert [kind for kind, _ in server.calls] == ["csim"]


def test_frequency_failure_blocks_optimization_and_completion(tmp_path) -> None:
    task = _task(tmp_path)
    server = _Server(
        task.budget,
        lambda code: _result("csim", True),
        lambda code: _result("synth", True, report=_report(clock_ns=10.01)),
    )
    llm = _Llm([AssertionError("frequency-invalid baseline must not optimize")])

    state = _run_auto(tmp_path, task, server, llm)

    assert state.status == "failed"
    assert state.stop_reason == "minimum_100mhz_not_met"
    assert state.kernel == _STARTER
    assert llm.calls == 0


def test_llm_bootstrap_exception_writes_redacted_infrastructure_report(
    tmp_path, monkeypatch
) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "task.toml").write_text(
        "\n".join(
            [
                'task_id = "bootstrap_failure"',
                'top = "top"',
                'kernel_file = "top.cpp"',
                'header_files = ["top.h"]',
                'public_tb = "top_tb.cpp"',
                "budget = 20",
                "[target]",
                'part = "xcu55c-fsvh2892-2L-e"',
                "clock_ns = 5.0",
            ]
        )
        + "\n"
    )
    (task_dir / "top.cpp").write_text(_STARTER)
    (task_dir / "top.h").write_text("int top(int *a);\n")
    (task_dir / "top_tb.cpp").write_text("int main() { return 0; }\n")
    output = tmp_path / "runs"

    def fail_backend(backend):
        raise RuntimeError(
            "request to https://private.example/v1 failed with sk-secretvalue"
        )

    monkeypatch.setattr(agent_main, "create_llm", fail_backend)
    rc = agent_main.main(
        [
            "--task",
            str(task_dir),
            "--mode",
            "auto",
            "--output-root",
            str(output),
            "--quiet",
        ]
    )

    import json

    report = json.loads(
        (output / "bootstrap_failure" / "run_report.json").read_text()
    )
    assert rc == 6
    assert report["status"] == "infrastructure_error"
    assert report["scoring"] is None
    assert "private.example" not in report["error"]["message"]
    assert "sk-secretvalue" not in report["error"]["message"]
