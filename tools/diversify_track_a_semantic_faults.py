#!/usr/bin/env python3
"""Select test-detectable semantic faults for functional and CoSim repair tasks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

from agent.candidate.validator import InterfaceValidator
from agent.runner import CSimTool
from agent.testbench import normalize_task_testbench_data
from llm4hls.task import load_task
from build_track_a_150 import _inject_early_return


CATEGORIES = {"functional_repair", "structural_cosim_repair"}
VARIANTS = ("arithmetic", "literal", "comparison", "return_value", "early_return")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def run_csim(task: Any, source: str, hidden: bool, build_dir: Path) -> dict[str, Any]:
    tb_code = task.hidden_tb_code if hidden else task.public_tb_code
    tb_name = task.hidden_tb_name if hidden else task.public_tb_name
    data = (
        getattr(task, "hidden_data_files", None)
        if hidden
        else getattr(task, "public_data_files", None)
    )
    result = CSimTool(workspace_root=build_dir.parents[3].resolve()).run(
        build_dir,
        task.assemble(source, tb_code, tb_name),
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
        data_files=data or None,
    )
    log = str(getattr(result, "log", "") or "")
    return {
        "ok": bool(getattr(result, "ok", False)),
        "phase": getattr(result, "phase", None),
        "return_code": getattr(result, "return_code", None),
        "log_tail": log[-4000:],
    }


def mask_noncode(source: str) -> str:
    """Preserve offsets while hiding comments and string/character literals."""

    pattern = re.compile(
        r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
        re.S,
    )
    return pattern.sub(
        lambda match: "".join("\n" if char == "\n" else " " for char in match.group()),
        source,
    )


def mutation_candidates(source: str, top: str, family: str) -> list[tuple[str, str]]:
    """Enumerate local, interface-preserving candidates for one operator family."""

    if family == "early_return":
        mutant, derivation = _inject_early_return(source, top, 91)
        return [(mutant, derivation)]

    clean = mask_noncode(source)
    top_match = re.search(rf"\b{re.escape(top)}\s*\(", clean)
    if top_match is None:
        raise RuntimeError("top function not found")
    body = clean.find("{", top_match.end())
    if body < 0:
        raise RuntimeError("top function body not found")
    results: list[tuple[str, str]] = []

    if family == "comparison":
        pattern = re.compile(r"(?<![<>=!])(?:==|!=|<=|>=)(?![=<>])")
        replacements = {"==": "!=", "!=": "==", "<=": ">", ">=": "<"}
        for match in pattern.finditer(clean[body + 1 :]):
            start = body + 1 + match.start()
            end = body + 1 + match.end()
            old = source[start:end]
            new = replacements[old]
            results.append(
                (
                    source[:start] + new + source[end:],
                    f"comparison_flip:{old}->{new}:offset={start}",
                )
            )
    elif family == "literal":
        pattern = re.compile(r"(?<![\w.])(?:0[xX][0-9A-Fa-f]+|\d+)(?![\w.])")
        for match in pattern.finditer(clean[body + 1 :]):
            start = body + 1 + match.start()
            end = body + 1 + match.end()
            line_start = clean.rfind("\n", 0, start) + 1
            line_end = clean.find("\n", end)
            if line_end < 0:
                line_end = len(clean)
            line = clean[line_start:line_end]
            if line.lstrip().startswith("#") or "static_assert" in line:
                continue
            old = source[start:end]
            value = int(old, 0)
            new_value = value + 1 if value in {0, 1} else value ^ 1
            new = hex(new_value) if old.lower().startswith("0x") else str(new_value)
            results.append(
                (
                    source[:start] + new + source[end:],
                    f"integer_literal_bitflip:{old}->{new}:offset={start}",
                )
            )
    elif family == "arithmetic":
        pattern = re.compile(
            r"(?<=[A-Za-z0-9_\]\)])(?P<space1>\s*)"
            r"(?P<op>\+=|-=|\*=|\+|-|\*|\^|\||&)"
            r"(?P<space2>\s*)(?=[A-Za-z0-9_(\[])"
        )
        replacements = {
            "+=": "-=", "-=": "+=", "*=": "+=",
            "+": "-", "-": "+", "*": "+", "^": "|", "|": "^", "&": "^",
        }
        for match in pattern.finditer(clean[body + 1 :]):
            start = body + 1 + match.start("op")
            end = body + 1 + match.end("op")
            old = source[start:end]
            new = replacements[old]
            results.append(
                (
                    source[:start] + new + source[end:],
                    f"arithmetic_operator:{old}->{new}:offset={start}",
                )
            )
    elif family == "return_value":
        pattern = re.compile(r"\breturn\s+(?P<expr>[^;{}\n]+);")
        for match in pattern.finditer(clean[body + 1 :]):
            start = body + 1 + match.start("expr")
            end = body + 1 + match.end("expr")
            old = source[start:end].strip()
            new = f"({old}) + 1"
            results.append(
                (
                    source[:start] + new + source[end:],
                    f"return_value_offset:+1:offset={start}",
                )
            )
    else:
        raise RuntimeError(f"unknown mutation family: {family}")

    # Bound validation cost while spreading choices across the source.
    if len(results) > 16:
        indices = [round(index * (len(results) - 1) / 15) for index in range(16)]
        results = [results[index] for index in indices]
    return results


def select_one(task_dir: Path, evidence_root: Path, ordinal: int) -> dict[str, Any]:
    spec = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    category = str(spec["track_a_category"])
    task = load_task(task_dir)
    normalize_task_testbench_data(task, include_hidden=True)
    reference = task.reference_code
    if reference is None:
        raise RuntimeError(f"{task.id}: reference missing")

    semantic_families = list(VARIANTS[:-1])
    rotation = ordinal % len(semantic_families)
    preferred = semantic_families[rotation:] + semantic_families[:rotation] + [
        "early_return"
    ]
    attempts: list[dict[str, Any]] = []
    selected: tuple[str, str, str] | None = None
    attempt_index = 0
    for variant in preferred:
        try:
            candidates = mutation_candidates(reference, task.top, variant)
        except RuntimeError as exc:
            attempts.append({"variant": variant, "generated": False, "reason": str(exc)})
            continue
        if not candidates:
            attempts.append(
                {"variant": variant, "generated": False, "reason": "no_candidate"}
            )
            continue
        # Rotate sites deterministically so the corpus does not always use the
        # first statement of every source file.
        site_rotation = ordinal % len(candidates)
        candidates = candidates[site_rotation:] + candidates[:site_rotation]
        for mutant, derivation in candidates:
            attempt_index += 1
            interface = InterfaceValidator.from_source(task.top, reference).validate(mutant)
            attempt: dict[str, Any] = {
                "variant": variant,
                "generated": True,
                "derivation": derivation,
                "mutant_sha256": sha256_text(mutant),
                "interface_preserved": bool(interface.ok),
            }
            if interface.ok:
                base = (
                    evidence_root
                    / "tasks"
                    / task.id
                    / "attempts_v2"
                    / f"{attempt_index:02d}_{variant}"
                )
                attempt["public"] = run_csim(task, mutant, False, base / "public")
                attempt["hidden"] = run_csim(task, mutant, True, base / "hidden")
                attempt["selected"] = all(
                    record.get("phase") == "runtime_fail"
                    for record in (attempt["public"], attempt["hidden"])
                )
            else:
                attempt["selected"] = False
            attempts.append(attempt)
            if attempt["selected"]:
                selected = (variant, derivation, mutant)
                break
        if selected is not None:
            break
    if selected is None:
        raise RuntimeError(f"{task.id}: no public-and-hidden-detectable mutation")

    variant, derivation, mutant = selected
    if category == "structural_cosim_repair":
        starter = (
            "#ifndef __SYNTHESIS__\n"
            + reference
            + "\n#else\n"
            + mutant
            + "\n#endif\n"
        )
        fault_derivation = "synthesis_only_" + derivation
    else:
        starter = mutant
        fault_derivation = derivation

    kernel_path = task_dir / str(spec["kernel_file"])
    kernel_path.write_text(starter, encoding="utf-8")
    toml_path = task_dir / "task.toml"
    toml_text = toml_path.read_text(encoding="utf-8")
    toml_text, count = re.subn(
        r'^fault_derivation = ".*"$',
        'fault_derivation = ' + json.dumps(fault_derivation),
        toml_text,
        count=1,
        flags=re.M,
    )
    if count != 1:
        raise RuntimeError(f"{task.id}: fault_derivation field not found")
    toml_path.write_text(toml_text, encoding="utf-8")

    payload = {
        "schema_version": 1,
        "purpose": "track_a_semantic_fault_selection",
        "task_id": task.id,
        "category": category,
        "preferred_order": preferred,
        "selected_variant": variant,
        "selected_derivation": fault_derivation,
        "reference_sha256": sha256_text(reference),
        "starter_sha256": sha256_text(starter),
        "mutant_sha256": sha256_text(mutant),
        "interface_preserved": True,
        "public_and_hidden_detect_mutant": True,
        "attempts": attempts,
    }
    atomic_json(evidence_root / "tasks" / task.id / "selection.json", payload)
    return payload


def finalize(task_root: Path, evidence_root: Path) -> int:
    records = []
    for task_dir in sorted(task_root.glob("*/")):
        toml_path = task_dir / "task.toml"
        if not toml_path.is_file():
            continue
        spec = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        if spec.get("track_a_category") not in CATEGORIES:
            continue
        record_path = evidence_root / "tasks" / task_dir.name / "selection.json"
        records.append(json.loads(record_path.read_text(encoding="utf-8")))
    if len(records) != 50:
        raise RuntimeError(f"expected 50 selection records, found {len(records)}")

    manifest_path = task_root / "candidate_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_id = {record["task_id"]: record for record in records}
    for item in manifest["tasks"]:
        record = by_id.get(item["task_id"])
        if record:
            item["fault_derivation"] = record["selected_derivation"]
            item["starter_sha256"] = record["starter_sha256"]
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    counts: dict[str, int] = {}
    for record in records:
        variant = record["selected_variant"]
        counts[variant] = counts.get(variant, 0) + 1
    summary = {
        "schema_version": 1,
        "purpose": "track_a_semantic_fault_selection_summary",
        "task_count": len(records),
        "all_public_and_hidden_detect_mutant": all(
            record["public_and_hidden_detect_mutant"] for record in records
        ),
        "selected_variant_counts": dict(sorted(counts.items())),
        "tasks": {
            record["task_id"]: {
                "category": record["category"],
                "variant": record["selected_variant"],
                "derivation": record["selected_derivation"],
                "starter_sha256": record["starter_sha256"],
                "evidence": str(
                    evidence_root / "tasks" / record["task_id"] / "selection.json"
                ),
            }
            for record in records
        },
    }
    atomic_json(evidence_root / "semantic_fault_selection_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        return finalize(args.task_root, args.evidence_root)
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        raise SystemExit("invalid shard index/count")

    task_dirs = []
    for path in sorted(args.task_root.glob("*/task.toml")):
        spec = tomllib.loads(path.read_text(encoding="utf-8"))
        if spec.get("track_a_category") in CATEGORIES:
            task_dirs.append(path.parent)
    selected = [
        path for index, path in enumerate(task_dirs)
        if index % args.shard_count == args.shard_index
    ]
    records = [
        select_one(path, args.evidence_root, task_dirs.index(path)) for path in selected
    ]
    shard = {
        "schema_version": 1,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "task_count": len(records),
        "selected_variant_counts": {
            variant: sum(record["selected_variant"] == variant for record in records)
            for variant in VARIANTS
        },
        "task_ids": [record["task_id"] for record in records],
    }
    atomic_json(
        args.evidence_root / f"semantic_fault_selection_shard_{args.shard_index:02d}.json",
        shard,
    )
    print(json.dumps(shard, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
