"""Low-level `vitis-run --mode hls --tcl <tcl>` runner.

Sources the pinned Vitis settings64.sh, then runs a generated TCL script in a
given working directory. Vitis 2025.2 replaced the standalone `vitis_hls`
binary with `vitis-run --mode hls --tcl <script>`; the HLS Tcl commands
(open_project / csynth_design / cosim_design / ...) are otherwise unchanged.
On timeout the whole process group is killed (Vitis spawns children), so
nothing is left hanging. Stdlib-only (no psutil).
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass
class ProcResult:
    return_code: int
    stdout: str
    stderr: str
    elapsed_s: float
    timeout: bool


def run_vitis_tcl(tcl_text: str, workdir: Path, timeout_s: float) -> ProcResult:
    """Write `tcl_text` to workdir/run_hls.tcl and run vitis-run on it."""
    workdir.mkdir(parents=True, exist_ok=True)
    tcl_fp = workdir / "run_hls.tcl"
    tcl_fp.write_text(tcl_text)

    # `source settings64.sh` puts vitis-run on PATH inside this shell only.
    inner = (
        f"source '{config.VITIS_SETTINGS}' >/dev/null 2>&1 "
        "&& exec vitis-run --mode hls --tcl run_hls.tcl"
    )
    return _run_shell(inner, workdir, timeout_s)


def run_binary(binary: Path, workdir: Path, timeout_s: float) -> ProcResult:
    """Run a compiled executable (e.g. csim.exe) and capture its return code."""
    return _run_shell(f"exec '{binary}'", workdir, timeout_s)


def _run_shell(inner_cmd: str, workdir: Path, timeout_s: float) -> ProcResult:
    t0 = time.monotonic()
    p = subprocess.Popen(
        ["bash", "-c", inner_cmd],
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,  # own process group -> killable as a unit
    )
    try:
        stdout, stderr = p.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = p.communicate()
        return ProcResult(-1, stdout or "", stderr or "", time.monotonic() - t0, True)
    return ProcResult(p.returncode, stdout, stderr, time.monotonic() - t0, False)
