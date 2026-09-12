import json
from types import SimpleNamespace

from agent.agents.repair import RepairAgent, _repair_attempt_record


def _result(kind, ok, brief, *, log="", phase="run"):
    return SimpleNamespace(
        kind=kind,
        ok=ok,
        log=log,
        phase=phase,
        report=None,
        brief=lambda: brief,
    )


def test_repair_reuses_adjacent_pipeline_csim_failure() -> None:
    failed = _result(
        "csim",
        False,
        "[csim] runtime_fail",
        log="projection mismatch",
    )
    passed = _result("csim", True, "[csim] pass")
    synthesized = _result("synth", True, "[synth] pass")
    synthesized.report = SimpleNamespace(
        latency_worst=10,
        latency_avg=10,
        clock_period_ns=5.0,
        resources={"LUT": 1, "FF": 1, "DSP": 0, "BRAM_18K": 0, "URAM": 0},
        available={
            "LUT": 100,
            "FF": 100,
            "DSP": 100,
            "BRAM_18K": 100,
            "URAM": 100,
        },
    )

    class Llm:
        def complete(self, system, prompt):
            return "int projection() { return 1; }"

    class Server:
        def __init__(self) -> None:
            self.csim_kernels = []
            self.synth_kernels = []

        def csim(self, kernel):
            self.csim_kernels.append(kernel)
            return passed

        def synth(self, kernel):
            self.synth_kernels.append(kernel)
            return synthesized

    task = SimpleNamespace(
        id="projection_bugfix",
        description="repair projection",
        top="projection",
        headers={},
        kernel_name="projection.cpp",
        requires_cosim=False,
        clock_ns=5.0,
    )
    server = Server()
    logs = []
    starter = "int projection() { return 0; }"
    state = SimpleNamespace(
        task=task,
        server=server,
        kernel=starter,
        results=[failed],
        csim_ok=False,
        synth_ok=False,
        status="running",
        stop_reason="",
        metadata={},
        interface_ok=False,
        frequency_ok=False,
        resource_ok=False,
        cosim_ok=False,
        best_latency=None,
        last_verified_kernel=None,
        log=logs.append,
    )

    result = RepairAgent(Llm(), max_attempts=3).run(state)

    assert result.csim_ok is True
    assert result.synth_ok is True
    assert server.csim_kernels == ["int projection() { return 1; }\n"]
    assert server.synth_kernels == ["int projection() { return 1; }\n"]
    assert len(result.results) == 3
    assert "repair: reusing pipeline csim failure" in logs


def test_repair_skips_an_exact_candidate_before_reusing_tools() -> None:
    initial = _result("csim", False, "[csim] runtime_fail", log="mismatch")
    failed = _result("csim", False, "[csim] runtime_fail", log="still mismatch")
    passed = _result("csim", True, "[csim] pass")
    synthesized = _result("synth", True, "[synth] pass")
    synthesized.report = SimpleNamespace(
        latency_worst=10,
        latency_avg=10,
        clock_period_ns=5.0,
        resources={"LUT": 1, "FF": 1, "DSP": 0, "BRAM_18K": 0, "URAM": 0},
        available={"LUT": 100, "FF": 100, "DSP": 100, "BRAM_18K": 100, "URAM": 100},
    )
    bad = "int projection() { return 2; }"
    starter = "int projection() { return 0; }"
    good = "int projection() { return 1; }"

    class Llm:
        def __init__(self):
            self.responses = iter([bad, starter, good])

        def complete(self, system, prompt):
            return next(self.responses)

    class Server:
        def __init__(self):
            self.csim_kernels = []
            self.synth_kernels = []

        def csim(self, kernel):
            self.csim_kernels.append(kernel)
            return passed if "return 1" in kernel else failed

        def synth(self, kernel):
            self.synth_kernels.append(kernel)
            return synthesized

    task = SimpleNamespace(
        id="projection_bugfix",
        description="repair projection",
        top="projection",
        headers={},
        kernel_name="projection.cpp",
        requires_cosim=False,
        clock_ns=5.0,
    )
    server = Server()
    logs = []
    state = SimpleNamespace(
        task=task,
        server=server,
        kernel=starter,
        results=[initial],
        csim_ok=False,
        synth_ok=False,
        status="running",
        stop_reason="",
        metadata={},
        interface_ok=False,
        frequency_ok=False,
        resource_ok=False,
        cosim_ok=False,
        best_latency=None,
        last_verified_kernel=None,
        log=logs.append,
    )

    result = RepairAgent(Llm(), max_attempts=3).run(state)

    assert result.csim_ok is True
    assert len(server.csim_kernels) == 2
    assert result.metadata["repair_duplicate_skips"] == 1
    assert any("duplicate candidate" in line for line in logs)


def test_repair_edits_the_latest_interface_valid_failed_candidate() -> None:
    initial = _result("csim", False, "[csim] runtime_fail", log="initial mismatch")
    failed = _result("csim", False, "[csim] runtime_fail", log="result mismatch")
    passed = _result("csim", True, "[csim] pass")
    synthesized = _result("synth", True, "[synth] pass")
    synthesized.report = SimpleNamespace(
        latency_worst=10,
        latency_avg=10,
        clock_period_ns=5.0,
        resources={"LUT": 1, "FF": 1, "DSP": 0, "BRAM_18K": 0, "URAM": 0},
        available={"LUT": 100, "FF": 100, "DSP": 100, "BRAM_18K": 100, "URAM": 100},
    )
    first = "int projection() { int value = 2; return value; }"
    second = "int projection() { int value = 1; return value; }"

    class Llm:
        def __init__(self):
            self.responses = iter([first, second])
            self.prompts = []

        def complete(self, system, prompt):
            self.prompts.append(prompt)
            return next(self.responses)

    class Server:
        def __init__(self):
            self.csim_kernels = []

        def csim(self, kernel):
            self.csim_kernels.append(kernel)
            return passed if "value = 1" in kernel else failed

        def synth(self, kernel):
            return synthesized

    task = SimpleNamespace(
        id="projection_bugfix",
        description="repair projection",
        top="projection",
        headers={},
        kernel_name="projection.cpp",
        requires_cosim=False,
        clock_ns=5.0,
    )
    llm = Llm()
    state = SimpleNamespace(
        task=task,
        server=Server(),
        kernel="int projection() { return 0; }",
        results=[initial],
        csim_ok=False,
        synth_ok=False,
        status="running",
        stop_reason="",
        metadata={},
        interface_ok=False,
        frequency_ok=False,
        resource_ok=False,
        cosim_ok=False,
        best_latency=None,
        last_verified_kernel=None,
        log=lambda message: None,
    )

    result = RepairAgent(llm, max_attempts=2).run(state)

    assert result.csim_ok is True
    second_payload = json.loads(llm.prompts[1])
    assert second_payload["editable_kernel"].strip().endswith(first)
    assert result.metadata["repair_working_candidate_advances"] == 1


def test_repair_attempt_summary_prefers_high_signal_error() -> None:
    result = _result(
        "csim",
        False,
        "[csim] runtime_fail",
        log="Vitis HLS banner\nINFO: running simulation\nPUBLIC_CSIM_MISMATCH: force_x[0] expected 3 got 4",
        phase="runtime_fail",
    )

    record = _repair_attempt_record(
        1,
        "int projection() { return 0; }",
        "int projection() { return 2; }",
        result,
    )

    assert record["result"]["summary"].startswith("PUBLIC_CSIM_MISMATCH")
