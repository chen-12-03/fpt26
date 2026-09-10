#!/usr/bin/env python3
"""Audit Track-A public/hidden testbench independence and check strength.

This is deliberately a conservative static audit.  It can prove obvious
failures (for example, byte-identical public and hidden assets), but it does
not claim semantic independence.  Dynamic reference/baseline/mutation runs
remain mandatory before a task corpus can be frozen.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


TEXT_DATA_SUFFIXES = {
    ".data", ".dat", ".txt", ".csv", ".hex", ".in", ".out", ".golden",
    ".coe", ".mif",
}
CHECK_PATTERNS = {
    "assert": re.compile(r"\bassert\s*\("),
    "nonzero_return": re.compile(r"\breturn\s+(?:-?[1-9]\d*|EXIT_FAILURE)\s*;"),
    "variable_return": re.compile(r"\breturn\s+[A-Za-z_]\w*\s*;"),
    "error_accumulator_return": re.compile(
        r"\breturn\s+(?:err(?:or)?s?|fail(?:ures?)?|mismatch(?:es?)?|status)\s*;",
        re.IGNORECASE,
    ),
    "comparison": re.compile(r"(?:!=|==|\bfabs\s*\(|\babs\s*\()"),
    "failure_word": re.compile(r"\b(?:fail(?:ed|ure)?|error|mismatch|incorrect)\b", re.I),
}

# The transcript hardener appends one of these footer forms.  If an imported
# main() already returned and that return was not removed, the apparent oracle
# exists textually but can never execute.  Keep this explicit regression gate
# separate from the looser self-check signal heuristic.
UNREACHABLE_GENERATED_ORACLE = re.compile(
    r"\breturn\s+[^;]+;\s*(?:"
    r"std::fflush\s*\(|"
    r"std::fprintf\s*\(\s*stderr\s*,\s*\"\\nTRACK_A_OBSERVATION_BEGIN"
    r")",
    re.S,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tokens(text: str) -> list[str]:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return re.findall(
        r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|'
        r"[A-Za-z_]\w*|0[xX][0-9A-Fa-f]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|"
        r"==|!=|<=|>=|&&|\|\||<<|>>|[-+*/%<>{}()[\],;:=&|^!~?.]",
        text,
    )


def _shingles(tokens: list[str], width: int = 5) -> set[tuple[str, ...]]:
    if len(tokens) < width:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[index : index + width]) for index in range(len(tokens) - width + 1)}


def _jaccard(left: set[Any], right: set[Any]) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def _check_signals(text: str) -> dict[str, bool]:
    return {name: bool(pattern.search(text)) for name, pattern in CHECK_PATTERNS.items()}


def _data_files(root: Path, *, public: bool) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in root.iterdir():
        if not path.is_file() or path.suffix.lower() not in TEXT_DATA_SUFFIXES:
            continue
        if path.name.endswith(":Zone.Identifier"):
            continue
        result[path.name] = path
    if public:
        return result
    return result


def audit_task(task_dir: Path) -> dict[str, Any]:
    spec = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    public_path = task_dir / str(spec["public_tb"])
    hidden_path = task_dir / "hidden" / str(spec["hidden_tb"])
    public_text = public_path.read_text(encoding="utf-8", errors="replace")
    hidden_text = hidden_path.read_text(encoding="utf-8", errors="replace")
    public_tokens = _tokens(public_text)
    hidden_tokens = _tokens(hidden_text)

    public_data = _data_files(task_dir, public=True)
    hidden_data = _data_files(task_dir / "hidden", public=False)
    shared_data_names = sorted(set(public_data) & set(hidden_data))
    equal_data_names = [
        name for name in shared_data_names if _sha256(public_data[name]) == _sha256(hidden_data[name])
    ]
    distinct_data_names = sorted(set(shared_data_names) - set(equal_data_names))
    hidden_only_data_names = sorted(set(hidden_data) - set(public_data))

    public_signals = _check_signals(public_text)
    hidden_signals = _check_signals(hidden_text)
    public_unreachable_generated_oracle = bool(
        UNREACHABLE_GENERATED_ORACLE.search(public_text)
    )
    hidden_unreachable_generated_oracle = bool(
        UNREACHABLE_GENERATED_ORACLE.search(hidden_text)
    )
    public_self_check_candidate = (
        public_signals["assert"]
        or public_signals["nonzero_return"]
        or public_signals["error_accumulator_return"]
        or (
            public_signals["comparison"]
            and (public_signals["failure_word"] or public_signals["variable_return"])
        )
    )
    hidden_self_check_candidate = (
        hidden_signals["assert"]
        or hidden_signals["nonzero_return"]
        or hidden_signals["error_accumulator_return"]
        or (
            hidden_signals["comparison"]
            and (hidden_signals["failure_word"] or hidden_signals["variable_return"])
        )
    )

    byte_equal = public_path.read_bytes() == hidden_path.read_bytes()
    distinct_hidden_input_asset = bool(distinct_data_names or hidden_only_data_names)
    if byte_equal and not distinct_hidden_input_asset:
        independence_class = "public_clone"
    elif byte_equal and distinct_hidden_input_asset:
        independence_class = "shared_harness_distinct_data"
    else:
        independence_class = "distinct_testbench_source"

    # This is intentionally named a candidate: textual difference cannot
    # establish an independent oracle or adequate fault coverage.
    input_independence_candidate = independence_class != "public_clone"
    return {
        "task_id": str(spec["task_id"]),
        "category": str(spec["track_a_category"]),
        "source_suite": str(spec.get("source_task_id", "unknown")).split("__", 1)[0],
        "public_tb": str(spec["public_tb"]),
        "hidden_tb": str(spec["hidden_tb"]),
        "public_sha256": _sha256(public_path),
        "hidden_sha256": _sha256(hidden_path),
        "byte_equal": byte_equal,
        "token_5gram_jaccard": round(
            _jaccard(_shingles(public_tokens), _shingles(hidden_tokens)), 6
        ),
        "public_token_count": len(public_tokens),
        "hidden_token_count": len(hidden_tokens),
        "public_top_call_count": len(
            re.findall(rf"(?<![\w:]){re.escape(str(spec['top']))}\s*\(", public_text)
        ),
        "hidden_top_call_count": len(
            re.findall(rf"(?<![\w:]){re.escape(str(spec['top']))}\s*\(", hidden_text)
        ),
        "public_check_signals": public_signals,
        "hidden_check_signals": hidden_signals,
        "public_self_check_candidate": public_self_check_candidate,
        "hidden_self_check_candidate": hidden_self_check_candidate,
        "public_unreachable_generated_oracle": public_unreachable_generated_oracle,
        "hidden_unreachable_generated_oracle": hidden_unreachable_generated_oracle,
        "public_data_files": sorted(public_data),
        "hidden_data_files": sorted(hidden_data),
        "equal_public_hidden_data_files": equal_data_names,
        "distinct_public_hidden_data_files": distinct_data_names,
        "hidden_only_data_files": hidden_only_data_names,
        "independence_class": independence_class,
        "input_independence_candidate": input_independence_candidate,
        "oracle_independence": "unverified_requires_manual_or_mutation_evidence",
    }


def audit(root: Path) -> dict[str, Any]:
    records = [audit_task(path.parent) for path in sorted(root.glob("*/task.toml"))]
    by_class = Counter(record["independence_class"] for record in records)
    clone_by_category: dict[str, list[str]] = defaultdict(list)
    clone_by_suite: dict[str, list[str]] = defaultdict(list)
    weak_public: list[str] = []
    weak_hidden: list[str] = []
    unreachable_public_oracle: list[str] = []
    unreachable_hidden_oracle: list[str] = []
    for record in records:
        if record["independence_class"] == "public_clone":
            clone_by_category[record["category"]].append(record["task_id"])
            clone_by_suite[record["source_suite"]].append(record["task_id"])
        if not record["public_self_check_candidate"]:
            weak_public.append(record["task_id"])
        if not record["hidden_self_check_candidate"]:
            weak_hidden.append(record["task_id"])
        if record["public_unreachable_generated_oracle"]:
            unreachable_public_oracle.append(record["task_id"])
        if record["hidden_unreachable_generated_oracle"]:
            unreachable_hidden_oracle.append(record["task_id"])

    weak_public_by_category = Counter(
        record["category"] for record in records if not record["public_self_check_candidate"]
    )
    weak_public_by_suite = Counter(
        record["source_suite"] for record in records if not record["public_self_check_candidate"]
    )
    weak_hidden_by_category = Counter(
        record["category"] for record in records if not record["hidden_self_check_candidate"]
    )

    # A static pass is only a prerequisite.  It never upgrades oracle
    # independence or mutation adequacy to verified.
    static_prerequisite_pass = (
        len(records) == 150
        and not clone_by_category
        and not weak_public
        and not weak_hidden
        and not unreachable_public_oracle
        and not unreachable_hidden_oracle
    )
    return {
        "schema_version": 1,
        "purpose": "track_a_testbench_credibility_static_audit",
        "task_root": str(root),
        "task_count": len(records),
        "limitations": [
            "Textual difference does not prove semantic input independence.",
            "Check-signal detection does not prove an oracle is correct.",
            "Dynamic reference, canonical-fault, and mutation testing are mandatory.",
        ],
        "static_prerequisite_pass": static_prerequisite_pass,
        "independence_class_counts": dict(sorted(by_class.items())),
        "public_clone_count": sum(len(ids) for ids in clone_by_category.values()),
        "public_clone_task_ids": [
            record["task_id"]
            for record in records
            if record["independence_class"] == "public_clone"
        ],
        "public_clone_by_category": {
            key: ids for key, ids in sorted(clone_by_category.items())
        },
        "public_clone_by_suite": {key: ids for key, ids in sorted(clone_by_suite.items())},
        "weak_public_count": len(weak_public),
        "weak_public_by_category": dict(sorted(weak_public_by_category.items())),
        "weak_public_by_suite": dict(sorted(weak_public_by_suite.items())),
        "weak_public_task_ids": weak_public,
        "weak_hidden_count": len(weak_hidden),
        "weak_hidden_by_category": dict(sorted(weak_hidden_by_category.items())),
        "weak_hidden_task_ids": weak_hidden,
        "unreachable_public_oracle_count": len(unreachable_public_oracle),
        "unreachable_public_oracle_task_ids": unreachable_public_oracle,
        "unreachable_hidden_oracle_count": len(unreachable_hidden_oracle),
        "unreachable_hidden_oracle_task_ids": unreachable_hidden_oracle,
        "dynamic_gates": {
            "reference_public_and_hidden": "pending",
            "canonical_fault_detected_by_hidden": "pending",
            "mutation_score": "pending",
            "evaluator_asset_physical_isolation": "pending",
        },
        "tasks": {record["task_id"]: record for record in records},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, default=Path("tasks/track_a_150_v2"))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print counts and gate status while retaining the full JSON in --output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = audit(args.task_root)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.summary_only:
        summary_keys = (
            "task_count",
            "static_prerequisite_pass",
            "independence_class_counts",
            "public_clone_count",
            "weak_public_count",
            "weak_public_by_category",
            "weak_public_by_suite",
            "weak_hidden_count",
            "weak_hidden_by_category",
            "unreachable_public_oracle_count",
            "unreachable_hidden_oracle_count",
            "dynamic_gates",
        )
        print(json.dumps({key: payload[key] for key in summary_keys}, indent=2, sort_keys=True))
    else:
        print(rendered, end="")
    return 0 if payload["task_count"] == 150 else 1


if __name__ == "__main__":
    raise SystemExit(main())
