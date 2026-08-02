#!/usr/bin/env python3
"""Collect starter/reference C-sim and synthesis evidence without scoring.

The reference is the fixed public AMD/Xilinx example imported under
``tasks/generated``.  The starter is derived deterministically by removing
only HLS directives that can affect scheduling, parallelism, or storage.
Interface directives and report-only LOOP_TRIPCOUNT directives are preserved.
No model backend or network API is used by this command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import tomllib
from pathlib import Path
from typing import Any

from agent.runner import CSimTool, SynthTool
from agent.testbench import normalize_task_testbench_data
from llm4hls.task import load_task


QOR_DIRECTIVES = (
    "ALLOCATION",
    "ARRAY_PARTITION",
    "ARRAY_RESHAPE",
    "BIND_OP",
    "BIND_STORAGE",
    "DATAFLOW",
    "DEPENDENCE",
    "FUNCTION_INSTANTIATE",
    "INLINE",
    "LATENCY",
    "LOOP_FLATTEN",
    "LOOP_MERGE",
    "OCCURRENCE",
    "PERFORMANCE",
    "PIPELINE",
    "STREAM",
    "UNROLL",
)
DIRECTIVE_RE = re.compile(
    r"^(?P<indent>\s*)#\s*pragma\s+HLS\s+(?P<name>"
    + "|".join(QOR_DIRECTIVES)
    + r")\b",
    re.IGNORECASE,
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def derive_starter(reference: str) -> tuple[str, list[dict[str, Any]]]:
    kept: list[str] = []
    removed: list[dict[str, Any]] = []
    for line_number, line in enumerate(reference.splitlines(keepends=True), 1):
        match = DIRECTIVE_RE.match(line)
        if match:
            removed.append(
                {
                    "line_number": line_number,
                    "directive": match.group("name").upper(),
                    "text": line.rstrip("\n"),
                }
            )
        else:
            kept.append(line)
    return "".join(kept), removed


def tool_record(result: Any, artifact_dir: Path) -> dict[str, Any]:
    report = result.report.to_dict() if result.report is not None else None
    xml_path = artifact_dir / "synth_proj/sol/syn/report/csynth.xml"
    return {
        "kind": result.kind,
        "ok": result.ok,
        "phase": result.phase,
        "return_code": result.return_code,
        "elapsed_s": result.elapsed_s,
        "report": report,
        "artifact_dir": str(artifact_dir),
        "csynth_xml": str(xml_path) if xml_path.is_file() else None,
        "csynth_xml_sha256": (
            sha256_bytes(xml_path.read_bytes()) if xml_path.is_file() else None
        ),
        "log": result.log,
    }


def provenance(task_dir: Path) -> dict[str, Any]:
    spec = tomllib.loads((task_dir / "task.toml").read_text())
    return dict(spec.get("provenance", {}))


def eligible_task_dirs(task_root: Path) -> list[Path]:
    selected: list[Path] = []
    for task_dir in sorted(task_root.glob("amd_intro__*/")):
        spec = tomllib.loads((task_dir / "task.toml").read_text())
        kernel_path = task_dir / spec["kernel_file"]
        _starter, removed = derive_starter(kernel_path.read_text())
        if removed:
            selected.append(task_dir)
    return selected


def collect(task_dir: Path, output_root: Path) -> Path:
    task = load_task(task_dir)
    normalize_task_testbench_data(task)
    reference_code = task.kernel_code
    starter_code, removed = derive_starter(reference_code)
    if not removed:
        raise RuntimeError(f"no QoR directive found in {task.id}")
    if starter_code == reference_code:
        raise RuntimeError(f"starter/reference unexpectedly identical: {task.id}")

    task_out = output_root / task.id
    evidence_path = task_out / "evidence.json"
    if evidence_path.exists():
        return evidence_path
    task_out.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    csim = CSimTool()
    synth = SynthTool()
    public_data = getattr(task, "public_data_files", None) or None

    starter_csim_dir = task_out / "starter_csim"
    starter_csim = csim.run(
        starter_csim_dir,
        task.assemble(starter_code, task.public_tb_code, task.public_tb_name),
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
        data_files=public_data,
    )
    reference_csim_dir = task_out / "reference_csim"
    reference_csim = csim.run(
        reference_csim_dir,
        task.assemble(reference_code, task.public_tb_code, task.public_tb_name),
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
        data_files=public_data,
    )

    starter_files = dict(task.headers)
    starter_files[task.kernel_name] = starter_code
    starter_synth_dir = task_out / "starter_synth"
    starter_synth = synth.run(
        starter_synth_dir,
        starter_files,
        synth_sources=[task.kernel_name],
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
    )

    reference_files = dict(task.headers)
    reference_files[task.kernel_name] = reference_code
    reference_synth_dir = task_out / "reference_synth"
    reference_synth = synth.run(
        reference_synth_dir,
        reference_files,
        synth_sources=[task.kernel_name],
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
    )

    record = {
        "schema_version": 1,
        "purpose": "qhw_starter_reference_study_raw_evidence",
        "task_id": task.id,
        "task_dir": str(task_dir.resolve()),
        "target": {
            "top": task.top,
            "part": task.part,
            "clock_ns": task.clock_ns,
        },
        "provenance": provenance(task_dir),
        "pair": {
            "construction": (
                "reference is the fixed public upstream code; starter removes "
                "only enumerated hardware-QoR pragmas"
            ),
            "kernel_name": task.kernel_name,
            "starter_sha256": sha256_bytes(starter_code.encode()),
            "reference_sha256": sha256_bytes(reference_code.encode()),
            "starter_reference_identical": starter_code == reference_code,
            "removed_directive_count": len(removed),
            "removed_directives": removed,
        },
        "starter_csim": tool_record(starter_csim, starter_csim_dir),
        "reference_csim": tool_record(reference_csim, reference_csim_dir),
        "starter_synth": tool_record(starter_synth, starter_synth_dir),
        "reference_synth": tool_record(reference_synth, reference_synth_dir),
        "wall_time_s": time.monotonic() - started,
        "api": {
            "invoked": False,
            "request_count": 0,
            "model": "not_applicable",
        },
    }
    evidence_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return evidence_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        raise SystemExit("invalid shard index/count")

    task_dirs = eligible_task_dirs(args.task_root)
    selected = [
        path
        for index, path in enumerate(task_dirs)
        if index % args.shard_count == args.shard_index
    ]
    failures = 0
    for task_dir in selected:
        try:
            evidence = collect(task_dir, args.output_root)
            record = json.loads(evidence.read_text())
            stages = (
                record["starter_csim"],
                record["reference_csim"],
                record["starter_synth"],
                record["reference_synth"],
            )
            ok = all(stage["ok"] for stage in stages)
            failures += int(not ok)
            print(f"{record['task_id']} {'PASS' if ok else 'FAIL'} {evidence}")
        except Exception as exc:
            failures += 1
            print(f"{task_dir.name} ERROR {type(exc).__name__}: {exc}")
    print(
        f"shard={args.shard_index}/{args.shard_count} "
        f"selected={len(selected)} failures={failures}"
    )
    return 0 if failures == 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())
