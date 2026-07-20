"""Submission-safe task loading and deterministic package preflight.

The official ``load_task`` helper intentionally serves the evaluator and may
read ``hidden/`` and ``reference/``.  A submission agent must not even open
those paths, so this module constructs the official ``Task`` data type from
public artifacts only.
"""

from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 in the frozen competition image.
    import tomli as tomllib

from llm4hls import config
from llm4hls.task import Task

from agent.security.paths import (
    resolve_safe_path,
    validate_hls_identifier,
    validate_task_id,
)


U55C_PART = "xcu55c-fsvh2892-2L-e"
REQUIRED_VITIS_VERSION = "2025.2"


class TaskPreflightError(ValueError):
    """The public task package or target contract is invalid."""


@dataclass(frozen=True)
class TaskPreflight:
    task_id: str
    top: str
    kernel_name: str
    public_tb_name: str
    part: str
    target_clock_ns: float
    budget: int
    configured_vitis_root: str
    observed_vitis_version: str
    observed_vitis_build: str | None
    public_files_read: tuple[str, ...]
    forbidden_artifact_accesses: int = 0
    required_vitis_version: str = REQUIRED_VITIS_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "top": self.top,
            "kernel_name": self.kernel_name,
            "public_tb_name": self.public_tb_name,
            "part": self.part,
            "target_clock_ns": self.target_clock_ns,
            "budget": self.budget,
            "configured_vitis_root": self.configured_vitis_root,
            "required_vitis_version": self.required_vitis_version,
            "observed_vitis_version": self.observed_vitis_version,
            "observed_vitis_build": self.observed_vitis_build,
            "public_files_read": list(self.public_files_read),
            "forbidden_artifact_accesses": self.forbidden_artifact_accesses,
        }


def _required_public_file(root: Path, relative: str, field: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise TaskPreflightError(f"{field} must name a public task file")
    lexical = PurePosixPath(relative.replace("\\", "/"))
    if (
        lexical.is_absolute()
        or ".." in lexical.parts
        or any(part.lower() in {"hidden", "reference"} for part in lexical.parts)
    ):
        raise TaskPreflightError(
            f"{field} must not reference evaluator-owned hidden/reference artifacts"
        )
    unresolved = root / relative
    if unresolved.is_symlink():
        raise TaskPreflightError(f"{field} must not be a symbolic link")
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise TaskPreflightError(f"{field} escapes the task directory") from exc
    if not candidate.is_file():
        raise TaskPreflightError(f"missing {field}: {relative}")
    return candidate


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise TaskPreflightError(f"{field} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise TaskPreflightError(f"{field} must be a positive integer") from exc
    if parsed <= 0:
        raise TaskPreflightError(f"{field} must be a positive integer")
    return parsed


def _positive_float(value: Any, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise TaskPreflightError(f"{field} must be a positive finite number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise TaskPreflightError(f"{field} must be a positive finite number")
    return parsed


@lru_cache(maxsize=4)
def probe_vitis_environment(root_text: str) -> tuple[str, str | None]:
    """Run the configured tool to prove the actual Vitis version."""

    settings = Path(root_text) / "settings64.sh"
    try:
        completed = subprocess.run(
            [
                "/bin/bash",
                "-c",
                'source "$1" >/dev/null 2>&1 && vitis-run --version',
                "fpt26-vitis-probe",
                str(settings),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TaskPreflightError(f"unable to execute Vitis version probe: {exc}") from exc
    output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    match = re.search(r"vitis-run v(\d+\.\d+)", output)
    if completed.returncode != 0 or match is None:
        raise TaskPreflightError(
            "configured Vitis environment did not produce a valid version banner"
        )
    build_match = re.search(r"SW Build\s+(\d+)", output)
    return match.group(1), build_match.group(1) if build_match else None


def load_public_task(task_dir: str | Path) -> tuple[Task, TaskPreflight]:
    """Load only public task artifacts into the official ``Task`` type.

    This function deliberately does not probe, stat, list, or read either the
    ``hidden`` or ``reference`` directory.
    """

    root = Path(task_dir).resolve()
    if not root.is_dir():
        raise TaskPreflightError(f"task directory not found: {root}")

    toml_path = _required_public_file(root, "task.toml", "task.toml")
    try:
        spec = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise TaskPreflightError(f"invalid task.toml: {exc}") from exc

    top = spec.get("top")
    if not isinstance(top, str) or not top.strip():
        raise TaskPreflightError("top must be a non-empty function name")

    kernel_name = spec.get("kernel_file")
    kernel_path = _required_public_file(root, kernel_name, "kernel_file")

    header_names = spec.get("header_files", [])
    if not isinstance(header_names, list) or not all(
        isinstance(name, str) for name in header_names
    ):
        raise TaskPreflightError("header_files must be a list of public filenames")
    header_paths = [
        (name, _required_public_file(root, name, "header_file"))
        for name in header_names
    ]

    public_tb_name = spec.get("public_tb")
    public_tb_path = _required_public_file(root, public_tb_name, "public_tb")

    target = spec.get("target", {})
    if not isinstance(target, dict):
        raise TaskPreflightError("target must be a table")
    part = target.get("part") or config.DEFAULT_PART
    if part != U55C_PART:
        raise TaskPreflightError(
            f"Track-A requires Alveo U55C part {U55C_PART}, got {part!r}"
        )
    clock_ns = _positive_float(target.get("clock_ns", config.DEFAULT_CLOCK_NS), "clock_ns")
    budget = _positive_int(spec.get("budget", 40), "budget")

    configured_root = str(config.VITIS_HLS_ROOT)
    if REQUIRED_VITIS_VERSION not in configured_root:
        raise TaskPreflightError(
            f"configured Vitis root is not {REQUIRED_VITIS_VERSION}: {configured_root}"
        )
    if not (config.VITIS_HLS_ROOT / "settings64.sh").is_file():
        raise TaskPreflightError(
            f"Vitis settings64.sh not found under configured root: {configured_root}"
        )
    observed_version, observed_build = probe_vitis_environment(configured_root)
    if observed_version != REQUIRED_VITIS_VERSION:
        raise TaskPreflightError(
            f"Track-A requires Vitis {REQUIRED_VITIS_VERSION}, "
            f"observed {observed_version}"
        )

    description_path = root / "description.md"
    description = (
        description_path.read_text(encoding="utf-8")
        if description_path.is_file()
        else ""
    )
    headers = {
        name: path.read_text(encoding="utf-8") for name, path in header_paths
    }
    task_id = spec.get("task_id", root.name)
    if not isinstance(task_id, str) or not task_id.strip():
        raise TaskPreflightError("task_id must be a non-empty string")
    # Security: validate against the canonical task_id pattern
    validate_task_id(task_id)

    task = Task(
        dir=root,
        id=task_id,
        type=str(spec.get("task_type", "generate")),
        difficulty=_positive_int(spec.get("difficulty", 1), "difficulty"),
        top=top,
        budget=budget,
        part=part,
        clock_ns=clock_ns,
        requires_cosim=bool(spec.get("requires_cosim", False)),
        initial_condition=str(spec.get("initial_condition", "")),
        description=description,
        kernel_name=kernel_name,
        kernel_code=kernel_path.read_text(encoding="utf-8"),
        headers=headers,
        public_tb_name=public_tb_name,
        public_tb_code=public_tb_path.read_text(encoding="utf-8"),
        # Submission code receives no hidden or reference contents.
        hidden_tb_name="",
        hidden_tb_code="",
        reference_code=None,
    )
    preflight = TaskPreflight(
        task_id=task.id,
        top=task.top,
        kernel_name=task.kernel_name,
        public_tb_name=task.public_tb_name,
        part=task.part,
        target_clock_ns=task.clock_ns,
        budget=task.budget,
        configured_vitis_root=configured_root,
        observed_vitis_version=observed_version,
        observed_vitis_build=observed_build,
        public_files_read=tuple(
            sorted(
                {
                    "task.toml",
                    *(
                        ["description.md"]
                        if description_path.is_file()
                        else []
                    ),
                    kernel_name,
                    public_tb_name,
                    *header_names,
                }
            )
        ),
    )
    return task, preflight
