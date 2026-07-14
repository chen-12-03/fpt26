#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from llm4hls.budget import Budget
from llm4hls.harness import ToolServer
from llm4hls.task import load_task

from agent.competition_agent import AgentRunResult, CompetitionAgent
from agent.config import (
    EXIT_BASELINE_CORRECTNESS_FAILURE,
    EXIT_BUDGET_EXCEEDED,
    EXIT_INPUT_OR_CONFIG_ERROR,
    EXIT_LLM_ERROR,
    EXIT_SAFE_FALLBACK,
    EXIT_SUCCESS,
    EXIT_TOOL_ERROR,
    SUPPORTED_MODES,
    AgentCLIConfig,
    AgentConfigError,
    config_from_args,
    mode_flags,
)
from agent.input.task_adapter import TaskAdapter
from agent.llm.config import LLMConfigError
from agent.llm.llm_client import LLMClient
from agent.reporting.console_report import render_console_report
from agent.reporting.run_report import attach_report_to_manifest, write_experimental_report
from agent.reporting.score_report import Scorer, run_official_scoring


TaskLoader = Callable[[str | Path], Any]
BudgetFactory = Callable[[int], Any]
ToolServerFactory = Callable[[Any, Any, Path], Any]
LLMClientFactory = Callable[[], LLMClient]


@dataclass(frozen=True)
class AgentExecution:
    result: AgentRunResult
    scoring: dict[str, Any] | None
    report: dict[str, Any]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the FPT26 Track-A agent on an official task package.")
    parser.add_argument("--task", required=True, type=Path, help="Official task directory.")
    parser.add_argument("--mode", required=True, choices=sorted(SUPPORTED_MODES), help="Agent mode.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Root directory for persisted Agent run artifacts. Defaults to FPT26_RUN_OUTPUT_ROOT or fpt26-agent/runs/cli.",
    )
    parser.add_argument(
        "--tool-run-root",
        type=Path,
        default=None,
        help="Optional official ToolServer run root. Defaults to a unique directory under output root.",
    )
    parser.add_argument("--max-repair-attempts", type=int, default=None, help="Override FPT26_MAX_REPAIR_ATTEMPTS.")
    parser.add_argument(
        "--max-structural-repair-attempts",
        type=int,
        default=None,
        help="Override FPT26_MAX_STRUCTURAL_REPAIR_ATTEMPTS.",
    )
    parser.add_argument(
        "--max-optimization-candidates",
        type=int,
        default=None,
        help="Override FPT26_MAX_OPTIMIZATION_CANDIDATES.",
    )
    parser.add_argument(
        "--summary-format",
        choices=["json", "text", "both"],
        default="json",
        help="Output format for the final run summary. Default: json.",
    )
    parser.add_argument(
        "--score",
        action="store_true",
        help="Run official hidden-testbench scoring after the Agent finishes and persist scorecard artifacts.",
    )
    return parser.parse_args(argv)


def run_agent(
    *,
    task_path: Path,
    mode: str,
    output_root: Path | None = None,
    tool_run_root: Path | None = None,
    max_repair_attempts: int | None = None,
    max_structural_repair_attempts: int | None = None,
    max_optimization_candidates: int | None = None,
    summary_format: str = "json",
    score: bool = False,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    task_loader: TaskLoader = load_task,
    budget_factory: BudgetFactory = Budget,
    tool_server_factory: ToolServerFactory = ToolServer,
    llm_client_factory: LLMClientFactory = LLMClient,
    backend_factory: Any = None,
    scorer: Scorer | None = None,
) -> int:
    args = argparse.Namespace(
        task=task_path,
        mode=mode,
        output_root=output_root,
        tool_run_root=tool_run_root,
        max_repair_attempts=max_repair_attempts,
        max_structural_repair_attempts=max_structural_repair_attempts,
        max_optimization_candidates=max_optimization_candidates,
        summary_format=summary_format,
        score=score,
    )
    try:
        config = config_from_args(args)
        execution = _run_config(
            config,
            stdout=stdout,
            task_loader=task_loader,
            budget_factory=budget_factory,
            tool_server_factory=tool_server_factory,
            llm_client_factory=llm_client_factory,
            backend_factory=backend_factory,
            scorer=scorer,
        )
    except (AgentConfigError, LLMConfigError, FileNotFoundError, NotADirectoryError, ValueError, KeyError) as exc:
        print(f"error: {_redact_secrets(str(exc))}", file=stderr)
        return EXIT_INPUT_OR_CONFIG_ERROR
    except Exception as exc:
        print(f"error: {_redact_secrets(type(exc).__name__ + ': ' + str(exc))}", file=stderr)
        return EXIT_TOOL_ERROR

    result = execution.result
    summary = result_summary(result, config.mode, scoring=execution.scoring, report=execution.report)
    if config.summary_format in {"text", "both"}:
        print(render_console_report(result, config.mode, scoring=execution.scoring, report=execution.report), file=stdout)
    if config.summary_format == "both":
        print("--- json summary ---", file=stdout)
    if config.summary_format in {"json", "both"}:
        print(json.dumps(summary, sort_keys=True, ensure_ascii=False), file=stdout)
    return exit_code_for_result(result, config.mode)


def _run_config(
    config: AgentCLIConfig,
    *,
    stdout: TextIO,
    task_loader: TaskLoader,
    budget_factory: BudgetFactory,
    tool_server_factory: ToolServerFactory,
    llm_client_factory: LLMClientFactory,
    backend_factory: Any,
    scorer: Scorer | None,
) -> AgentExecution:
    del stdout
    task_dir = config.task_path.resolve()
    if not task_dir.is_dir():
        raise NotADirectoryError(f"task directory does not exist: {task_dir}")
    task = task_loader(task_dir)
    task_context = TaskAdapter.from_official_task(task)
    flags = mode_flags(config.mode, task_context.task_type)
    llm_client = llm_client_factory() if flags.needs_llm else None
    run_root = _tool_run_root(config, task_context.task_id)
    _validate_tool_run_root(run_root)
    tool_server = tool_server_factory(task, budget_factory(task.budget), run_root)

    agent_kwargs: dict[str, Any] = {
        "llm_client": llm_client,
        "repair_enabled": flags.repair_enabled,
        "optimize_enabled": flags.optimize_enabled,
        "structural_repair_enabled": flags.structural_repair_enabled,
        "max_repair_attempts": config.max_repair_attempts,
        "max_structural_repair_attempts": config.max_structural_repair_attempts,
        "max_optimization_candidates": config.max_optimization_candidates,
    }
    if backend_factory is not None:
        agent_kwargs["backend_factory"] = backend_factory
    agent = CompetitionAgent(**agent_kwargs)
    result = agent.run(task, tool_server, output_root=config.output_root)
    scoring = None
    if config.score:
        if result.run_directory is None:
            raise ValueError("run_directory is required before scoring")
        if scorer is None:
            scoring = run_official_scoring(task, result.final_kernel, result.run_directory)
        else:
            scoring = run_official_scoring(task, result.final_kernel, result.run_directory, scorer=scorer)
    report = write_experimental_report(result, mode=config.mode, scoring=scoring)
    attach_report_to_manifest(result, report, scoring=scoring)
    return AgentExecution(result=result, scoring=scoring, report=report)


def _tool_run_root(config: AgentCLIConfig, task_id: str) -> Path:
    if config.tool_run_root is not None:
        return config.tool_run_root.resolve()
    unique = uuid.uuid4().hex[:12]
    return (config.output_root / "_toolserver" / task_id / f"tools_{unique}").resolve()


def _validate_tool_run_root(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"tool run root already exists and is not empty: {path}")


def result_summary(
    result: AgentRunResult,
    mode: str,
    scoring: dict[str, Any] | None = None,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = {
        "task_id": result.task_id,
        "mode": mode,
        "status": result.status,
        "initial_condition": result.initial_condition.to_dict(),
        "selected_candidate_id": result.selected_candidate_id,
        "final_kernel_sha256": result.final_kernel_sha256,
        "stage_statuses": [
            {
                "stage": stage.stage,
                "status": stage.status,
                "summary": stage.summary,
                "budget_before": stage.budget_before,
                "budget_after": stage.budget_after,
            }
            for stage in result.stage_results
        ],
        "repair_status": result.repair_status,
        "optimization_status": result.optimization_status,
        "structural_repair_status": result.structural_repair_status,
        "hls_budget": result.budget,
        "llm_usage": result.llm_usage,
        "model_repair_failed": _model_repair_failed(result),
        "run_directory": result.run_directory,
        "run_manifest_path": result.run_manifest_path,
        "report": _report_summary(report),
        "scoring": scoring,
        "stop_reason": result.stop_reason,
    }
    return summary


def _report_summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    paths = report.get("paths") if isinstance(report.get("paths"), dict) else {}
    return {
        "report_json": paths.get("report_json"),
        "report_txt": paths.get("report_txt"),
        "verification": report.get("verification"),
        "ppa": report.get("ppa"),
    }


def exit_code_for_result(result: AgentRunResult, mode: str) -> int:
    if _has_llm_error(result):
        return EXIT_LLM_ERROR
    if result.status == "budget_exceeded" or _has_stage_status(result, {"budget_exceeded"}):
        return EXIT_BUDGET_EXCEEDED
    if result.status in {"timeout", "exception"} or _has_stage_status(result, {"timeout", "exception"}):
        return EXIT_TOOL_ERROR

    if result.status == "completed":
        if mode == "optimize" and result.optimization_status not in {"improved", "not_attempted"}:
            return EXIT_SAFE_FALLBACK
        return EXIT_SUCCESS

    if mode == "baseline":
        return EXIT_BASELINE_CORRECTNESS_FAILURE
    if result.status in {"repair_failed", "structural_repair_failed"}:
        return EXIT_SAFE_FALLBACK
    if result.optimization_status not in {"not_attempted", "improved"}:
        return EXIT_SAFE_FALLBACK
    condition = result.initial_condition.condition
    if condition in {"compile_failure", "csim_failure", "synth_failure", "cosim_failure", "structural_failure"}:
        return EXIT_BASELINE_CORRECTNESS_FAILURE
    return EXIT_TOOL_ERROR


def _has_llm_error(result: AgentRunResult) -> bool:
    for attempt in result.repair_attempts:
        if attempt.status == "llm_error":
            return True
    for attempt in result.structural_repair_attempts:
        if attempt.status == "llm_error":
            return True
    return False


def _model_repair_failed(result: AgentRunResult) -> bool:
    return (
        result.repair_status == "failed"
        and bool(result.repair_attempts)
        and any(attempt.llm_response.status == "ok" for attempt in result.repair_attempts)
    )


def _has_stage_status(result: AgentRunResult, statuses: set[str]) -> bool:
    return any(stage.status in statuses for stage in result.stage_results)


def _redact_secrets(text: str) -> str:
    redacted = text
    for name in ("FPT26_LLM_API_KEY", "LLM_API_KEY"):
        value = os.environ.get(name)
        if value:
            redacted = redacted.replace(value, "[redacted]")
    return redacted


def main(argv: list[str] | None = None, *, stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_INPUT_OR_CONFIG_ERROR
    return run_agent(
        task_path=args.task,
        mode=args.mode,
        output_root=args.output_root,
        tool_run_root=args.tool_run_root,
        max_repair_attempts=args.max_repair_attempts,
        max_structural_repair_attempts=args.max_structural_repair_attempts,
        max_optimization_candidates=args.max_optimization_candidates,
        summary_format=args.summary_format,
        score=args.score,
        stdout=stdout,
        stderr=stderr,
    )


if __name__ == "__main__":
    sys.exit(main())
