#!/usr/bin/env python3
"""CLI entry point for the fpt26-agent-v2 pipeline.

Usage::

    python -m agent.main --task tasks/projection_bugfix --mode baseline
    python -m agent.main --task tasks/dotProduct_optimize --mode full
    python -m agent.main --task tasks/residual_stream_deadlock --mode full --competition
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from llm4hls.budget import Budget
from llm4hls.harness import ToolServer
from llm4hls.task import load_task

from agent.agents.base import RunState
from agent.backends import create_llm
from agent.workflow import build_pipeline


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="FPT26 Track-A agent v2 — pipeline-based LLM4HLS agent"
    )
    p.add_argument("--task", required=True, type=Path, help="Path to official task directory")
    p.add_argument(
        "--mode", required=True,
        choices=["baseline", "repair", "optimize", "structural", "full"],
        help="Agent operating mode",
    )
    p.add_argument("--output-root", type=Path, default=None, help="Run artifact output root")
    p.add_argument("--budget", type=int, default=None, help="Override task credit budget")
    p.add_argument(
        "--backend", choices=["auto", "openrouter", "custom", "scripted"],
        default="auto", help="LLM backend selection (default: auto-detect)",
    )
    p.add_argument("--competition", action="store_true", help="Use parallel agent competition within stages")
    p.add_argument("--max-repair-attempts", type=int, default=None)
    p.add_argument("--max-optimization-rounds", type=int, default=None)
    p.add_argument("--max-structural-attempts", type=int, default=None)
    p.add_argument("--no-score", action="store_true", help="Skip hidden-testbench scoring")
    p.add_argument("--quiet", action="store_true", help="Suppress step-by-step log output")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # 1. Load task -----------------------------------------------------------
    task_dir = args.task.resolve()
    if not task_dir.is_dir():
        print(f"error: task directory not found: {task_dir}", file=sys.stderr)
        return 2
    task = load_task(str(task_dir))

    # 2. Budget & ToolServer -------------------------------------------------
    total_budget = args.budget if args.budget is not None else task.budget
    budget = Budget(total=total_budget)
    output_root = str(args.output_root or os.environ.get("FPT26_RUN_OUTPUT_ROOT", "runs"))
    run_root = Path(output_root) / task.id / "agent"
    server = ToolServer(task, budget, run_root)

    # 3. LLM client (only if mode requires it) --------------------------------
    llm = None
    modes_needing_llm = {"repair", "optimize", "structural", "full"}
    if args.mode in modes_needing_llm:
        try:
            llm = create_llm(args.backend)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 7

    # 4. Build config ---------------------------------------------------------
    from agent.agents.base import AgentConfig

    config = AgentConfig(
        mode=args.mode,
        competition=args.competition,
        output_root=output_root,
        score=not args.no_score,
        verbose=not args.quiet,
        max_repair_attempts=args.max_repair_attempts or _env_int("FPT26_MAX_REPAIR_ATTEMPTS", 3),
        max_optimization_rounds=args.max_optimization_rounds or _env_int("FPT26_MAX_OPTIMIZATION_CANDIDATES", 5),
        max_structural_attempts=args.max_structural_attempts or _env_int("FPT26_MAX_STRUCTURAL_REPAIR_ATTEMPTS", 3),
    )

    # 5. Build and run pipeline ----------------------------------------------
    pipeline = build_pipeline(config=config, task=task, server=server, llm=llm)

    state = RunState(
        task=task,
        server=server,
        llm=llm,
        config=config,
        kernel=task.kernel_code,
    )

    final_state = pipeline.run(state)

    # 5. Persist run report --------------------------------------------------
    from agent.reporting import print_evaluation, write_run_report

    report_path = write_run_report(final_state)
    print(f"Run report written to {report_path}")
    print_evaluation(final_state)

    # 6. Print results -------------------------------------------------------
    print(f"\n=== Agent run complete: {final_state.status} ===")
    print(f"Transcript ({len(server.transcript)} tool calls):")
    for entry in server.transcript:
        print(f"  #{entry.n:<2} {entry.detail}   [spent {entry.spent}/{total_budget}]")
    print(f"  {budget.summary()}")

    if final_state.scorecard is not None:
        print(f"\n{final_state.scorecard.render()}")

    if final_state.status == "completed":
        return 0
    if final_state.status == "budget_exceeded":
        return 5
    return 4


if __name__ == "__main__":
    sys.exit(main())
