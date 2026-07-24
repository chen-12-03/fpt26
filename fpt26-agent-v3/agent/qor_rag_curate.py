#!/usr/bin/env python3
"""Promote measured public submission candidates into QoR knowledge cases.

This utility reads only explicitly supplied submission ``run_report.json``
files.  It never reads sibling task sources, hidden tests, reference
implementations, or evaluator reports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from agent.knowledge import (
    KNOWLEDGE_SCHEMA_VERSION,
    KnowledgeEntry,
    KnowledgeValidationError,
)


_FORBIDDEN_COMPONENTS = frozenset({"hidden", "reference", "evaluator"})


def curate_submission_report(report_path: Path) -> list[KnowledgeEntry]:
    _require_public_submission_path(report_path)
    raw = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise KnowledgeValidationError("submission report must be an object")
    role = str(raw.get("run_role", "") or "").lower()
    if role and role != "submission":
        raise KnowledgeValidationError(
            f"report role must be submission, got {role!r}"
        )
    if raw.get("status") != "completed":
        return []
    public_gate = (
        raw.get("gates", {}).get("public_acceptance", {})
        if isinstance(raw.get("gates"), Mapping)
        else {}
    )
    final_artifact = (
        raw.get("final_artifact", {})
        if isinstance(raw.get("final_artifact"), Mapping)
        else {}
    )
    if public_gate.get("ok") is not True or final_artifact.get(
        "fully_verified"
    ) is not True:
        return []

    optimization = (
        raw.get("optimization_metrics", {})
        if isinstance(raw.get("optimization_metrics"), Mapping)
        else {}
    )
    candidates = optimization.get("synth_candidates", [])
    if not isinstance(candidates, list):
        return []

    task_id = str(raw.get("task_id", "")).strip()
    if not task_id:
        raise KnowledgeValidationError("submission report lacks task_id")
    target = raw.get("target", {}) if isinstance(raw.get("target"), Mapping) else {}
    toolchain = (
        raw.get("toolchain", {})
        if isinstance(raw.get("toolchain"), Mapping)
        else {}
    )
    vitis_version = _vitis_version(toolchain)
    semantic_tags = _semantic_tags(task_id)
    entries: list[KnowledgeEntry] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping) or candidate.get("is_baseline"):
            continue
        decision = str(candidate.get("decision", "")).upper()
        if decision not in {"ACCEPTED", "REJECTED"}:
            continue
        before = candidate.get("q_hw_before")
        after = candidate.get("q_hw_after")
        if not isinstance(before, (int, float)) or not isinstance(
            after, (int, float)
        ):
            continue
        validation = (
            dict(candidate.get("validation", {}))
            if isinstance(candidate.get("validation"), Mapping)
            else {}
        )
        if not _validation_complete(validation):
            continue
        action = (
            dict(candidate.get("action", {}))
            if isinstance(candidate.get("action"), Mapping)
            else {}
        )
        family = _action_family(action)
        round_number = int(candidate.get("round", 0) or 0)
        digest = hashlib.sha256(
            json.dumps(
                {
                    "task_id": task_id,
                    "round": round_number,
                    "action": action,
                    "before": before,
                    "after": after,
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:12]
        source = f"submission:{task_id}:{digest}"
        common_evidence = {
            **validation,
            "q_hw_before": before,
            "q_hw_after": after,
            "latency": candidate.get("latency"),
            "clock_ns": candidate.get("clock_ns"),
            "resources": candidate.get("resources", {}),
            "loop_metrics": candidate.get("loop_metrics", []),
            "source_metadata": candidate.get("source_metadata", {}),
            "target_part": target.get("part"),
            "submission_artifact_sha256": final_artifact.get("sha256"),
        }
        if decision == "ACCEPTED" and after > before:
            record = {
                "id": f"submission.{task_id}.r{round_number}.{digest}",
                "kind": "verified_case",
                "family": family,
                "preconditions": _case_preconditions(candidate),
                "action": _action_text(action),
                "expected_signal": (
                    f"Measured Q_HW improved from {before:.6f} to {after:.6f}."
                ),
                "contraindications": [
                    "Reuse only when source structure, bottleneck, target part, and Vitis version are compatible.",
                    "Real validation and Q_HW must still decide acceptance.",
                ],
                "source": source,
                "confidence": "high",
                "vitis_version": vitis_version,
                "status": "verified_case",
                "tags": [
                    family,
                    "measured",
                    "q_hw_improved",
                    *semantic_tags,
                ],
                "evidence": common_evidence,
            }
        else:
            record = {
                "id": f"submission.{task_id}.r{round_number}.negative.{digest}",
                "kind": "failure_case",
                "family": family,
                "preconditions": _case_preconditions(candidate),
                "action": "Avoid repeating measured action: " + _action_text(action),
                "expected_signal": (
                    f"Avoid a candidate whose measured Q_HW was {after:.6f} "
                    f"versus current best {before:.6f}."
                ),
                "contraindications": [
                    "This negative case does not prohibit a smaller or structurally different measured action.",
                    "Do not generalize across incompatible targets or tool versions.",
                ],
                "source": source,
                "confidence": "high",
                "vitis_version": vitis_version,
                "status": "verified_failure",
                "tags": [
                    family,
                    "measured",
                    "q_hw_rejected",
                    *semantic_tags,
                ],
                "evidence": {
                    **common_evidence,
                    "observed_failure": True,
                    "stage": "q_hw_selection",
                },
            }
        entries.append(KnowledgeEntry.from_dict(record))
    return entries


def write_case_file(
    entries: list[KnowledgeEntry], output: Path, *, replace: bool
) -> None:
    _require_safe_path(output)
    if output.exists() and not replace:
        raise FileExistsError(
            f"{output} already exists; pass --replace after reviewing provenance"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for entry in sorted(entries, key=lambda item: item.id):
        records.append(
            {
                "id": entry.id,
                "kind": entry.kind,
                "family": entry.family,
                "preconditions": list(entry.preconditions),
                "action": entry.action,
                "expected_signal": entry.expected_signal,
                "contraindications": list(entry.contraindications),
                "source": entry.source,
                "confidence": entry.confidence,
                "vitis_version": entry.vitis_version,
                "status": entry.status,
                "tags": list(entry.tags),
                "evidence": dict(entry.evidence),
            }
        )
    output.write_text(
        json.dumps(
            {"schema_version": KNOWLEDGE_SCHEMA_VERSION, "entries": records},
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _require_public_submission_path(path: Path) -> None:
    _require_safe_path(path)
    if path.name != "run_report.json":
        raise KnowledgeValidationError(
            "case promotion accepts only submission run_report.json files"
        )
    if "submission" not in {part.lower() for part in path.parts}:
        raise KnowledgeValidationError(
            "case promotion accepts only paths under a submission directory"
        )


def _require_safe_path(path: Path) -> None:
    parts = {part.lower() for part in path.resolve(strict=False).parts}
    forbidden = parts & _FORBIDDEN_COMPONENTS
    if forbidden:
        raise KnowledgeValidationError(
            f"forbidden private path component: {sorted(forbidden)}"
        )


def _validation_complete(validation: Mapping[str, Any]) -> bool:
    for key in (
        "interface_ok",
        "csim_ok",
        "synth_ok",
        "frequency_ok",
        "resource_ok",
    ):
        if validation.get(key) is not True:
            return False
    return not validation.get("cosim_required") or validation.get(
        "cosim_ok"
    ) is True


def _action_family(action: Mapping[str, Any]) -> str:
    families = action.get("families", [])
    if isinstance(families, list) and families:
        return str(families[0]).strip().lower()
    return "source_restructure" if action.get("source_changed") else "unknown"


def _action_text(action: Mapping[str, Any]) -> str:
    return json.dumps(
        {
            "families": action.get("families", []),
            "added_pragmas": action.get("added_pragmas", []),
            "removed_pragmas": action.get("removed_pragmas", []),
            "source_changed": bool(action.get("source_changed")),
        },
        sort_keys=True,
        separators=(",", ":"),
    )[:1_200]


def _case_preconditions(candidate: Mapping[str, Any]) -> list[str]:
    metadata = candidate.get("source_metadata", {})
    loop_count = (
        metadata.get("loop_count", "unknown")
        if isinstance(metadata, Mapping)
        else "unknown"
    )
    array_count = (
        metadata.get("array_count", "unknown")
        if isinstance(metadata, Mapping)
        else "unknown"
    )
    return [
        f"Comparable source metadata has loop_count={loop_count} and array_count={array_count}.",
        "The measured bottleneck, resource headroom, target part, and Vitis version are compatible.",
    ]


def _vitis_version(toolchain: Mapping[str, Any]) -> str:
    for key in (
        "vitis_version",
        "preflight_vitis_version",
        "required_vitis_version",
        "version",
        "tool_version",
    ):
        value = toolchain.get(key)
        if value:
            return str(value)
    observed = toolchain.get("observed_vitis_versions")
    if isinstance(observed, list) and observed:
        return str(observed[0])
    return "unknown"


def _semantic_tags(task_id: str) -> list[str]:
    lowered = task_id.lower()
    tags = []
    for token, tag in (
        ("dotproduct", "dot_product"),
        ("popcount", "popcount"),
        ("gemm", "gemm"),
        ("matmul", "gemm"),
        ("stencil", "stencil"),
        ("cordic", "cordic"),
    ):
        if token in lowered and tag not in tags:
            tags.append(tag)
    return tags


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    entries: list[KnowledgeEntry] = []
    seen: set[str] = set()
    for report in args.report:
        for entry in curate_submission_report(report):
            if entry.id not in seen:
                seen.add(entry.id)
                entries.append(entry)
    write_case_file(entries, args.output, replace=args.replace)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "entry_count": len(entries),
                "verified_cases": sum(
                    entry.kind == "verified_case" for entry in entries
                ),
                "failure_cases": sum(
                    entry.kind == "failure_case" for entry in entries
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
