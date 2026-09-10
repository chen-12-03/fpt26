#!/usr/bin/env python3
"""Validate public/hidden Track-A testbench pairs with a minimal bad kernel.

For every selected task this runs four independent C simulations:

* reference kernel against the public testbench;
* reference kernel against the hidden testbench;
* an interface-preserving early-return mutant against the public testbench;
* the same mutant against the hidden testbench.

A pair passes only when both reference runs pass and both mutant runs fail.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from agent.runner import CSimTool
from agent.testbench import normalize_task_testbench_data
from build_track_a_150 import _inject_early_return
from llm4hls.task import load_task


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _data_fingerprint(files: dict[str, bytes] | None) -> dict[str, str]:
    return {
        name: hashlib.sha256(content).hexdigest()
        for name, content in sorted((files or {}).items())
    }


def _run(
    task: Any,
    source: str,
    *,
    hidden: bool,
    build_dir: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    tb_code = task.hidden_tb_code if hidden else task.public_tb_code
    tb_name = task.hidden_tb_name if hidden else task.public_tb_name
    data_files = (
        getattr(task, "hidden_data_files", None)
        if hidden
        else getattr(task, "public_data_files", None)
    )
    result = CSimTool(workspace_root=workspace_root).run(
        build_dir,
        task.assemble(source, tb_code, tb_name),
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
        data_files=data_files or None,
    )
    log = str(getattr(result, "log", "") or "")
    return {
        "ok": bool(getattr(result, "ok", False)),
        "phase": getattr(result, "phase", None),
        "return_code": getattr(result, "return_code", None),
        "elapsed_s": round(float(getattr(result, "elapsed_s", 0.0)), 3),
        "log_tail": log[-6000:],
    }


def validate_one(task_dir: Path, output_root: Path) -> dict[str, Any]:
    task = load_task(task_dir)
    normalize_task_testbench_data(task, include_hidden=True)
    public_data = _data_fingerprint(getattr(task, "public_data_files", None))
    hidden_data = _data_fingerprint(getattr(task, "hidden_data_files", None))
    checkpoint = output_root / "tasks" / task_dir.name / "pair_validation.json"
    if checkpoint.is_file():
        previous = json.loads(checkpoint.read_text(encoding="utf-8"))
        checkpoint_matches_current_pair = all(
            (
                previous.get("public_tb_sha256") == _sha256(task.public_tb_code),
                previous.get("hidden_tb_sha256") == _sha256(task.hidden_tb_code),
                previous.get("public_data_sha256", {}) == public_data,
                previous.get("hidden_data_sha256", {}) == hidden_data,
            )
        )
        if previous.get("passed") is True and checkpoint_matches_current_pair:
            return previous
    if task.reference_code is None:
        raise RuntimeError(f"{task.id}: reference source missing")
    mutant, derivation = _inject_early_return(task.reference_code, task.top, 91)
    task_root = output_root / "tasks" / task.id
    started = time.monotonic()
    runs = {
        "reference_public": _run(
            task,
            task.reference_code,
            hidden=False,
            build_dir=task_root / "reference_public",
            workspace_root=output_root.resolve(),
        ),
        "reference_hidden": _run(
            task,
            task.reference_code,
            hidden=True,
            build_dir=task_root / "reference_hidden",
            workspace_root=output_root.resolve(),
        ),
        "early_return_public": _run(
            task,
            mutant,
            hidden=False,
            build_dir=task_root / "early_return_public",
            workspace_root=output_root.resolve(),
        ),
        "early_return_hidden": _run(
            task,
            mutant,
            hidden=True,
            build_dir=task_root / "early_return_hidden",
            workspace_root=output_root.resolve(),
        ),
    }
    gates = {
        "reference_public_pass": runs["reference_public"]["ok"],
        "reference_hidden_pass": runs["reference_hidden"]["ok"],
        "early_return_public_rejected": not runs["early_return_public"]["ok"],
        "early_return_hidden_rejected": not runs["early_return_hidden"]["ok"],
        "public_hidden_distinct": (
            task.public_tb_code != task.hidden_tb_code or public_data != hidden_data
        ),
    }
    payload = {
        "schema_version": 1,
        "purpose": "track_a_testbench_pair_validation",
        "task_id": task.id,
        "public_tb_sha256": _sha256(task.public_tb_code),
        "hidden_tb_sha256": _sha256(task.hidden_tb_code),
        "public_data_sha256": public_data,
        "hidden_data_sha256": hidden_data,
        "mutant_derivation": derivation,
        "mutant_sha256": _sha256(mutant),
        "runs": runs,
        "gates": gates,
        "passed": all(gates.values()),
        "elapsed_s": round(time.monotonic() - started, 3),
    }
    _atomic_json(task_root / "pair_validation.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, default=Path("tasks/track_a_150_v2"))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--all", action="store_true", help="Validate every task directory.")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    task_ids = list(args.task_id)
    if args.all:
        task_ids.extend(
            path.name for path in args.task_root.iterdir() if (path / "task.toml").is_file()
        )
    task_ids = sorted(set(task_ids))
    if not task_ids:
        raise SystemExit("select tasks with --task-id or --all")
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        raise SystemExit("invalid shard index/count")
    task_ids = [
        task_id for index, task_id in enumerate(task_ids)
        if index % args.shard_count == args.shard_index
    ]
    records = []
    for task_id in task_ids:
        task_dir = args.task_root / task_id
        if not (task_dir / "task.toml").is_file():
            raise SystemExit(f"unknown task id: {task_id}")
        record = validate_one(task_dir, args.output_root)
        records.append(record)
        print(f"{task_id}: {'PASS' if record['passed'] else 'FAIL'}", flush=True)
    summary = {
        "schema_version": 1,
        "purpose": "track_a_testbench_pair_validation_summary",
        "task_count": len(records),
        "passed_count": sum(record["passed"] for record in records),
        "failed_task_ids": [record["task_id"] for record in records if not record["passed"]],
        "tasks": {
            record["task_id"]: {
                "passed": record["passed"],
                "gates": record["gates"],
                "evidence": str(
                    args.output_root / "tasks" / record["task_id"] / "pair_validation.json"
                ),
            }
            for record in records
        },
    }
    summary_name = (
        "pair_validation_summary.json"
        if args.shard_count == 1
        else f"pair_validation_summary_shard_{args.shard_index:02d}.json"
    )
    _atomic_json(args.output_root / summary_name, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["passed_count"] == summary["task_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
