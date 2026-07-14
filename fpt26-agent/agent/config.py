from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


SUPPORTED_MODES = {"baseline", "repair", "optimize", "structural", "full"}

EXIT_SUCCESS = 0
EXIT_INPUT_OR_CONFIG_ERROR = 2
EXIT_BASELINE_CORRECTNESS_FAILURE = 3
EXIT_SAFE_FALLBACK = 4
EXIT_BUDGET_EXCEEDED = 5
EXIT_TOOL_ERROR = 6
EXIT_LLM_ERROR = 7

DEFAULT_OUTPUT_ROOT = Path("fpt26-agent/runs/cli")
DEFAULT_MAX_REPAIR_ATTEMPTS = 2
DEFAULT_MAX_STRUCTURAL_REPAIR_ATTEMPTS = 2
DEFAULT_MAX_OPTIMIZATION_CANDIDATES = 3


class AgentConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AgentCLIConfig:
    task_path: Path
    mode: str
    output_root: Path
    tool_run_root: Path | None
    summary_format: str
    score: bool
    max_repair_attempts: int
    max_structural_repair_attempts: int
    max_optimization_candidates: int


@dataclass(frozen=True)
class ModeFlags:
    repair_enabled: bool
    optimize_enabled: bool
    structural_repair_enabled: bool

    @property
    def needs_llm(self) -> bool:
        return self.repair_enabled or self.structural_repair_enabled


def config_from_args(args: object, env: Mapping[str, str] | None = None) -> AgentCLIConfig:
    source = os.environ if env is None else env
    task_path = Path(getattr(args, "task"))
    mode = str(getattr(args, "mode"))
    if mode not in SUPPORTED_MODES:
        raise AgentConfigError(f"unsupported mode: {mode}")

    output_arg = getattr(args, "output_root", None)
    output_root = Path(output_arg) if output_arg is not None else Path(source.get("FPT26_RUN_OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT))
    tool_arg = getattr(args, "tool_run_root", None)
    tool_run_root = Path(tool_arg) if tool_arg is not None else None
    summary_format = str(getattr(args, "summary_format", "json"))
    if summary_format not in {"json", "text", "both"}:
        raise AgentConfigError("summary format must be one of: json, text, both")

    return AgentCLIConfig(
        task_path=task_path,
        mode=mode,
        output_root=output_root,
        tool_run_root=tool_run_root,
        summary_format=summary_format,
        score=bool(getattr(args, "score", False)),
        max_repair_attempts=_positive_int_arg_or_env(
            getattr(args, "max_repair_attempts", None),
            source,
            "FPT26_MAX_REPAIR_ATTEMPTS",
            DEFAULT_MAX_REPAIR_ATTEMPTS,
        ),
        max_structural_repair_attempts=_positive_int_arg_or_env(
            getattr(args, "max_structural_repair_attempts", None),
            source,
            "FPT26_MAX_STRUCTURAL_REPAIR_ATTEMPTS",
            DEFAULT_MAX_STRUCTURAL_REPAIR_ATTEMPTS,
        ),
        max_optimization_candidates=_positive_int_arg_or_env(
            getattr(args, "max_optimization_candidates", None),
            source,
            "FPT26_MAX_OPTIMIZATION_CANDIDATES",
            DEFAULT_MAX_OPTIMIZATION_CANDIDATES,
        ),
    )


def mode_flags(mode: str, task_type: str) -> ModeFlags:
    if mode == "baseline":
        return ModeFlags(False, False, False)
    if mode == "repair":
        return ModeFlags(True, False, False)
    if mode == "optimize":
        return ModeFlags(False, True, False)
    if mode == "structural":
        return ModeFlags(False, False, True)
    if mode == "full":
        normalized = task_type.strip().lower()
        return ModeFlags(
            repair_enabled=normalized in {"repair", "generate", "synth_fix", "unknown", "mixed"},
            optimize_enabled=normalized in {"optimize", "mixed"},
            structural_repair_enabled=normalized in {"structural", "mixed"},
        )
    raise AgentConfigError(f"unsupported mode: {mode}")


def _positive_int_arg_or_env(
    arg_value: object,
    env: Mapping[str, str],
    env_name: str,
    default: int,
) -> int:
    if arg_value is not None:
        return _positive_int(str(arg_value), f"--{env_name.lower().removeprefix('fpt26_').replace('_', '-')}")
    raw = env.get(env_name)
    if raw is None or raw == "":
        return default
    return _positive_int(raw, env_name)


def _positive_int(raw: str, name: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise AgentConfigError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise AgentConfigError(f"{name} must be a positive integer")
    return value
