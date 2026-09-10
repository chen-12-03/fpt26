"""C-simulation must not lose the toolchain evidence it observed.

The driver log proves the pinned Vitis 2025.2 / U55C configuration was used,
and grading harvests it from the tool result.  C-simulation is split into
compile and run phases, and only the compile-phase log carries that evidence —
so a design that compiles and then fails its testbench used to look like it had
never invoked the pinned part.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent.reporting.metrics import _toolchain_evidence
from llm4hls import tools as hls_tools


COMPILE_LOG = (
    "****** vitis-run v2025.2 ******\n"
    "INFO: [HLS 200-1510] Running: set_part xcu55c-fsvh2892-2L-e\n"
    "INFO: [HLS 200-10] Setting target device to 'xcu55c-fsvh2892-2L-e'\n"
    "Compiling tb.cpp...\n"
)


def _run_csim(
    monkeypatch,
    tmp_path: Path,
    *,
    return_code: int,
    stdout: str,
) -> hls_tools.ToolResult:
    """Run CSimTool against a fake Vitis that always compiles successfully."""

    def fake_run_vitis_tcl(tcl: str, work: Path, timeout_s: float):
        exe = Path(work) / "csim_proj" / "sol" / "csim" / "build" / "csim.exe"
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text("#!/bin/sh\n")
        return SimpleNamespace(
            stdout=COMPILE_LOG,
            stderr="",
            return_code=0,
            timeout=False,
            elapsed_s=1.0,
        )

    def fake_run_binary(exe: Path, cwd: Path, timeout_s: float):
        return SimpleNamespace(
            stdout=stdout,
            stderr="",
            return_code=return_code,
            timeout=False,
            elapsed_s=0.5,
        )

    monkeypatch.setattr(hls_tools.vitis, "run_vitis_tcl", fake_run_vitis_tcl)
    monkeypatch.setattr(hls_tools.vitis, "run_binary", fake_run_binary)
    return hls_tools.CSimTool().run(
        tmp_path / "build", {"kernel.cpp": "void k() {}"}, "k"
    )


def test_failed_testbench_keeps_the_driver_evidence(monkeypatch, tmp_path) -> None:
    result = _run_csim(
        monkeypatch,
        tmp_path,
        return_code=1,
        stdout="Test 2 failed: Got z0=0x1, z1=0xfffffffffffffffe\n",
    )

    assert result.phase == "runtime_fail"
    # The functional failure the agent needs to read is still there...
    assert "Test 2 failed" in result.log
    # ...alongside the toolchain that produced it.
    assert "vitis-run v2025.2" in result.log
    assert "set_part xcu55c-fsvh2892-2L-e" in result.log


def test_passing_testbench_keeps_the_driver_evidence(monkeypatch, tmp_path) -> None:
    result = _run_csim(
        monkeypatch, tmp_path, return_code=0, stdout="INFO: [SIM 2] PASSED\n"
    )

    assert result.phase == "pass"
    assert "INFO: [SIM 2] PASSED" in result.log
    assert "set_part xcu55c-fsvh2892-2L-e" in result.log


def test_part_gate_is_satisfied_by_a_compiled_design(monkeypatch, tmp_path) -> None:
    """Grading reads the part out of the tool log; the evidence must survive."""
    result = _run_csim(
        monkeypatch, tmp_path, return_code=1, stdout="Test 1 failed\n"
    )
    state = SimpleNamespace(
        results=[result],
        metadata={},
        task=SimpleNamespace(part="xcu55c-fsvh2892-2L-e"),
    )

    evidence = _toolchain_evidence(state)

    assert evidence["observed_parts"] == ["xcu55c-fsvh2892-2L-e"]
    assert evidence["real_tool_banner_observed"] is True
    assert evidence["part_gate_ok"] is True


def test_compile_error_log_is_left_alone(monkeypatch, tmp_path) -> None:
    """The compile-phase log already carries the evidence — no duplication."""
    monkeypatch.setattr(
        hls_tools.vitis,
        "run_vitis_tcl",
        lambda tcl, work, timeout_s: SimpleNamespace(
            stdout=COMPILE_LOG,
            stderr="ERROR: [HLS 200-70] cannot open kernel.cpp\n",
            return_code=1,
            timeout=False,
            elapsed_s=0.7,
        ),
    )

    result = hls_tools.CSimTool().run(
        tmp_path / "build", {"kernel.cpp": "void k() {}"}, "k"
    )

    assert result.phase == "compile_error"
    # The compile log is returned verbatim — evidence included, and not twice.
    assert result.log.count("set_part xcu55c-fsvh2892-2L-e") == 1
