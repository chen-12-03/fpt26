"""Run one deterministic shard of the full real-API/Vitis task corpus.

This is an orchestration command, not a backend: every selected task is run by
the frozen ``agent.main`` CLI with ``--backend custom``.  It records launcher
return codes and then fail-closes unless a completed run report contains at
least one fully reported OpenAI-compatible API request.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


OFFICIAL_MODES = {
    "dotProduct_optimize": "optimize",
    "projection_bugfix": "repair",
    "residual_stream_deadlock": "structural",
}

EXPECTED_GENERATED_TASK_COUNT = 196
EXPECTED_OFFICIAL_TASK_COUNT = 3
EXPECTED_TASK_COUNT = EXPECTED_GENERATED_TASK_COUNT + EXPECTED_OFFICIAL_TASK_COUNT


def discover_tasks(task_root: Path) -> list[Path]:
    tasks = sorted((task_root / "generated").glob("*/task.toml"))
    tasks += sorted((task_root / "official").glob("*/task.toml"))
    task_dirs = [path.parent.resolve() for path in tasks]
    if (
        len(task_dirs) != EXPECTED_TASK_COUNT
        or len({path.name for path in task_dirs}) != EXPECTED_TASK_COUNT
    ):
        raise RuntimeError(
            f"expected {EXPECTED_TASK_COUNT} unique tasks, found {len(task_dirs)}"
        )
    return task_dirs


def mode_for(task_dir: Path) -> str:
    return OFFICIAL_MODES.get(task_dir.name, "optimize")


def _validate_report(report_path: Path) -> dict[str, Any]:
    if not report_path.is_file():
        raise RuntimeError("run_report.json missing")
    report = json.loads(report_path.read_text())
    llm = report.get("llm") or {}
    usage = llm.get("token_usage") or {}
    if report.get("status") != "completed":
        raise RuntimeError(f"status={report.get('status')}")
    if llm.get("client") != "OpenAICompatClient":
        raise RuntimeError(f"unexpected LLM client={llm.get('client')}")
    if (
        usage.get("complete") is not True
        or usage.get("request_count", 0) < 1
        or usage.get("request_count") != usage.get("response_count")
        or usage.get("failed_request_count") != 0
        or usage.get("unreported_response_count") != 0
        or usage.get("total_tokens")
        != usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
    ):
        raise RuntimeError(f"invalid real API usage={usage}")
    grading = (report.get("execution_trace") or {}).get("grading_results") or []
    required = {"hidden_csim", "candidate_synth", "starter_synth", "reference_synth"}
    if report.get("task_id") == "residual_stream_deadlock":
        required.add("hidden_cosim")
    stages = {stage.get("stage"): stage for stage in grading}
    for name in required:
        stage = stages.get(name)
        if not stage or stage.get("ok") is not True or stage.get("return_code") != 0:
            raise RuntimeError(f"required grading stage failed or missing: {name}")
    return report


def run_shard(
    task_root: Path,
    output_root: Path,
    shard_index: int,
    shard_count: int,
    timeout_s: float,
) -> dict[str, Any]:
    all_tasks = discover_tasks(task_root)
    selected = [
        task for index, task in enumerate(all_tasks)
        if index % shard_count == shard_index
    ]
    if output_root.exists():
        raise RuntimeError(f"refusing to reuse output root: {output_root}")
    output_root.mkdir(parents=True)
    summary_path = output_root / "shard_summary.json"
    records: list[dict[str, Any]] = []
    shard_started = time.monotonic()
    for ordinal, task_dir in enumerate(selected, start=1):
        mode = mode_for(task_dir)
        task_id = task_dir.name
        command = [
            sys.executable,
            "-m",
            "agent.main",
            "--task",
            str(task_dir),
            "--mode",
            mode,
            "--backend",
            "custom",
            "--output-root",
            str(output_root),
            "--quiet",
        ]
        log_path = output_root / f"launcher_{ordinal:02d}_{task_id}.log"
        started = time.monotonic()
        return_code: int | None = None
        error = ""
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_s,
                check=False,
            )
            return_code = completed.returncode
            log_path.write_text(completed.stdout)
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode(errors="replace")
            log_path.write_text(output + "\nLAUNCHER TIMEOUT\n")
            error = f"launcher_timeout_after_{timeout_s}s"

        report_path = output_root / task_id / "run_report.json"
        report: dict[str, Any] | None = None
        if not error and return_code != 0:
            error = f"agent_return_code_{return_code}"
        if not error:
            try:
                report = _validate_report(report_path)
            except Exception as exc:  # keep the shard moving; audit fails later
                error = str(exc)
        usage = ((report or {}).get("llm") or {}).get("token_usage") or {}
        record = {
            "ordinal": ordinal,
            "task_id": task_id,
            "task_dir": str(task_dir),
            "mode": mode,
            "command": command,
            "return_code": return_code,
            "elapsed_s": time.monotonic() - started,
            "log": str(log_path),
            "run_report": str(report_path),
            "status": "passed" if not error else "failed",
            "error": error,
            "api_request_count": usage.get("request_count"),
            "api_response_count": usage.get("response_count"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }
        records.append(record)
        summary = {
            "schema_version": 1,
            "purpose": "all_tasks_real_api_vitis_acceptance",
            "shard_index": shard_index,
            "shard_count": shard_count,
            "selected_task_count": len(selected),
            "completed_task_count": len(records),
            "passed_task_count": sum(r["status"] == "passed" for r in records),
            "failed_task_count": sum(r["status"] == "failed" for r in records),
            "elapsed_s": time.monotonic() - shard_started,
            "records": records,
        }
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        print(
            f"shard={shard_index}/{shard_count} task={ordinal}/{len(selected)} "
            f"id={task_id} status={record['status']} rc={return_code} "
            f"requests={record['api_request_count']} elapsed={record['elapsed_s']:.1f}s",
            flush=True,
        )
    return json.loads(summary_path.read_text())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--shard-index", required=True, type=int)
    parser.add_argument("--shard-count", type=int, default=3)
    parser.add_argument("--task-timeout-s", type=float, default=7200.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        raise RuntimeError("shard index is outside shard count")
    result = run_shard(
        args.task_root.resolve(),
        args.output_root.resolve(),
        args.shard_index,
        args.shard_count,
        args.task_timeout_s,
    )
    return 0 if result["failed_task_count"] == 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())
