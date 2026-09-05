#!/usr/bin/env python3
"""Run a single Vitis HLS operation (csim / synth / cosim) on a single task.

Reuses the metered harness tools from llm4hls.tools unchanged, so results
match what the agent/grading pipeline sees (same tcl, same part/clock, same
report parsing).  Intended to run INSIDE the fpt26-agent-v3 container (see
tools/vitis_task.sh for the one-command docker wrapper):

    tools/vitis_task.sh tasks/official/dotProduct_optimize csim
    tools/vitis_task.sh tasks/official/dotProduct_optimize synth
    tools/vitis_task.sh tasks/official/dotProduct_optimize cosim

The task directory is read-only here: sources are copied into a build dir
under work/vitis_task/<task_id>/<op> (wiped on re-run), which also holds the
full tool log (run.log) and, for synth/cosim, the parsed reports.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from agent.testbench import normalize_task_testbench_data
from llm4hls.task import load_task
from llm4hls.tools import CSimTool, CoSimTool, SynthTool

OPS = ("csim", "synth", "cosim")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="vitis_task.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("task", type=Path, help="Path to a task directory")
    parser.add_argument(
        "op",
        choices=OPS,
        help="Which Vitis operation to run (one per invocation)",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        help=(
            "Build directory (wiped if it exists). "
            "Default: work/vitis_task/<task_id>/<op>"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    task_dir = args.task.resolve()
    if not task_dir.is_dir():
        print(f"vitis_task: task dir does not exist: {task_dir}", file=sys.stderr)
        return 2

    task = load_task(task_dir)
    normalize_task_testbench_data(task)
    files = task.assemble(task.kernel_code, task.public_tb_code, task.public_tb_name)

    build_dir = args.build_dir or (
        Path.cwd() / "work" / "vitis_task" / task_dir.name / args.op
    )
    build_dir = build_dir.resolve()
    if build_dir.exists():
        import shutil

        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    print(
        f"vitis_task: {args.op} on {task_dir.name} "
        f"(top={task.top}, part={task.part}, clock={task.clock_ns}ns)",
        flush=True,
    )
    print(f"vitis_task: build dir {build_dir}", flush=True)

    if args.op == "csim":
        result = CSimTool().run(
            build_dir,
            files,
            task.top,
            task.part,
            task.clock_ns,
            data_files=getattr(task, "data_files", None),
        )
    elif args.op == "synth":
        result = SynthTool().run(
            build_dir, files, [task.kernel_name], task.top, task.part, task.clock_ns
        )
    else:  # cosim
        result = CoSimTool().run(
            build_dir,
            files,
            [task.kernel_name],
            [task.public_tb_name],
            task.top,
            task.part,
            task.clock_ns,
        )

    log_fp = build_dir / "run.log"
    log_fp.write_text(result.log, encoding="utf-8")
    print(f"vitis_task: full log -> {log_fp}", flush=True)
    print(f"vitis_task: {result.brief()}", flush=True)
    print(f"vitis_task: wall {time.monotonic() - t0:.1f}s", flush=True)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
