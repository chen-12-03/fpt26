#!/usr/bin/env python3
"""Generate and validate independent MachSuite hidden input/check fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from agent.testbench import normalize_task_testbench_data
from build_track_a_150 import _inject_early_return
from harden_track_a_testbench_transcripts import _run
from llm4hls.task import load_task


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mutate_section_value(content: bytes, section: int = 1) -> tuple[bytes, str]:
    text = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    markers = list(re.finditer(r"(?m)^%%\s*$", text))
    if len(markers) < section:
        raise RuntimeError("input.data has no section marker")
    marker = markers[section - 1]
    start = marker.end()
    token = re.search(r"\S+", text[start:])
    if token is None:
        raise RuntimeError("first input section is empty")
    left, right = start + token.start(), start + token.end()
    old = text[left:right]
    if re.fullmatch(r"[-+]?\d+", old):
        new = str(int(old) + 1)
        kind = "integer_plus_one"
    elif re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][-+]?\d+)?", old):
        new = f"{float(old) + 0.125:.16f}"
        kind = "floating_plus_0.125"
    else:
        first = old[0]
        replacement = "a" if first.lower() != "a" else "b"
        if first.isupper():
            replacement = replacement.upper()
        new = replacement + old[1:]
        kind = "string_first_character_rotation"
    mutated = text[:left] + new + text[right:]
    return mutated.encode("utf-8"), f"{kind}:{old}->{new}"


def _generated_output(build_dir: Path) -> bytes:
    executables = sorted(build_dir.glob("**/csim.exe"))
    if len(executables) != 1:
        raise RuntimeError(f"expected one csim.exe, found {len(executables)}")
    output = executables[0].parent / "output.data"
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("reference did not generate output.data")
    return output.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def harden_one(
    source_dir: Path, staging_root: Path, evidence_root: Path
) -> dict[str, Any]:
    started = time.monotonic()
    staged = staging_root / source_dir.name
    checkpoint = evidence_root / source_dir.name / "hardening_evidence.json"
    if checkpoint.is_file() and staged.is_dir():
        return json.loads(checkpoint.read_text(encoding="utf-8"))
    if staged.exists():
        shutil.rmtree(staged)
    shutil.copytree(source_dir, staged)
    hidden_input = staged / "hidden" / "input.data"
    hidden_check = staged / "hidden" / "check.data"
    if not hidden_input.is_file() or not hidden_check.is_file():
        raise RuntimeError("expected hidden input.data and check.data")
    section = 2 if "__machsuite__kmp_kmp" in source_dir.name else 1
    mutated, derivation = _mutate_section_value(hidden_input.read_bytes(), section)
    hidden_input.write_bytes(mutated)

    task = load_task(staged)
    normalize_task_testbench_data(task, include_hidden=True)
    generation_dir = evidence_root / task.id / "hidden_check_generation"
    _run(
        task,
        task.reference_code,
        generation_dir,
        evidence_root.resolve(),
        use_hidden=True,
    )
    hidden_check.write_bytes(_generated_output(generation_dir))

    task = load_task(staged)
    normalize_task_testbench_data(task, include_hidden=True)
    reference_hidden, _ = _run(
        task,
        task.reference_code,
        evidence_root / task.id / "reference_hidden",
        evidence_root.resolve(),
        use_hidden=True,
    )
    reference_public, _ = _run(
        task,
        task.reference_code,
        evidence_root / task.id / "reference_public",
        evidence_root.resolve(),
        use_hidden=False,
    )
    mutant, mutation = _inject_early_return(task.reference_code, task.top, 211)
    mutant_hidden, _ = _run(
        task,
        mutant,
        evidence_root / task.id / "early_return_hidden",
        evidence_root.resolve(),
        use_hidden=True,
    )
    mutant_public, _ = _run(
        task,
        mutant,
        evidence_root / task.id / "early_return_public",
        evidence_root.resolve(),
        use_hidden=False,
    )
    record = {
        "schema_version": 1,
        "purpose": "track_a_machsuite_hidden_fixture_hardening",
        "task_id": task.id,
        "input_derivation": derivation,
        "public_input_derivation": "preserved_existing_public_fixture",
        "oracle_strategy": "reference_generated_machsuite_check_fixture",
        "reference_hidden_pass": reference_hidden,
        "reference_public_pass": reference_public,
        "early_return_mutation": mutation,
        "early_return_rejected": not mutant_hidden,
        "public_early_return_rejected": not mutant_public,
        "public_hidden_byte_distinct": (
            (staged / "input.data").read_bytes() != hidden_input.read_bytes()
        ),
        "public_testbench_preserved": True,
        "hidden_fixture_names": ["input.data", "check.data"],
        "hidden_fixture_sha256": {
            "input.data": _sha256(hidden_input),
            "check.data": _sha256(hidden_check),
        },
        "staged_task": str(staged),
        "elapsed_s": round(time.monotonic() - started, 3),
    }
    _atomic_json(checkpoint, record)
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--audit-json", type=Path, required=True)
    parser.add_argument(
        "--task-id",
        action="append",
        default=[],
        help="Restrict hardening to an audited task ID; may be repeated.",
    )
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = json.loads(args.audit_json.read_text(encoding="utf-8"))
    task_ids = sorted(
        task_id
        for task_id in audit.get("public_clone_task_ids", [])
        if "__machsuite__" in task_id
    )
    if args.task_id:
        requested = set(args.task_id)
        missing = sorted(requested.difference(task_ids))
        if missing:
            raise SystemExit(
                "requested task IDs are not audited MachSuite public clones: "
                + ", ".join(missing)
            )
        task_ids = [task_id for task_id in task_ids if task_id in requested]
    selected = [
        task_id
        for index, task_id in enumerate(task_ids)
        if index % args.shard_count == args.shard_index
    ]
    records, failures = [], []
    for task_id in selected:
        try:
            records.append(
                harden_one(args.task_root / task_id, args.staging_root, args.evidence_root)
            )
        except Exception as exc:
            failures.append({"task_id": task_id, "error": f"{type(exc).__name__}: {exc}"})
    summary = {
        "schema_version": 1,
        "purpose": "track_a_machsuite_hidden_fixture_hardening_summary",
        "selected_task_count": len(selected),
        "task_count": len(records),
        "failure_count": len(failures),
        "failures": failures,
        "passed_count": sum(
            all(
                record[key]
                for key in (
                    "reference_hidden_pass",
                    "reference_public_pass",
                    "early_return_rejected",
                    "public_early_return_rejected",
                    "public_hidden_byte_distinct",
                )
            )
            for record in records
        ),
        "tasks": records,
    }
    _atomic_json(
        args.evidence_root / f"hardening_summary_shard_{args.shard_index:02d}.json",
        summary,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not failures and summary["passed_count"] == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
