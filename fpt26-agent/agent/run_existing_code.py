#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, TextIO

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.ir import HLSIR, HLSIRValidationError, load_ir


AGENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNNER = AGENT_ROOT / "harness" / "wrapper" / "run-hls-in-docker.sh"
DEFAULT_CANDIDATE_PREFIX = "existing_code"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an existing-code HLS IR through the first-stage HLS runner."
    )
    parser.add_argument("ir_json", type=Path, help="Path to an existing_code HLS IR JSON file.")
    parser.add_argument(
        "--candidate-prefix",
        default=DEFAULT_CANDIDATE_PREFIX,
        help=f"Candidate prefix passed to the HLS runner. Defaults to {DEFAULT_CANDIDATE_PREFIX!r}.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=_timeout_from_env(),
        help="Optional timeout for the underlying HLS runner subprocess.",
    )
    return parser.parse_args(argv)


def run_existing_code(
    ir_path: Path,
    *,
    runner_path: Path = DEFAULT_RUNNER,
    candidate_prefix: str = DEFAULT_CANDIDATE_PREFIX,
    timeout_seconds: float | None = None,
    agent_root: Path = AGENT_ROOT,
    manifest_metadata: dict[str, Any] | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    try:
        ir = load_ir(ir_path)
        _validate_existing_code_ir(ir, agent_root)
    except HLSIRValidationError as exc:
        print(f"error: invalid IR: {exc}", file=stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=stderr)
        return 2

    if not candidate_prefix.strip():
        print("error: candidate prefix must be a non-empty string", file=stderr)
        return 2
    if not runner_path.is_file():
        print(f"error: HLS runner does not exist: {runner_path}", file=stderr)
        return 2

    command = [
        str(runner_path),
        "--task-id",
        ir.task_id,
        "--candidate-prefix",
        candidate_prefix,
        "--top",
        ir.top_function,
        "--source",
        _required_path(ir.source_file, "source_file"),
        "--testbench",
        _required_path(ir.testbench_file, "testbench_file"),
        "--clock-period",
        str(ir.clock_period_ns),
        "--hls-part",
        ir.hls_part,
    ]

    try:
        result = subprocess.run(
            command,
            cwd=agent_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        if exc.stdout:
            print(exc.stdout, end="", file=stdout)
        if exc.stderr:
            print(exc.stderr, end="", file=stderr)
        print(f"error: HLS runner timed out after {timeout_seconds} seconds", file=stderr)
        return 124

    stdout.write(result.stdout)
    stderr.write(result.stderr)
    if manifest_metadata is not None:
        metadata_exit_code = _update_manifest_metadata(
            result.stdout,
            ir=ir,
            ir_path=ir_path,
            metadata=manifest_metadata,
            stderr=stderr,
        )
        if metadata_exit_code != 0 and result.returncode == 0:
            return metadata_exit_code
    return result.returncode


def _validate_existing_code_ir(ir: HLSIR, agent_root: Path) -> None:
    if ir.input_mode != "existing_code":
        raise HLSIRValidationError(
            [f"input_mode must be 'existing_code' for this entrypoint, got {ir.input_mode!r}"]
        )

    source_path = _resolve_repo_path(agent_root, _required_path(ir.source_file, "source_file"))
    testbench_path = _resolve_repo_path(agent_root, _required_path(ir.testbench_file, "testbench_file"))
    missing: list[str] = []
    if not source_path.is_file():
        missing.append(f"source file does not exist: {source_path}")
    if not testbench_path.is_file():
        missing.append(f"testbench file does not exist: {testbench_path}")
    if missing:
        raise FileNotFoundError("; ".join(missing))


def _required_path(value: str | None, field: str) -> str:
    if value is None:
        raise HLSIRValidationError([f"{field} is required"])
    return value


def _resolve_repo_path(agent_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return agent_root / path


def _update_manifest_metadata(
    runner_stdout: str,
    *,
    ir: HLSIR,
    ir_path: Path,
    metadata: dict[str, Any],
    stderr: TextIO,
) -> int:
    run_dir = _discover_run_dir(runner_stdout)
    if run_dir is None:
        print("error: HLS runner output did not include run_dir; cannot update manifest", file=stderr)
        return 1

    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        print(f"error: manifest.json was not found: {manifest_path}", file=stderr)
        return 1

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"error: cannot read manifest.json for metadata update: {exc}", file=stderr)
        return 1
    if not isinstance(manifest, dict):
        print(f"error: manifest.json root must be an object: {manifest_path}", file=stderr)
        return 1

    mode = metadata.get("mode")
    input_type = metadata.get("input_type")
    llm_called = bool(metadata.get("llm_called", False))

    manifest["mode"] = mode
    manifest["input_type"] = input_type
    manifest["input_ir"] = str(ir_path.resolve())
    manifest["input_ir_source_file"] = _required_path(ir.source_file, "source_file")
    manifest["input_ir_testbench_file"] = _required_path(ir.testbench_file, "testbench_file")
    manifest["llm"] = {"called": llm_called}
    agent_metadata = {
        "mode": mode,
        "input_type": input_type,
        "input_ir": str(ir_path.resolve()),
        "source_file": _required_path(ir.source_file, "source_file"),
        "testbench_file": _required_path(ir.testbench_file, "testbench_file"),
        "llm": {"called": llm_called},
    }
    for key, value in metadata.items():
        if key not in {"mode", "input_type", "llm_called"}:
            agent_metadata[key] = value
    manifest["agent"] = agent_metadata

    try:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write manifest metadata: {exc}", file=stderr)
        return 1
    return 0


def _discover_run_dir(runner_stdout: str) -> Path | None:
    return discover_run_dir_from_stdout(runner_stdout)


def discover_run_dir_from_stdout(runner_stdout: str) -> Path | None:
    prefix = "wrapper: run_dir="
    for line in runner_stdout.splitlines():
        if line.startswith(prefix):
            value = line[len(prefix) :].strip()
            if value:
                return Path(value)
    return None


def _timeout_from_env() -> float | None:
    value = os.environ.get("AGENT_RUN_TIMEOUT_SECONDS")
    if not value:
        return None
    try:
        timeout = float(value)
    except ValueError:
        return None
    return timeout if timeout > 0 else None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return run_existing_code(
        args.ir_json,
        candidate_prefix=args.candidate_prefix,
        timeout_seconds=args.timeout_seconds,
    )


if __name__ == "__main__":
    sys.exit(main())
