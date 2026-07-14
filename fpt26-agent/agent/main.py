#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TextIO

from agent.natural_language_flow import run_natural_language_baseline
from agent.run_existing_code import DEFAULT_RUNNER, run_existing_code


SUPPORTED_INPUT_TYPES = {"ir", "natural-language"}
SUPPORTED_MODES = {"baseline", "replay"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the FPT26 Track-A HLS agent.")
    parser.add_argument("--input", required=True, type=Path, help="Input artifact path.")
    parser.add_argument(
        "--input-type",
        required=True,
        choices=sorted(SUPPORTED_INPUT_TYPES),
        help="Input type. Supports 'ir' and 'natural-language'.",
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=sorted(SUPPORTED_MODES),
        help="Execution mode. Currently supports 'baseline' and 'replay'.",
    )
    return parser.parse_args(argv)


def run_agent(
    input_path: Path,
    *,
    input_type: str,
    mode: str,
    runner_path: Path = DEFAULT_RUNNER,
    agent_work_root: Path | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    if input_type not in SUPPORTED_INPUT_TYPES:
        print(f"error: unsupported input type: {input_type}", file=stderr)
        return 2
    if mode not in SUPPORTED_MODES:
        print(f"error: unsupported mode: {mode}", file=stderr)
        return 2

    if input_type == "natural-language":
        if mode != "baseline":
            print("error: natural-language input currently supports only baseline mode", file=stderr)
            return 2
        result = run_natural_language_baseline(
            input_path,
            runner_path=runner_path,
            work_root=agent_work_root,
            stdout=stdout,
            stderr=stderr,
        )
        return result.exit_code

    manifest_metadata = None
    if mode == "replay":
        manifest_metadata = {
            "mode": "replay",
            "input_type": input_type,
            "llm_called": False,
        }

    return run_existing_code(
        input_path,
        runner_path=runner_path,
        candidate_prefix=mode,
        manifest_metadata=manifest_metadata,
        stdout=stdout,
        stderr=stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return run_agent(args.input, input_type=args.input_type, mode=args.mode)


if __name__ == "__main__":
    sys.exit(main())
