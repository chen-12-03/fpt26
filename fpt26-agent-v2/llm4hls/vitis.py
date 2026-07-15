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
import shlex
import shutil
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
    return _run_shell(f"exec {shlex.quote(str(binary.resolve()))}", workdir, timeout_s)


def _run_shell(inner_cmd: str, workdir: Path, timeout_s: float) -> ProcResult:
    t0 = time.monotonic()
    p = subprocess.Popen(
        ["bash", "-c", inner_cmd],
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_prepared_env(),
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


def _prepared_env() -> dict[str, str]:
    env = os.environ.copy()
    _ensure_locale(env)
    _ensure_libtinfo_compat(env)
    return env


def _ensure_locale(env: dict[str, str]) -> None:
    """Vitis 2025.2's launcher forces en_US.UTF-8; provide it from /tmp if absent."""
    locale_dir = Path(env.get("LLM4HLS_LOCALE_DIR", "/tmp/vitis-locale"))
    locale_path = locale_dir / "en_US.UTF-8"

    if not locale_path.exists() and shutil.which("localedef"):
        try:
            locale_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "localedef",
                    "--no-archive",
                    "-i",
                    "en_US",
                    "-f",
                    "UTF-8",
                    str(locale_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            pass

    if locale_path.exists():
        env.setdefault("LOCPATH", str(locale_dir))


def _ensure_libtinfo_compat(env: dict[str, str]) -> None:
    """Expose a Vitis-compatible libtinfo.so.5 without adding a whole sysroot."""
    install_root = config.VITIS_HLS_ROOT.resolve().parent
    libtinfo = (
        install_root
        / "data"
        / "emulation"
        / "qemu"
        / "comp"
        / "qemu"
        / "sysroots"
        / "x86_64-petalinux-linux"
        / "lib"
        / "libtinfo.so.5.9"
    )
    if not libtinfo.exists():
        return

    compat_dir = Path(env.get("LLM4HLS_VITIS_COMPAT_DIR", "/tmp/vitis-compat"))
    compat_link = compat_dir / "libtinfo.so.5"
    try:
        compat_dir.mkdir(parents=True, exist_ok=True)
        if compat_link.exists() or compat_link.is_symlink():
            if not compat_link.is_symlink() or compat_link.resolve() != libtinfo.resolve():
                compat_link.unlink()
        if not compat_link.exists():
            compat_link.symlink_to(libtinfo)
    except OSError:
        return

    _prepend_env_path(env, "LD_LIBRARY_PATH", compat_dir)


def _prepend_env_path(env: dict[str, str], key: str, path: Path) -> None:
    text = str(path)
    old = env.get(key, "")
    parts = [p for p in old.split(os.pathsep) if p]
    if text in parts:
        return
    env[key] = text if not old else text + os.pathsep + old
