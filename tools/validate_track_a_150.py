#!/usr/bin/env python3
"""Fresh U55C/Vitis 2025.2 acceptance for the Track-A 150-task corpus.

Each task is checkpointed atomically in ``<output>/tasks/<id>/evidence.json``.
Resume skips only accepted checkpoints.  Failed candidates remain recorded and
are never counted in the accepted manifest.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from agent.candidate.validator import (
    InterfaceValidator,
    frequency_gate,
    resource_gate,
)
from agent.runner import CSimTool, CoSimTool, SynthTool
from agent.testbench import normalize_task_testbench_data
from agent.task_io import load_public_task
from llm4hls.task import load_task
from scoring.evaluator import _evaluate_anchor_source


EXPECTED_COUNTS = {
    "code_generation": 25,
    "compile_repair": 25,
    "synthesis_repair": 25,
    "functional_repair": 25,
    "structural_cosim_repair": 25,
    "qor_optimization": 25,
}
U55C_PART = "xcu55c-fsvh2892-2L-e"
CAPACITY_KEYS = ("BRAM_18K", "DSP", "FF", "LUT", "URAM")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _tool_record(result: Any, artifact_dir: Path) -> dict[str, Any]:
    report = result.report.to_dict() if getattr(result, "report", None) else None
    payload = getattr(result, "cosim", None)
    cosim = dataclasses.asdict(payload) if dataclasses.is_dataclass(payload) else None
    log = str(getattr(result, "log", "") or "")
    return {
        "kind": getattr(result, "kind", None),
        "ok": bool(getattr(result, "ok", False)),
        "phase": getattr(result, "phase", None),
        "return_code": getattr(result, "return_code", None),
        "elapsed_s": round(float(getattr(result, "elapsed_s", 0.0)), 3),
        "report": report,
        "cosim": cosim,
        "artifact_dir": str(artifact_dir),
        "log_tail": log[-12000:],
    }


def _vitis_version() -> dict[str, Any]:
    command = ["vitis-run", "--version"]
    completed = subprocess.run(
        command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
    )
    output = completed.stdout.strip()
    return {
        "command": command,
        "return_code": completed.returncode,
        "output": output,
        "version_2025_2": completed.returncode == 0
        and bool(re.search(r"(?<!\d)2025\.2(?!\d)", output)),
    }


def _interface(task: Any, reference: str, baseline: str) -> dict[str, Any]:
    try:
        validation = InterfaceValidator.from_source(
            task.top, reference
        ).validate(baseline)
        return validation.to_dict()
    except ValueError as exc:
        return {
            "ok": False,
            "reason": f"contract_error:{exc}",
            "fingerprint": None,
            "canonical_signature": None,
            "required_includes_present": False,
        }


def _synth_gates(result: Any, target_clock_ns: float) -> dict[str, Any]:
    report = getattr(result, "report", None)
    freq = frequency_gate(report, target_clock_ns)
    capacity = resource_gate(report)
    return {
        "frequency_100mhz": freq.to_dict(),
        "resource_capacity": capacity.to_dict(),
    }


def _qor_ratio(
    baseline_report: dict[str, Any] | None, reference: Any
) -> dict[str, Any]:
    if baseline_report is None:
        return {"ok": False, "reason": "baseline_report_missing"}
    base_latency = baseline_report.get("latency_worst")
    base_clock = baseline_report.get("clock_period_ns")
    ref_latency = getattr(reference, "synth_latency", None)
    ref_clock = getattr(reference, "synth_clock_ns", None)
    if not all(
        isinstance(value, (int, float)) and value > 0
        for value in (base_latency, base_clock, ref_latency, ref_clock)
    ):
        return {"ok": False, "reason": "latency_or_clock_missing"}
    performance_ratio = (base_latency * base_clock) / (ref_latency * ref_clock)
    base_resources = dict(baseline_report.get("resources") or {})
    ref_resources = dict(getattr(reference, "synth_resources", {}) or {})
    growth: dict[str, float] = {}
    for key in CAPACITY_KEYS:
        base = max(1, int(base_resources.get(key, 0)))
        ref = max(1, int(ref_resources.get(key, 0)))
        growth[key] = ref / base
    bottleneck = max(growth, key=growth.get)
    area_ratio = 1.0 / growth[bottleneck]
    hardware_ratio = performance_ratio**0.55 * area_ratio**0.45
    return {
        "ok": math.isfinite(hardware_ratio) and hardware_ratio > 1.0001,
        "reason": "reference_improves_hardware_ratio"
        if hardware_ratio > 1.0001
        else "reference_not_better_than_baseline",
        "performance_ratio": performance_ratio,
        "area_ratio": area_ratio,
        "hardware_ratio": hardware_ratio,
        "bottleneck_resource": bottleneck,
        "growth_by_resource": growth,
    }


def _reference_record(reference: Any) -> dict[str, Any]:
    if dataclasses.is_dataclass(reference):
        return dataclasses.asdict(reference)
    raise TypeError(f"unexpected reference evidence: {type(reference)}")


def validate_one(task_dir: Path, output_root: Path, toolchain: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    spec = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    category = str(spec["track_a_category"])
    task_id = str(spec["task_id"])
    work = output_root / "tasks" / task_id
    checkpoint = work / "evidence.json"
    if checkpoint.is_file():
        previous = json.loads(checkpoint.read_text(encoding="utf-8"))
        if previous.get("accepted") is True:
            return previous

    task = load_task(task_dir)
    normalize_task_testbench_data(task)
    if task.reference_code is None:
        raise RuntimeError(f"{task_id}: reference missing")
    baseline = task.kernel_code
    reference = task.reference_code
    attempt = int(time.time_ns())
    attempt_root = work / f"attempt_{attempt}"

    reference_ev = _evaluate_anchor_source(
        source_code=reference,
        source_label="reference",
        task=task,
        grade_root=attempt_root / "reference",
        requires_cosim=task.requires_cosim,
    )
    reference_record = _reference_record(reference_ev)

    public_files = task.assemble(baseline, task.public_tb_code, task.public_tb_name)
    interface = _interface(task, reference, baseline)
    baseline_csim_dir = attempt_root / "baseline" / "csim"
    baseline_csim = CSimTool().run(
        baseline_csim_dir,
        public_files,
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
        data_files=getattr(task, "data_files", None)
        or getattr(task, "public_data_files", None)
        or None,
    )
    baseline_synth_dir = attempt_root / "baseline" / "synth"
    baseline_synth = SynthTool().run(
        baseline_synth_dir,
        {**task.headers, task.kernel_name: baseline},
        synth_sources=[task.kernel_name],
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
    )
    baseline_gates = _synth_gates(baseline_synth, task.clock_ns)
    baseline_cosim = None
    baseline_cosim_dir = attempt_root / "baseline" / "cosim"
    if category == "structural_cosim_repair" and baseline_synth.ok:
        baseline_cosim = CoSimTool().run(
            baseline_cosim_dir,
            public_files,
            synth_sources=[task.kernel_name],
            tb_sources=[task.public_tb_name],
            top=task.top,
            part=task.part,
            clock_ns=task.clock_ns,
        )

    expected_checks: dict[str, bool] = {
        "interface_preserved": interface.get("ok") is True,
    }
    if category in {"code_generation", "compile_repair"}:
        expected_checks.update(
            {
                "baseline_csim_fails": not baseline_csim.ok,
                "baseline_synth_fails": not baseline_synth.ok,
            }
        )
    elif category == "synthesis_repair":
        expected_checks.update(
            {
                "baseline_csim_passes": baseline_csim.ok,
                "baseline_synth_fails": not baseline_synth.ok,
            }
        )
    elif category == "functional_repair":
        expected_checks.update(
            {
                "baseline_csim_fails": not baseline_csim.ok,
                "baseline_synth_passes": baseline_synth.ok,
            }
        )
    elif category == "structural_cosim_repair":
        expected_checks.update(
            {
                "baseline_csim_passes": baseline_csim.ok,
                "baseline_synth_passes": baseline_synth.ok,
                "baseline_cosim_fails": baseline_cosim is not None
                and not baseline_cosim.ok,
            }
        )
    elif category == "qor_optimization":
        expected_checks.update(
            {
                "baseline_csim_passes": baseline_csim.ok,
                "baseline_synth_passes": baseline_synth.ok,
            }
        )
    else:
        raise RuntimeError(f"{task_id}: unknown category {category}")

    baseline_synth_record = _tool_record(baseline_synth, baseline_synth_dir)
    qor = (
        _qor_ratio(baseline_synth_record["report"], reference_ev)
        if category == "qor_optimization"
        else None
    )
    if qor is not None:
        expected_checks["reference_qor_improves"] = qor["ok"] is True

    reference_checks = {
        "accepted": reference_record.get("accepted") is True,
        "interface": (reference_record.get("interface") or {}).get("ok") is True,
        "hidden_csim": reference_record.get("csim") == "pass",
        "synth": reference_record.get("synth") == "pass",
        "frequency_100mhz": (reference_record.get("frequency") or {}).get("ok")
        is True,
        "resource_capacity": (reference_record.get("resource") or {}).get("ok")
        is True,
        "required_cosim": (
            (reference_record.get("cosim") or {}).get("ok") is True
            if task.requires_cosim
            else True
        ),
    }
    artifact_checks = {
        "task_toml": (task_dir / "task.toml").is_file(),
        "description": (task_dir / "description.md").is_file(),
        "baseline": (task_dir / task.kernel_name).is_file(),
        "headers": all((task_dir / name).is_file() for name in spec.get("header_files", [])),
        "public_testbench": (task_dir / task.public_tb_name).is_file(),
        "hidden_testbench": (task_dir / "hidden" / task.hidden_tb_name).is_file(),
        "reference": (task_dir / "reference" / task.kernel_name).is_file(),
        "source_url": str(spec.get("source_url", "")).startswith("https://github.com/"),
        "source_commit": bool(re.fullmatch(r"[0-9a-f]{40}", str(spec.get("repo_commit", "")))),
        "license": spec.get("license") in {"MIT", "Apache-2.0"},
    }
    target_checks = {
        "u55c": task.part == U55C_PART,
        "vitis_2025_2": toolchain.get("version_2025_2") is True,
        "minimum_frequency_declared": float(
            (spec.get("target") or {}).get("minimum_frequency_mhz", 0)
        )
        >= 100.0,
    }
    accepted = all(
        list(expected_checks.values())
        + list(reference_checks.values())
        + list(artifact_checks.values())
        + list(target_checks.values())
    )
    record = {
        "schema_version": 1,
        "purpose": "track_a_task_initial_acceptance",
        "task_id": task_id,
        "category": category,
        "accepted": accepted,
        "task_dir": str(task_dir),
        "attempt_root": str(attempt_root),
        "toolchain": toolchain,
        "target": {
            "part": task.part,
            "clock_ns": task.clock_ns,
            "requires_cosim": task.requires_cosim,
        },
        "hashes": {
            "task_toml": _sha256(task_dir / "task.toml"),
            "description": _sha256(task_dir / "description.md"),
            "baseline": _sha256(task_dir / task.kernel_name),
            "reference": _sha256(task_dir / "reference" / task.kernel_name),
            "public_testbench": _sha256(task_dir / task.public_tb_name),
            "hidden_testbench": _sha256(task_dir / "hidden" / task.hidden_tb_name),
        },
        "artifact_checks": artifact_checks,
        "target_checks": target_checks,
        "expected_baseline_checks": expected_checks,
        "reference_checks": reference_checks,
        "interface": interface,
        "baseline": {
            "csim": _tool_record(baseline_csim, baseline_csim_dir),
            "synth": baseline_synth_record,
            "synth_gates": baseline_gates,
            "cosim": _tool_record(baseline_cosim, baseline_cosim_dir)
            if baseline_cosim is not None
            else None,
        },
        "reference": reference_record,
        "qor_comparison": qor,
        "elapsed_s": round(time.monotonic() - started, 3),
    }
    _atomic_json(checkpoint, record)
    return record


def _discover(task_root: Path) -> list[Path]:
    tasks = sorted(path.parent for path in task_root.glob("*/task.toml"))
    if len(tasks) != 150:
        raise RuntimeError(f"expected 150 task packages, found {len(tasks)}")
    return tasks


def _corpus_checks(tasks: list[Path]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    family_categories: dict[str, set[str]] = defaultdict(set)
    ids: set[str] = set()
    tasks_with_headers = 0
    for task_dir in tasks:
        spec = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
        task_id = str(spec["task_id"])
        if task_id in ids:
            raise RuntimeError(f"duplicate task id: {task_id}")
        ids.add(task_id)
        category = str(spec["track_a_category"])
        counts[category] += 1
        tasks_with_headers += int(bool(spec.get("header_files")))
        family_categories[str(spec["kernel_family_id"])].add(category)
    overlaps = {
        family: sorted(categories)
        for family, categories in family_categories.items()
        if len(categories) > 1
    }
    return {
        "task_count": len(tasks),
        "category_counts": dict(sorted(counts.items())),
        "category_counts_ok": dict(counts) == EXPECTED_COUNTS,
        "unique_kernel_family_count": len(family_categories),
        "cross_category_kernel_overlap_count": len(overlaps),
        "cross_category_kernel_overlaps": overlaps,
        "tasks_with_headers": tasks_with_headers,
        "all_tasks_have_headers": tasks_with_headers == len(tasks),
    }


def _aggregate(
    task_root: Path,
    output_root: Path,
    records: list[dict[str, Any]],
    corpus: dict[str, Any],
    toolchain: dict[str, Any],
) -> dict[str, Any]:
    accepted = [item for item in records if item.get("accepted") is True]
    category_accepted = Counter(item["category"] for item in accepted)
    failures = [
        {
            "task_id": item["task_id"],
            "category": item["category"],
            "failed_expected_checks": sorted(
                key
                for key, value in (item.get("expected_baseline_checks") or {}).items()
                if value is not True
            ),
            "failed_reference_checks": sorted(
                key
                for key, value in (item.get("reference_checks") or {}).items()
                if value is not True
            ),
            "failed_artifact_checks": sorted(
                key
                for key, value in (item.get("artifact_checks") or {}).items()
                if value is not True
            ),
            "evidence": str(
                output_root / "tasks" / item["task_id"] / "evidence.json"
            ),
        }
        for item in records
        if item.get("accepted") is not True
    ]
    public_preflights = [
        load_public_task(path.parent)[1]
        for path in sorted(task_root.glob("*/task.toml"))
    ]
    submission_isolation = {
        "task_count": len(public_preflights),
        "forbidden_artifact_access_count": sum(
            item.forbidden_artifact_accesses for item in public_preflights
        ),
        "all_u55c": all(item.part == U55C_PART for item in public_preflights),
        "observed_vitis_versions": sorted(
            {item.observed_vitis_version for item in public_preflights}
        ),
        "public_files_read_count": sum(
            len(item.public_files_read) for item in public_preflights
        ),
    }
    payload = {
        "schema_version": 1,
        "purpose": "track_a_150_initial_gate_matrix",
        "task_root": str(task_root),
        "output_root": str(output_root),
        "toolchain": toolchain,
        "validation_implementation": {
            "path": str(Path(__file__).resolve()),
            "sha256": _sha256(Path(__file__).resolve()),
        },
        "candidate_manifest": {
            "path": str(task_root / "candidate_manifest.json"),
            "sha256": _sha256(task_root / "candidate_manifest.json"),
        },
        "corpus": corpus,
        "submission_isolation": submission_isolation,
        "accepted_count": len(accepted),
        "rejected_count": len(failures),
        "accepted_by_category": dict(sorted(category_accepted.items())),
        "fully_accepted": len(accepted) == 150
        and corpus["category_counts_ok"]
        and corpus["cross_category_kernel_overlap_count"] == 0
        and corpus["all_tasks_have_headers"]
        and submission_isolation["forbidden_artifact_access_count"] == 0,
        "tasks": {
            item["task_id"]: {
                "category": item["category"],
                "accepted": item["accepted"],
                "evidence": str(
                    output_root / "tasks" / item["task_id"] / "evidence.json"
                ),
            }
            for item in records
        },
        "failure_audit": failures,
    }
    _atomic_json(output_root / "initial_gate_matrix.json", payload)
    if payload["fully_accepted"]:
        manifest_tasks = []
        for item in sorted(accepted, key=lambda value: value["task_id"]):
            task_dir = Path(item["task_dir"])
            spec = tomllib.loads(
                (task_dir / "task.toml").read_text(encoding="utf-8")
            )
            manifest_tasks.append(
                {
                    "task_id": item["task_id"],
                    "category": item["category"],
                    "task_type": spec["task_type"],
                    "task_dir": item["task_dir"],
                    "top": spec["top"],
                    "kernel_file": spec["kernel_file"],
                    "header_files": list(spec.get("header_files") or []),
                    "public_tb": spec["public_tb"],
                    "hidden_tb": spec["hidden_tb"],
                    "requires_cosim": bool(spec.get("requires_cosim", False)),
                    "expected_baseline_state": spec[
                        "expected_baseline_state"
                    ],
                    "fault_derivation": spec["fault_derivation"],
                    "kernel_family_id": spec["kernel_family_id"],
                    "source": {
                        "task_id": spec["source_task_id"],
                        "url": spec["source_url"],
                        "path": spec["source_path"],
                        "commit": spec["repo_commit"],
                        "license": spec["license"],
                        "sha256": spec["source_sha256"],
                    },
                    "hashes": {
                        **dict(item["hashes"]),
                        "headers": {
                            name: _sha256(task_dir / name)
                            for name in spec.get("header_files", [])
                        },
                    },
                    "evidence": str(
                        output_root
                        / "tasks"
                        / item["task_id"]
                        / "evidence.json"
                    ),
                    "evidence_sha256": _sha256(
                        output_root
                        / "tasks"
                        / item["task_id"]
                        / "evidence.json"
                    ),
                }
            )
        manifest = {
            "schema_version": 1,
            "purpose": "track_a_150_frozen_accepted_manifest",
            "task_count": 150,
            "category_counts": corpus["category_counts"],
            "unique_kernel_family_count": corpus["unique_kernel_family_count"],
            "cross_category_kernel_overlap_count": 0,
            "toolchain": toolchain,
            "submission_isolation": submission_isolation,
            "tasks": manifest_tasks,
        }
        _atomic_json(output_root / "accepted_manifest.json", manifest)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, default=Path("tasks/track_a_150"))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--aggregate-only", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        raise SystemExit("invalid shard index/count")
    tasks = _discover(args.task_root)
    corpus = _corpus_checks(tasks)
    if args.aggregate_only:
        toolchain = _vitis_version()
        records = []
        for task_dir in tasks:
            checkpoint = (
                args.output_root / "tasks" / task_dir.name / "evidence.json"
            )
            if not checkpoint.is_file():
                raise RuntimeError(f"missing task checkpoint: {checkpoint}")
            records.append(json.loads(checkpoint.read_text(encoding="utf-8")))
        matrix = _aggregate(
            args.task_root, args.output_root, records, corpus, toolchain
        )
        print(
            f"accepted={matrix['accepted_count']} "
            f"rejected={matrix['rejected_count']} "
            f"fully_accepted={matrix['fully_accepted']}",
            flush=True,
        )
        return 0 if matrix["fully_accepted"] else 4
    if args.task_id:
        wanted = set(args.task_id)
        tasks = [task for task in tasks if task.name in wanted]
        missing = wanted - {task.name for task in tasks}
        if missing:
            raise RuntimeError(f"unknown task ids: {sorted(missing)}")
    else:
        tasks = [
            task
            for index, task in enumerate(tasks)
            if index % args.shard_count == args.shard_index
        ]
    toolchain = _vitis_version()
    if not toolchain["version_2025_2"]:
        raise RuntimeError(f"Vitis 2025.2 gate failed: {toolchain}")
    records = []
    for index, task_dir in enumerate(tasks, start=1):
        record = validate_one(task_dir, args.output_root, toolchain)
        records.append(record)
        print(
            f"{index}/{len(tasks)} {record['task_id']} "
            f"category={record['category']} accepted={record['accepted']} "
            f"elapsed={record['elapsed_s']}s",
            flush=True,
        )
    shard = {
        "schema_version": 1,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "selected_task_count": len(tasks),
        "accepted_count": sum(item.get("accepted") is True for item in records),
        "task_ids": [item["task_id"] for item in records],
        "toolchain": toolchain,
        "host": platform.node(),
    }
    _atomic_json(
        args.output_root / f"validation_shard_{args.shard_index:02d}.json", shard
    )
    # A single-shard run can freeze immediately.  Multi-shard runs use
    # --aggregate-only after all shards finish.
    if args.shard_count == 1 and not args.task_id:
        matrix = _aggregate(args.task_root, args.output_root, records, corpus, toolchain)
        return 0 if matrix["fully_accepted"] else 4
    return 0 if all(item.get("accepted") is True for item in records) else 4


if __name__ == "__main__":
    raise SystemExit(main())
