"""Operator-friendly CLI wrapper around :mod:`agent.main`.

This module owns task discovery, run naming, environment preparation, command
preview, and terminal-log teeing.  The actual HLS workflow remains in
``agent.main`` so the interactive and automation entry points cannot diverge.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from agent.console_ui import configure, console_width, paint, strip_ansi

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10/3.11 container compatibility
    import tomli as tomllib


_MODES = ("auto", "baseline", "repair", "optimize", "structural", "full")
_BACKENDS = ("auto", "openrouter", "custom", "scripted")
_RUNTIMES = ("docker", "local")
_CONTAINER_ROOT = Path("/workspace")
_DEFAULT_IMAGE = "fpt26-agent-v3:latest"
_SAFE_LABEL_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class CliError(ValueError):
    """User-facing configuration error."""


@dataclass(frozen=True)
class TaskInfo:
    path: Path
    task_id: str
    task_type: str
    top: str
    budget: int | None
    requires_cosim: bool


@dataclass(frozen=True)
class RunSpec:
    task: TaskInfo
    runtime: str
    image: str
    mode: str
    backend: str
    model: str
    budget: int | None
    output_root: Path
    log_file: Path
    env_file: Path | None
    vitis_settings: Path | None
    max_repair_attempts: int | None
    max_optimization_rounds: int | None
    max_structural_attempts: int | None
    scoring_profile: str
    competition: bool
    quiet: bool
    color: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_task_root() -> Path:
    return _repo_root() / "tasks"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fpt26-task",
        description=(
            "Discover and run FPT26 tasks with a concise configuration panel, "
            "automatic run naming, and a terminal log."
        ),
    )
    task = parser.add_mutually_exclusive_group()
    task.add_argument("--task-id", help="Task ID from task.toml")
    task.add_argument(
        "--task-path",
        "--task",
        dest="task_path",
        type=Path,
        help="Direct path to a task directory",
    )
    parser.add_argument(
        "--task-root",
        type=Path,
        default=_default_task_root(),
        help="Task repository root used for --task-id and --list-tasks",
    )
    parser.add_argument(
        "--list-tasks",
        nargs="?",
        const="",
        metavar="FILTER",
        help="List known tasks, optionally filtered by ID/path text",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Check container, Python, Vitis, task repository, and LLM configuration",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt for omitted run settings and ask for confirmation",
    )
    parser.add_argument(
        "--runtime",
        choices=_RUNTIMES,
        default="docker",
        help="Execution runtime (default: docker; local must be explicit)",
    )
    parser.add_argument(
        "--image",
        help=(
            "Docker image; defaults to FPT26_AGENT_IMAGE or "
            f"{_DEFAULT_IMAGE}"
        ),
    )
    parser.add_argument("--mode", choices=_MODES)
    parser.add_argument("--backend", choices=_BACKENDS)
    parser.add_argument("--model", help="Override both LLM4HLS_MODEL and FPT26_LLM_MODEL")
    parser.add_argument("--budget", type=int)
    parser.add_argument("--max-repair-attempts", type=int)
    parser.add_argument("--max-optimization-rounds", type=int)
    parser.add_argument("--max-structural-attempts", type=int)
    parser.add_argument(
        "--scoring-profile",
        choices=("balanced", "extreme_speed", "extreme_speed_capped"),
        default="balanced",
    )
    parser.add_argument("--competition", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--run-label", help="Directory name below runs/")
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Exact run output root; overrides the generated runs/<label>",
    )
    parser.add_argument("--log-file", type=Path, help="Exact terminal-log path")
    parser.add_argument(
        "--env-file",
        type=Path,
        help="KEY=VALUE environment file; defaults to /tmp/fpt26.env when present",
    )
    parser.add_argument(
        "--no-env-file",
        action="store_true",
        help="Do not auto-load /tmp/fpt26.env",
    )
    parser.add_argument(
        "--vitis-settings",
        type=Path,
        help="settings64.sh to source for the child process",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without executing")
    parser.add_argument("--yes", action="store_true", help="Skip interactive confirmation")
    return parser.parse_args(argv)


def discover_tasks(task_root: Path) -> list[TaskInfo]:
    root = task_root.expanduser().resolve()
    if not root.is_dir():
        raise CliError(f"task root not found: {root}")
    tasks: list[TaskInfo] = []
    for manifest in sorted(root.rglob("task.toml")):
        try:
            tasks.append(read_task_info(manifest.parent))
        except (CliError, OSError, tomllib.TOMLDecodeError):
            continue
    return tasks


def read_task_info(task_path: Path) -> TaskInfo:
    path = task_path.expanduser().resolve()
    manifest = path / "task.toml"
    if not path.is_dir() or not manifest.is_file():
        raise CliError(f"task directory must contain task.toml: {path}")
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    task_id = str(data.get("task_id") or path.name).strip()
    if not task_id:
        raise CliError(f"task_id missing in {manifest}")
    raw_budget = data.get("budget")
    budget = int(raw_budget) if isinstance(raw_budget, int) else None
    return TaskInfo(
        path=path,
        task_id=task_id,
        task_type=str(data.get("task_type") or "unknown"),
        top=str(data.get("top") or "unknown"),
        budget=budget,
        requires_cosim=bool(data.get("requires_cosim", False)),
    )


def resolve_task(
    *,
    task_root: Path,
    task_id: str | None,
    task_path: Path | None,
) -> TaskInfo:
    if task_path is not None:
        return read_task_info(task_path)
    if not task_id:
        raise CliError("provide --task-id or --task-path")
    matches = [task for task in discover_tasks(task_root) if task.task_id == task_id]
    if not matches:
        raise CliError(f"task ID not found below {task_root}: {task_id}")
    if len(matches) > 1:
        paths = ", ".join(str(task.path) for task in matches[:4])
        raise CliError(f"task ID is ambiguous ({len(matches)} matches): {paths}")
    return matches[0]


def _ask(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _interactive_task(task_root: Path) -> tuple[str | None, Path | None]:
    value = _ask("Task ID or task path")
    candidate = Path(value).expanduser()
    if candidate.is_dir():
        return None, candidate
    return value, None


def _safe_run_label(task_id: str, supplied: str | None) -> str:
    raw = supplied or f"single_{task_id}_{datetime.now():%Y%m%d_%H%M%S}"
    normalized = _SAFE_LABEL_RE.sub("_", raw).strip("._")
    if not normalized:
        raise CliError("run label is empty after normalization")
    return normalized[:180]


def _default_env_file(args: argparse.Namespace) -> Path | None:
    if args.no_env_file:
        return None
    if args.env_file is not None:
        return args.env_file.expanduser().resolve()
    configured = os.environ.get("FPT26_ENV_FILE", "").strip()
    candidate = Path(configured) if configured else Path("/tmp/fpt26.env")
    return candidate.resolve() if candidate.is_file() else None


def _auto_vitis_settings(
    explicit: Path | None,
    *,
    runtime: str,
) -> Path | None:
    configured = os.environ.get("FPT26_VITIS_SETTINGS", "").strip()
    selected = explicit or (Path(configured) if configured else None)
    if selected is not None:
        path = selected.expanduser().resolve()
        if not path.is_file():
            raise CliError(f"Vitis settings file not found: {path}")
        return path
    if runtime == "local" and shutil.which("vitis-run"):
        return None
    candidates = (
        Path("/tools/Xilinx/2025.2/Vitis/settings64.sh"),
        Path("/tools/Xilinx/Vitis/2025.2/settings64.sh"),
    )
    return next((path for path in candidates if path.is_file()), None)


def _positive_optional(name: str, value: int | None) -> int | None:
    if value is not None and value <= 0:
        raise CliError(f"{name} must be positive")
    return value


def build_run_spec(args: argparse.Namespace) -> RunSpec:
    task_id = args.task_id
    task_path = args.task_path
    if task_id is None and task_path is None:
        if not sys.stdin.isatty():
            raise CliError("provide --task-id or --task-path in non-interactive mode")
        task_id, task_path = _interactive_task(args.task_root)
    task = resolve_task(
        task_root=args.task_root,
        task_id=task_id,
        task_path=task_path,
    )

    env_file = _default_env_file(args)
    env_values = _load_env_file(env_file)
    mode = args.mode or "auto"
    backend = args.backend or "openrouter"
    model = (
        args.model
        or os.environ.get("LLM4HLS_MODEL", "")
        or env_values.get("LLM4HLS_MODEL", "")
        or env_values.get("FPT26_LLM_MODEL", "")
    )
    budget = _positive_optional("budget", args.budget)
    if task.budget is not None and budget is not None and budget > task.budget:
        raise CliError(
            f"budget {budget} exceeds task budget {task.budget}"
        )
    max_repair = _positive_optional(
        "max repair attempts", args.max_repair_attempts
    )
    max_opt = _positive_optional(
        "max optimization rounds", args.max_optimization_rounds
    )
    max_structural = _positive_optional(
        "max structural attempts", args.max_structural_attempts
    )
    if args.interactive:
        if args.mode is None:
            mode = _ask("Mode", mode)
            if mode not in _MODES:
                raise CliError(f"invalid mode: {mode}")
        if args.backend is None:
            backend = _ask("Backend", backend)
            if backend not in _BACKENDS:
                raise CliError(f"invalid backend: {backend}")
        if args.model is None:
            model = _ask("Model", model)
        if args.budget is None:
            default_budget = str(task.budget or "")
            raw_budget = _ask("Budget", default_budget)
            budget = int(raw_budget) if raw_budget else None
        if args.max_optimization_rounds is None:
            max_opt = int(_ask("Max optimization rounds", "2"))

    label = _safe_run_label(task.task_id, args.run_label)
    output_root = (
        args.output_root.expanduser().resolve()
        if args.output_root
        else (_repo_root() / "runs" / label).resolve()
    )
    log_file = (
        args.log_file.expanduser().resolve()
        if args.log_file
        else (_repo_root() / "runs" / f"{label}.terminal.log").resolve()
    )
    runtime = args.runtime
    if runtime == "docker" and os.environ.get("FPT26_CLI_IN_CONTAINER") == "1":
        runtime = "container"
    return RunSpec(
        task=task,
        runtime=runtime,
        image=(
            args.image
            or os.environ.get("FPT26_AGENT_IMAGE", "").strip()
            or _DEFAULT_IMAGE
        ),
        mode=mode,
        backend=backend,
        model=model,
        budget=budget,
        output_root=output_root,
        log_file=log_file,
        env_file=env_file,
        vitis_settings=_auto_vitis_settings(
            args.vitis_settings,
            runtime=runtime,
        ),
        max_repair_attempts=max_repair,
        max_optimization_rounds=max_opt,
        max_structural_attempts=max_structural,
        scoring_profile=args.scoring_profile,
        competition=bool(args.competition),
        quiet=bool(args.quiet),
        color=args.color,
    )


def _is_below(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _container_path(path: Path, fallback: Path) -> Path:
    resolved = path.resolve()
    repo = _repo_root().resolve()
    if _is_below(resolved, repo):
        return _CONTAINER_ROOT / resolved.relative_to(repo)
    return fallback


def _vitis_mount_root(settings: Path) -> Path:
    configured = os.environ.get("VITIS_MOUNT_ROOT", "").strip()
    root = (
        Path(configured).expanduser().resolve()
        if configured
        else settings.resolve().parent.parent.parent
    )
    if root == Path("/") or not _is_below(settings, root):
        raise CliError(
            f"unsafe Vitis mount root {root}; set VITIS_MOUNT_ROOT to the "
            "specific Xilinx installation root"
        )
    if not root.is_dir():
        raise CliError(f"Vitis mount root not found: {root}")
    return root


def build_agent_command(spec: RunSpec) -> list[str]:
    docker = spec.runtime == "docker"
    container_python = spec.runtime in {"docker", "container"}
    task_path = (
        _container_path(spec.task.path, Path("/fpt26-task"))
        if docker
        else spec.task.path
    )
    output_root = (
        _container_path(
            spec.output_root,
            Path("/fpt26-output") / spec.output_root.name,
        )
        if docker
        else spec.output_root
    )
    command = [
        "python3" if container_python else sys.executable,
        "-m",
        "agent.main",
        "--task",
        str(task_path),
        "--mode",
        spec.mode,
        "--backend",
        spec.backend,
        "--output-root",
        str(output_root),
        "--scoring-profile",
        spec.scoring_profile,
    ]
    optional_values = (
        ("--budget", spec.budget),
        ("--max-repair-attempts", spec.max_repair_attempts),
        ("--max-optimization-rounds", spec.max_optimization_rounds),
        ("--max-structural-attempts", spec.max_structural_attempts),
    )
    for flag, value in optional_values:
        if value is not None:
            command.extend((flag, str(value)))
    if spec.competition:
        command.append("--competition")
    if spec.quiet:
        command.append("--quiet")
    child_color = spec.color
    if child_color == "auto":
        child_color = "always" if sys.stdout.isatty() else "never"
    command.extend(("--color", child_color))
    return command


def _load_env_file(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    if not path.is_file():
        raise CliError(f"environment file not found: {path}")
    values: dict[str, str] = {}
    for number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise CliError(f"invalid env line {path}:{number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise CliError(f"invalid env key {path}:{number}: {key}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def build_child_environment(spec: RunSpec) -> dict[str, str]:
    env = dict(os.environ)
    env.update(_load_env_file(spec.env_file))
    if spec.model:
        env["LLM4HLS_MODEL"] = spec.model
        env["FPT26_LLM_MODEL"] = spec.model
    repo = _repo_root()
    python_paths = [
        str(repo),
        str(repo / "fpt26-agent-v3"),
        str(repo / "fpt26-harness"),
    ]
    if env.get("PYTHONPATH"):
        python_paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(python_paths)

    locale_path = Path("/tmp/fpt26_locale_dirs/usr/lib/locale")
    if locale_path.is_dir() and not env.get("LOCPATH"):
        env["LOCPATH"] = str(locale_path)
    runtime_paths = [
        path
        for path in (
            Path("/tmp/fpt26_vitis_tinfo5_qemu"),
            (
                spec.vitis_settings.parent / "lib/lnx64.o/Ubuntu/22"
                if spec.vitis_settings is not None
                else Path("/tools/Xilinx/2025.2/Vitis/lib/lnx64.o/Ubuntu/22")
            ),
        )
        if path.is_dir()
    ]
    existing_ld = env.get("LD_LIBRARY_PATH", "")
    if existing_ld:
        runtime_paths.append(Path(existing_ld))
    if runtime_paths:
        env["LD_LIBRARY_PATH"] = os.pathsep.join(
            str(path) for path in runtime_paths
        )
    return env


def _local_launch_command(
    spec: RunSpec,
    agent_command: list[str],
) -> list[str]:
    if spec.vitis_settings is None:
        return agent_command
    return [
        "bash",
        "-lc",
        'set -eo pipefail; source "$1"; shift; exec "$@"',
        "fpt26-task",
        str(spec.vitis_settings),
        *agent_command,
    ]


def _docker_launch_command(
    spec: RunSpec,
    agent_command: list[str],
) -> list[str]:
    repo = _repo_root().resolve()
    command = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "-v",
        f"{repo}:{_CONTAINER_ROOT}",
        "-w",
        str(_CONTAINER_ROOT),
    ]

    for system_file in (Path("/etc/passwd"), Path("/etc/group")):
        if system_file.is_file():
            command.extend(("-v", f"{system_file}:{system_file}:ro"))
    home = Path.home().resolve()
    if home.is_dir():
        command.extend(("-v", f"{home}:{home}"))
        command.extend(("-e", f"HOME={home}"))
    command.extend(
        (
            "-e",
            f"USER={os.environ.get('USER', 'fpt26')}",
            "-e",
            f"LOGNAME={os.environ.get('LOGNAME', os.environ.get('USER', 'fpt26'))}",
            "-e",
            "PYTHONPATH=/workspace:/workspace/fpt26-agent-v3:/workspace/fpt26-harness",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "PYTHONUNBUFFERED=1",
        )
    )

    if spec.env_file is not None:
        command.extend(("--env-file", str(spec.env_file)))
    if spec.model:
        command.extend(("-e", f"LLM4HLS_MODEL={spec.model}"))
        command.extend(("-e", f"FPT26_LLM_MODEL={spec.model}"))

    if not _is_below(spec.task.path, repo):
        command.extend(("-v", f"{spec.task.path.resolve()}:/fpt26-task:ro"))
    if not _is_below(spec.output_root, repo):
        command.extend(
            (
                "-v",
                f"{spec.output_root.resolve().parent}:/fpt26-output",
            )
        )

    container_vitis = spec.vitis_settings
    if spec.vitis_settings is not None:
        mount_root = _vitis_mount_root(spec.vitis_settings)
        command.extend(("-v", f"{mount_root}:{mount_root}:ro"))

    locale_root = Path("/tmp/fpt26_locale_dirs")
    if locale_root.is_dir():
        command.extend(("-v", f"{locale_root}:{locale_root}:ro"))
        command.extend(
            ("-e", "LOCPATH=/tmp/fpt26_locale_dirs/usr/lib/locale")
        )
    tinfo_root = Path("/tmp/fpt26_vitis_tinfo5_qemu")
    runtime_paths: list[str] = []
    if tinfo_root.is_dir():
        command.extend(("-v", f"{tinfo_root}:{tinfo_root}:ro"))
        runtime_paths.append(str(tinfo_root))
    vitis_lib = (
        spec.vitis_settings.parent / "lib/lnx64.o/Ubuntu/22"
        if spec.vitis_settings is not None
        else Path("/tools/Xilinx/2025.2/Vitis/lib/lnx64.o/Ubuntu/22")
    )
    if vitis_lib.is_dir():
        runtime_paths.append(str(vitis_lib))
    if runtime_paths:
        command.extend(("-e", f"LD_LIBRARY_PATH={':'.join(runtime_paths)}"))

    command.append(spec.image)
    if container_vitis is not None:
        command.extend(
            (
                "bash",
                "-lc",
                'set -eo pipefail; source "$1"; shift; exec "$@"',
                "fpt26-task",
                str(container_vitis),
                *agent_command,
            )
        )
    else:
        command.extend(agent_command)
    return command


def build_launch_command(spec: RunSpec) -> list[str]:
    agent_command = build_agent_command(spec)
    if spec.runtime == "docker":
        return _docker_launch_command(spec, agent_command)
    return _local_launch_command(spec, agent_command)


def render_summary(spec: RunSpec, command: Iterable[str]) -> str:
    width = console_width()
    rows = (
        ("Task ID", spec.task.task_id),
        ("Task path", str(spec.task.path)),
        ("Task profile", f"{spec.task.task_type} · top={spec.task.top} · cosim={spec.task.requires_cosim}"),
        (
            "Runtime",
            (
                f"docker · image={spec.image}"
                if spec.runtime == "docker"
                else (
                    f"docker (current container) · image={spec.image}"
                    if spec.runtime == "container"
                    else "local (explicit override)"
                )
            ),
        ),
        ("Run", f"mode={spec.mode} · backend={spec.backend} · model={spec.model or '(environment default)'}"),
        ("Budget", f"{spec.budget or spec.task.budget or 'task default'} credits"),
        ("Output", str(spec.output_root)),
        ("Terminal log", str(spec.log_file)),
        ("Env file", str(spec.env_file) if spec.env_file else "(none)"),
        ("Vitis", str(spec.vitis_settings) if spec.vitis_settings else "(current environment)"),
    )
    title = " FPT26 · TASK RUNNER "
    lines = ["╭" + title + "─" * max(width - len(title) - 2, 0) + "╮"]

    def append_row(label: str, value: str) -> None:
        label_width = 14
        available = max(width - 6 - label_width, 24)
        chunks = textwrap.wrap(
            value,
            width=available,
            break_long_words=True,
            break_on_hyphens=False,
        ) or [""]
        for index, chunk in enumerate(chunks):
            prefix = f"{label:<{label_width}}" if index == 0 else " " * label_width
            body = prefix + chunk
            lines.append("│ " + body.ljust(width - 4) + " │")

    for label, value in rows:
        append_row(label, value)
    lines.append("├" + "─" * (width - 2) + "┤")
    append_row("Command", shlex.join(command))
    lines.append("╰" + "─" * (width - 2) + "╯")
    return "\n".join(lines)


def _print_task_list(task_root: Path, filter_text: str) -> int:
    needle = filter_text.lower().strip()
    tasks = [
        task
        for task in discover_tasks(task_root)
        if not needle
        or needle in task.task_id.lower()
        or needle in str(task.path).lower()
    ]
    print(f"{'TASK ID':<72} {'TYPE':<14} PATH")
    for task in tasks:
        print(f"{task.task_id:<72} {task.task_type:<14} {task.path}")
    print(f"\n{len(tasks)} task(s)")
    return 0


def _run_doctor(args: argparse.Namespace) -> int:
    checks: list[tuple[str, str, str]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append((name, "PASS" if ok else "FAIL", detail))

    in_container = os.environ.get("FPT26_CLI_IN_CONTAINER") == "1"
    check(
        "Runtime",
        in_container or args.runtime == "local",
        "Docker container" if in_container else f"{args.runtime} launcher",
    )
    py_ok = sys.version_info >= (3, 10)
    check("Python", py_ok, platform.python_version())
    machine = platform.machine().lower()
    check("Architecture", machine in {"x86_64", "amd64"}, machine)
    check("Task repository", args.task_root.is_dir(), str(args.task_root))
    check("Run output", os.access(_repo_root(), os.W_OK), str(_repo_root() / "runs"))

    runtime = "container" if in_container else args.runtime
    vitis: Path | None = None
    try:
        vitis = _auto_vitis_settings(args.vitis_settings, runtime=runtime)
    except CliError as exc:
        checks.append(("Vitis settings", "FAIL", str(exc)))
    if vitis is None:
        checks.append(("Vitis settings", "FAIL", "Vitis 2025.2 settings64.sh not found"))
    else:
        check("Vitis settings", True, str(vitis))
        probe_env = dict(os.environ)
        probe_env.pop("MATLABPATH", None)
        try:
            probe = subprocess.run(
                [
                    "bash",
                    "-lc",
                    'set -eo pipefail; source "$1"; command -v vitis-run >/dev/null',
                    "fpt26-doctor",
                    str(vitis),
                ],
                env=probe_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                check=False,
            )
            probe_error = strip_ansi(probe.stderr).strip().splitlines()
            check(
                "Vitis launcher",
                probe.returncode == 0,
                "vitis-run available"
                if probe.returncode == 0
                else (
                    probe_error[-1]
                    if probe_error
                    else f"vitis-run probe exited {probe.returncode}"
                ),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            check("Vitis launcher", False, f"{type(exc).__name__}: {exc}")

    env_file = _default_env_file(args)
    env_values = _load_env_file(env_file)
    check(
        "Environment file",
        True,
        str(env_file) if env_file else "not used; process environment only",
    )
    backend = args.backend or "openrouter"
    if backend == "scripted":
        check("LLM backend", True, "scripted (offline)")
    else:
        api_configured = bool(
            os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("FPT26_LLM_API_KEY")
            or env_values.get("OPENROUTER_API_KEY")
            or env_values.get("FPT26_LLM_API_KEY")
        )
        check("LLM credentials", api_configured, f"{backend} key configured")

    print("FPT26 environment doctor")
    for name, status, detail in checks:
        print(f"  {status:<4}  {name:<18} {detail}")
    failures = [name for name, status, _ in checks if status == "FAIL"]
    if failures:
        print(f"\nDoctor found {len(failures)} blocking issue(s).")
        return 2
    print("\nEnvironment is ready.")
    return 0


def execute(
    spec: RunSpec,
    *,
    dry_run: bool = False,
    show_summary: bool = True,
) -> int:
    launch_command = build_launch_command(spec)
    summary = render_summary(spec, launch_command)
    if show_summary:
        print(paint(summary, "\x1b[36m"))
    if dry_run:
        print("\nDRY RUN — no task was executed and no run files were created.")
        return 0

    spec.output_root.parent.mkdir(parents=True, exist_ok=True)
    spec.log_file.parent.mkdir(parents=True, exist_ok=True)
    env = (
        dict(os.environ)
        if spec.runtime == "docker"
        else build_child_environment(spec)
    )
    with spec.log_file.open("w", encoding="utf-8") as log:
        log.write(strip_ansi(summary) + "\n\n")
        log.flush()
        process = subprocess.Popen(
            launch_command,
            cwd=_repo_root(),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            errors="replace",
        )
        assert process.stdout is not None
        try:
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(strip_ansi(line))
                log.flush()
        except KeyboardInterrupt:
            process.terminate()
            print("\nInterrupted; child process terminated.", file=sys.stderr)
            return 130
        return process.wait()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    configure(args.color)
    try:
        if args.doctor:
            return _run_doctor(args)
        if args.list_tasks is not None:
            return _print_task_list(args.task_root, args.list_tasks)
        spec = build_run_spec(args)
        if args.interactive:
            command = build_launch_command(spec)
            print(render_summary(spec, command))
            if not args.yes and not args.dry_run:
                answer = _ask("Start run?", "N").lower()
                if answer not in {"y", "yes"}:
                    print("Cancelled.")
                    return 0
            if args.dry_run:
                print("\nDRY RUN — no task was executed and no run files were created.")
                return 0
            return execute(spec, show_summary=False)
        return execute(spec, dry_run=args.dry_run)
    except (CliError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
