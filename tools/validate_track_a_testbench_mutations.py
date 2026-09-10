#!/usr/bin/env python3
"""Run evaluator-side CSim mutation probes against Track-A hidden tests.

The script is resumable per task.  A surviving mutant is direct evidence that
the hidden testbench does not detect that fault.  A rejected mutant is useful
evidence but is not automatically called a semantic kill, because CSim may
also reject a syntactically valid source for toolchain-specific reasons.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

from agent.candidate.validator import InterfaceValidator
from agent.runner import CSimTool
from agent.testbench import normalize_task_testbench_data
from build_track_a_150 import _inject_early_return
from llm4hls.task import load_task


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _mask_comments(source: str) -> str:
    return re.sub(
        r"//[^\n]*|/\*.*?\*/",
        lambda match: "".join("\n" if char == "\n" else " " for char in match.group(0)),
        source,
        flags=re.S,
    )


def _comparison_flip(source: str) -> tuple[str, str]:
    clean = _mask_comments(source)
    for match in re.finditer(r"==|!=|<=|>=", clean):
        line_start = clean.rfind("\n", 0, match.start()) + 1
        line_end = clean.find("\n", match.end())
        if line_end < 0:
            line_end = len(clean)
        if clean[line_start:line_end].lstrip().startswith("#"):
            continue
        replacement = {"==": "!=", "!=": "==", "<=": ">", ">=": "<"}[match.group(0)]
        return (
            source[: match.start()] + replacement + source[match.end() :],
            f"comparison_flip:{match.group(0)}->{replacement}:offset={match.start()}",
        )
    raise RuntimeError("no comparison candidate")


def _top_body_offset(source: str, top: str) -> int:
    clean = _mask_comments(source)
    match = re.search(rf"\b{re.escape(top)}\s*\(", clean)
    if match is None:
        raise RuntimeError("top function not found")
    depth = 0
    close_paren = None
    for index in range(clean.find("(", match.start()), len(clean)):
        if clean[index] == "(":
            depth += 1
        elif clean[index] == ")":
            depth -= 1
            if depth == 0:
                close_paren = index
                break
    if close_paren is None:
        raise RuntimeError("unbalanced top signature")
    body = clean.find("{", close_paren)
    if body < 0:
        raise RuntimeError("top body not found")
    return body


def _semantic_literal_mutation(source: str, top: str) -> tuple[str, str]:
    clean = _mask_comments(source)
    body = _top_body_offset(source, top)
    candidates: list[tuple[int, int, str]] = []
    for match in re.finditer(r"(?<![\w.])(?:0[xX][0-9A-Fa-f]+|\d+)(?![\w.])", clean[body + 1 :]):
        absolute_start = body + 1 + match.start()
        absolute_end = body + 1 + match.end()
        line_start = clean.rfind("\n", 0, absolute_start) + 1
        line_end = clean.find("\n", absolute_end)
        if line_end < 0:
            line_end = len(clean)
        line = clean[line_start:line_end]
        if line.lstrip().startswith("#") or "static_assert" in line:
            continue
        candidates.append((absolute_start, absolute_end, clean[absolute_start:absolute_end]))
    if not candidates:
        raise RuntimeError("no executable literal candidate")
    selected = candidates[len(candidates) // 2]
    start, end, old = selected
    value = int(old, 0)
    new_value = value + 1 if value < 2**31 - 1 else value - 1
    replacement = hex(new_value) if old.lower().startswith("0x") else str(new_value)
    return (
        source[:start] + replacement + source[end:],
        f"executable_integer_literal:{old}->{replacement}:offset={start}",
    )


def _loop_bound_flip(source: str) -> tuple[str, str]:
    clean = _mask_comments(source)
    patterns = (
        re.compile(r"\bfor\s*\([^;]*;[^;]*?(?P<op><|>)\s*[^;)]*;"),
        re.compile(r"\bwhile\s*\([^)]*?(?P<op><|>)\s*[^)]*\)"),
    )
    matches = [match for pattern in patterns for match in pattern.finditer(clean)]
    for match in sorted(matches, key=lambda item: item.start()):
        op_start = match.start("op")
        line_start = clean.rfind("\n", 0, op_start) + 1
        if clean[line_start:op_start].lstrip().startswith("#"):
            continue
        replacement = "<=" if match.group("op") == "<" else ">="
        return (
            source[:op_start] + replacement + source[op_start + 1 :],
            f"loop_bound_flip:{match.group('op')}->{replacement}:offset={op_start}",
        )
    raise RuntimeError("no loop-bound candidate")


MUTATORS: dict[str, Callable[[str, str], tuple[str, str]]] = {
    "early_return": lambda source, top: _inject_early_return(source, top, 91),
    "literal": _semantic_literal_mutation,
    "comparison": lambda source, top: _comparison_flip(source),
    "loop_bound": lambda source, top: _loop_bound_flip(source),
}


def _tool_record(result: Any) -> dict[str, Any]:
    log = str(getattr(result, "log", "") or "")
    return {
        "ok": bool(getattr(result, "ok", False)),
        "phase": getattr(result, "phase", None),
        "return_code": getattr(result, "return_code", None),
        "elapsed_s": round(float(getattr(result, "elapsed_s", 0.0)), 3),
        "log_tail": log[-8000:],
    }


def _runtime_observation(build_dir: Path, fixture_names: set[str]) -> dict[str, Any]:
    executables = sorted(build_dir.glob("**/csim.exe"))
    if len(executables) != 1:
        return {
            "available": False,
            "reason": f"expected_one_csim_executable_found_{len(executables)}",
        }
    executable = executables[0].resolve()
    completed = subprocess.run(
        [str(executable)],
        cwd=executable.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    stdout = completed.stdout.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    stderr = completed.stderr.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    output_hashes: dict[str, str] = {}
    for path in sorted(executable.parent.iterdir()):
        if not path.is_file() or path.name in fixture_names:
            continue
        if path.name == "csim.exe" or path.suffix.lower() in {".o", ".log", ".tcl"}:
            continue
        if not re.match(r"(?i)^(?:output|out|result)", path.name):
            continue
        output_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    digest_payload = (
        b"stdout\0"
        + stdout
        + b"\0stderr\0"
        + stderr
        + b"\0files\0"
        + json.dumps(output_hashes, sort_keys=True).encode("utf-8")
    )
    return {
        "available": True,
        "return_code": completed.returncode,
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "output_file_sha256": output_hashes,
        "has_observable_output": bool(stdout or stderr or output_hashes),
        "observable_sha256": hashlib.sha256(digest_payload).hexdigest(),
    }


def _run_csim(task: Any, source: str, build_dir: Path, workspace_root: Path) -> dict[str, Any]:
    files = task.assemble(source, task.hidden_tb_code, task.hidden_tb_name)
    result = CSimTool(workspace_root=workspace_root).run(
        build_dir,
        files,
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
        data_files=getattr(task, "hidden_data_files", None) or None,
    )
    record = _tool_record(result)
    if record["ok"]:
        record["runtime_observation"] = _runtime_observation(
            build_dir, set((getattr(task, "hidden_data_files", None) or {}).keys())
        )
    return record


def validate_one(
    task_dir: Path,
    output_root: Path,
    variants: list[str],
) -> dict[str, Any]:
    task = load_task(task_dir)
    normalize_task_testbench_data(task, include_hidden=True)
    spec = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    if task.reference_code is None:
        raise RuntimeError(f"{task.id}: reference source missing")

    task_root = output_root / "tasks" / task.id
    checkpoint = task_root / "mutation_evidence.json"
    if checkpoint.is_file():
        existing = json.loads(checkpoint.read_text(encoding="utf-8"))
        if existing.get("schema_version") == 3 and existing.get("requested_variants") == variants:
            return existing

    started = time.monotonic()
    reference = task.reference_code
    reference_result = _run_csim(
        task, reference, task_root / "reference_hidden_csim", output_root.resolve()
    )
    baseline_result = _run_csim(
        task, task.kernel_code, task_root / "baseline_hidden_csim", output_root.resolve()
    )
    mutation_records: list[dict[str, Any]] = []
    for variant in variants:
        try:
            mutant, derivation = MUTATORS[variant](reference, task.top)
        except RuntimeError as exc:
            mutation_records.append(
                {"variant": variant, "generated": False, "reason": str(exc)}
            )
            continue
        interface = InterfaceValidator.from_source(task.top, reference).validate(mutant)
        record: dict[str, Any] = {
            "variant": variant,
            "generated": True,
            "derivation": derivation,
            "source_sha256": _sha256_text(mutant),
            "distinct_from_reference": mutant != reference,
            "interface_preserved": bool(interface.ok),
        }
        if not interface.ok:
            record["outcome"] = "invalid_interface"
        else:
            result = _run_csim(
                task,
                mutant,
                task_root / f"mutant_{variant}_hidden_csim",
                output_root.resolve(),
            )
            record["csim"] = result
            record["outcome"] = "survived" if result["ok"] else "rejected_by_hidden_csim"
            if result["ok"]:
                reference_observation = reference_result.get("runtime_observation") or {}
                mutant_observation = result.get("runtime_observation") or {}
                comparable = bool(
                    reference_observation.get("available")
                    and reference_observation.get("has_observable_output")
                    and mutant_observation.get("available")
                )
                record["differential_oracle_comparable"] = comparable
                record["differential_outcome"] = (
                    "rejected_by_reference_observation"
                    if comparable
                    and mutant_observation.get("observable_sha256")
                    != reference_observation.get("observable_sha256")
                    else "survived_reference_observation"
                    if comparable
                    else "no_observable_output"
                )
        mutation_records.append(record)

    generated = [record for record in mutation_records if record.get("generated")]
    valid_interface = [record for record in generated if record.get("interface_preserved")]
    survived = [record for record in valid_interface if record.get("outcome") == "survived"]
    rejected = [
        record for record in valid_interface if record.get("outcome") == "rejected_by_hidden_csim"
    ]
    differential_rejected = [
        record
        for record in survived
        if record.get("differential_outcome") == "rejected_by_reference_observation"
    ]
    observable_survivors = [
        record
        for record in survived
        if record.get("differential_outcome") == "survived_reference_observation"
    ]
    expected = str(spec.get("expected_baseline_state", ""))
    baseline_hidden_expected = (
        not baseline_result["ok"]
        if expected in {"compile_fail", "csim_fail"}
        else baseline_result["ok"]
    )
    payload = {
        "schema_version": 3,
        "purpose": "track_a_hidden_testbench_mutation_probe",
        "task_id": task.id,
        "category": str(spec["track_a_category"]),
        "requested_variants": variants,
        "reference_hidden_csim": reference_result,
        "reference_hidden_pass": reference_result["ok"],
        "baseline_hidden_csim": baseline_result,
        "baseline_hidden_matches_expected_csim_state": baseline_hidden_expected,
        "generated_mutant_count": len(generated),
        "interface_preserving_mutant_count": len(valid_interface),
        "rejected_by_hidden_csim_count": len(rejected),
        "surviving_mutant_count": len(survived),
        "differentially_rejected_survivor_count": len(differential_rejected),
        "observable_survivor_count": len(observable_survivors),
        "effective_survivor_count_with_differential_oracle": len(survived)
        - len(differential_rejected),
        "mutation_rejection_rate": (
            len(rejected) / len(valid_interface) if valid_interface else None
        ),
        "mutations": mutation_records,
        "elapsed_s": round(time.monotonic() - started, 3),
    }
    _atomic_json(checkpoint, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, default=Path("tasks/track_a_150_v2"))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument(
        "--variants",
        default="early_return,literal,comparison,loop_bound",
        help="Comma-separated mutation variants.",
    )
    parser.add_argument(
        "--sample-per-category",
        type=int,
        default=0,
        help="Select an evenly spaced deterministic sample within each category.",
    )
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    variants = [item.strip() for item in args.variants.split(",") if item.strip()]
    unknown = sorted(set(variants) - set(MUTATORS))
    if unknown:
        raise SystemExit(f"unknown variants: {', '.join(unknown)}")
    selected = set(args.task_id)
    task_dirs = [path.parent for path in sorted(args.task_root.glob("*/task.toml"))]
    if selected:
        task_dirs = [path for path in task_dirs if path.name in selected]
        missing = selected - {path.name for path in task_dirs}
        if missing:
            raise SystemExit(f"unknown task ids: {', '.join(sorted(missing))}")
    elif args.sample_per_category:
        by_category: dict[str, list[Path]] = defaultdict(list)
        for path in task_dirs:
            spec = tomllib.loads((path / "task.toml").read_text(encoding="utf-8"))
            by_category[str(spec["track_a_category"])].append(path)
        sampled: list[Path] = []
        for category in sorted(by_category):
            paths = by_category[category]
            count = min(args.sample_per_category, len(paths))
            if count == 1:
                indices = [len(paths) // 2]
            else:
                indices = [round(index * (len(paths) - 1) / (count - 1)) for index in range(count)]
            sampled.extend(paths[index] for index in indices)
        task_dirs = sorted(set(sampled))
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        raise SystemExit("invalid shard index/count")
    task_dirs = [
        path for index, path in enumerate(task_dirs)
        if index % args.shard_count == args.shard_index
    ]

    records = [validate_one(path, args.output_root, variants) for path in task_dirs]
    summary = {
        "schema_version": 1,
        "purpose": "track_a_hidden_testbench_mutation_probe_summary",
        "task_root": str(args.task_root),
        "output_root": str(args.output_root),
        "requested_variants": variants,
        "task_count": len(records),
        "reference_hidden_pass_count": sum(item["reference_hidden_pass"] for item in records),
        "baseline_hidden_expected_count": sum(
            item["baseline_hidden_matches_expected_csim_state"] for item in records
        ),
        "interface_preserving_mutant_count": sum(
            item["interface_preserving_mutant_count"] for item in records
        ),
        "rejected_by_hidden_csim_count": sum(
            item["rejected_by_hidden_csim_count"] for item in records
        ),
        "surviving_mutant_count": sum(item["surviving_mutant_count"] for item in records),
        "differentially_rejected_survivor_count": sum(
            item["differentially_rejected_survivor_count"] for item in records
        ),
        "effective_survivor_count_with_differential_oracle": sum(
            item["effective_survivor_count_with_differential_oracle"] for item in records
        ),
        "tasks_with_surviving_mutants": [
            item["task_id"] for item in records if item["surviving_mutant_count"]
        ],
        "tasks": {
            item["task_id"]: {
                "category": item["category"],
                "reference_hidden_pass": item["reference_hidden_pass"],
                "baseline_hidden_matches_expected_csim_state": item[
                    "baseline_hidden_matches_expected_csim_state"
                ],
                "mutation_rejection_rate": item["mutation_rejection_rate"],
                "surviving_mutant_count": item["surviving_mutant_count"],
                "differentially_rejected_survivor_count": item[
                    "differentially_rejected_survivor_count"
                ],
                "effective_survivor_count_with_differential_oracle": item[
                    "effective_survivor_count_with_differential_oracle"
                ],
                "evidence": str(
                    args.output_root / "tasks" / item["task_id"] / "mutation_evidence.json"
                ),
            }
            for item in records
        },
    }
    summary_name = (
        "mutation_summary.json"
        if args.shard_count == 1
        else f"mutation_summary_shard_{args.shard_index:02d}.json"
    )
    _atomic_json(args.output_root / summary_name, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
