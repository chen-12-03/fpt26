#!/usr/bin/env python3
"""Classify public-HLS tasks whose synth reports lack scoreable metrics."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".h", ".hpp"}
VARIABLE_BOUND_RE = re.compile(
    r"\bfor\s*\([^;]+;[^;]*\b("
    r"size|len|length|num|count|n_elements|elements|rows|cols|"
    r"width|height|iter|rep_count|buf_size|data_size|N"
    r")\b",
    re.IGNORECASE,
)


def audit(
    *,
    manifest_path: Path,
    smoke_path: Path,
    task_root: Path,
    tripcount_summary_path: Path | None = None,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    smoke = _read_json(smoke_path)
    scoreable_gate = _mapping(manifest.get("scoreable_gate"))
    task_ids = [
        item
        for item in scoreable_gate.get("metric_incomplete_task_ids", [])
        if isinstance(item, str) and item
    ]
    smoke_by_task = {
        str(item.get("task_id")): item
        for item in smoke.get("results", [])
        if isinstance(item, dict) and item.get("task_id")
    }
    manifest_by_task = {
        str(item.get("task_id")): item
        for item in manifest.get("validated", [])
        if isinstance(item, dict) and item.get("task_id")
    }
    tripcount_summary = (
        _read_json(tripcount_summary_path)
        if tripcount_summary_path is not None and tripcount_summary_path.exists()
        else None
    )

    records = []
    for task_id in sorted(task_ids):
        record = classify_task(
            task_id=task_id,
            manifest_record=_mapping(manifest_by_task.get(task_id)),
            smoke_record=_mapping(smoke_by_task.get(task_id)),
            task_dir=task_root / task_id,
        )
        records.append(record)

    resolution_counts = Counter(
        str(record["resolution_class"]) for record in records
    )
    signal_counts = Counter(
        signal for record in records for signal in record["signals"]
    )
    input_size_related_count = sum(
        1 for record in records if record["input_size_related"]
    )
    return {
        "schema_version": 1,
        "purpose": "phase2f_public_hls_metric_incomplete_resolution_audit",
        "scope": {
            "policy": "public task packages, manifests, and existing reports only",
            "api_or_vitis_run": False,
            "hidden_reference_or_evaluator_reads": False,
            "scoring_prompt_rag_or_strategy_changed_by_this_audit": False,
        },
        "inputs": {
            "manifest": str(manifest_path),
            "smoke": str(smoke_path),
            "task_root": str(task_root),
            "tripcount_summary": (
                str(tripcount_summary_path)
                if tripcount_summary_path is not None
                else None
            ),
        },
        "summary": {
            "metric_incomplete_count": len(records),
            "input_size_related_count": input_size_related_count,
            "resolution_class_counts": dict(sorted(resolution_counts.items())),
            "signal_counts": dict(sorted(signal_counts.items())),
            "tripcount_patch_restores_scoreable_metrics": _get(
                tripcount_summary,
                "conclusion",
                "tripcount_patch_restores_scoreable_metrics_on_this_sample",
            ),
        },
        "records": records,
        "recommendations": _recommendations(
            resolution_counts=resolution_counts,
            tripcount_summary=tripcount_summary,
        ),
    }


def classify_task(
    *,
    task_id: str,
    manifest_record: dict[str, Any],
    smoke_record: dict[str, Any],
    task_dir: Path,
) -> dict[str, Any]:
    text = _task_source_text(task_dir)
    signals = _signals(text=text, manifest_record=manifest_record)
    resolution_class = _resolution_class(signals)
    source_path = str(manifest_record.get("source_path") or "")
    return {
        "task_id": task_id,
        "source": manifest_record.get("source"),
        "source_path": source_path,
        "top_function": manifest_record.get("top_function"),
        "generated_testbench": manifest_record.get("generated_testbench"),
        "csim_ok": smoke_record.get("csim_ok"),
        "synth_ok": smoke_record.get("synth_ok"),
        "latency_worst": smoke_record.get("latency_worst"),
        "interval_max": smoke_record.get("interval_max"),
        "signals": signals,
        "input_size_related": _input_size_related(signals),
        "resolution_class": resolution_class,
        "submission_guidance": _submission_guidance(resolution_class),
    }


def _signals(*, text: str, manifest_record: dict[str, Any]) -> list[str]:
    signals: list[str] = []
    lowered = text.lower()
    source_path = str(manifest_record.get("source_path") or "").lower()
    if VARIABLE_BOUND_RE.search(text):
        signals.append("variable_size_loop")
    if "hls::stream" in text or "ap_axiu" in text or "axis" in lowered:
        signals.append("stream_or_axis_protocol")
    if "dataflow" in lowered:
        signals.append("dataflow")
    if "m_axi" in text or "maxi" in lowered or "burst" in lowered:
        signals.append("axi_or_burst_memory")
    if "performance" in source_path or "perf" in lowered:
        signals.append("performance_counter_or_benchmark_kernel")
    if (
        "ap_ctrl_none" in text
        or "ap_ctrl_chain" in text
        or "ap_ctrl_hs" in text
    ):
        signals.append("explicit_control_protocol")
    if "loop_tripcount" in lowered:
        signals.append("loop_tripcount_present")
    return sorted(set(signals))


def _resolution_class(signals: list[str]) -> str:
    signal_set = set(signals)
    if "performance_counter_or_benchmark_kernel" in signal_set:
        return "quarantine_low_value_performance_counter_kernel"
    if signal_set & {
        "stream_or_axis_protocol",
        "dataflow",
        "explicit_control_protocol",
    }:
        return "quarantine_protocol_or_dataflow_modeling_required"
    if "variable_size_loop" in signal_set:
        return "bounded_wrapper_small_sample_candidate"
    if "axi_or_burst_memory" in signal_set:
        return "bounded_memory_wrapper_small_sample_candidate"
    return "quarantine_metric_incomplete_unclassified"


def _input_size_related(signals: list[str]) -> bool:
    return bool({"variable_size_loop", "axi_or_burst_memory"} & set(signals))


def _submission_guidance(resolution_class: str) -> str:
    if resolution_class == "bounded_wrapper_small_sample_candidate":
        return (
            "Eligible for a 1-3 task bounded-wrapper experiment; do not expand "
            "without proving top-level latency/II is restored."
        )
    if resolution_class == "bounded_memory_wrapper_small_sample_candidate":
        return (
            "Potential wrapper candidate only if public fixed-size semantics are "
            "obvious; otherwise quarantine."
        )
    if resolution_class == "quarantine_low_value_performance_counter_kernel":
        return (
            "Prefer quarantine or task replacement; wrappering performance "
            "counter kernels is likely to change task intent."
        )
    if resolution_class == "quarantine_protocol_or_dataflow_modeling_required":
        return (
            "Prefer quarantine before submission; protocol/dataflow scoreability "
            "requires a separate modeling decision."
        )
    return "Keep quarantined until a generic scoreability fix is proven."


def _recommendations(
    *,
    resolution_counts: Counter[str],
    tripcount_summary: dict[str, Any] | None,
) -> list[str]:
    recommendations = [
        "Keep metric-incomplete public-HLS tasks explicitly marked in manifest scoreable_gate.",
        "Use runner exclusion/quarantine for formal acceptance unless a generic scoreability fix is proven.",
    ]
    if _get(
        tripcount_summary,
        "conclusion",
        "tripcount_patch_restores_scoreable_metrics_on_this_sample",
    ) is False:
        recommendations.append(
            "Do not expand LOOP_TRIPCOUNT-only patching; the existing 3-task sample did not restore scoreable metrics."
        )
    if resolution_counts.get("bounded_wrapper_small_sample_candidate"):
        recommendations.append(
            "If more work is allowed, try at most 1-3 bounded-wrapper samples from simple variable-size memory kernels."
        )
    if (
        resolution_counts.get("quarantine_low_value_performance_counter_kernel")
        or resolution_counts.get("quarantine_protocol_or_dataflow_modeling_required")
    ):
        recommendations.append(
            "Do not treat performance-counter, stream, or dataflow protocol tasks as generation failures."
        )
    return recommendations


def _task_source_text(task_dir: Path) -> str:
    chunks = []
    for path in sorted(task_dir.iterdir()) if task_dir.is_dir() else []:
        if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _get(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tasks/generated/public_hls_validated_tasks_manifest.json"),
    )
    parser.add_argument(
        "--smoke",
        type=Path,
        default=Path("tasks/generated/public_hls_tasks_smoke.json"),
    )
    parser.add_argument("--task-root", type=Path, default=Path("tasks/generated"))
    parser.add_argument(
        "--tripcount-summary",
        type=Path,
        default=Path(
            "fpt26-agent-v3/scoring/reports/"
            "phase2f_tripcount_patch_sample_summary_20260725.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "fpt26-agent-v3/scoring/reports/"
            "phase2f_public_hls_metric_incomplete_resolution_20260726.json"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit(
        manifest_path=args.manifest,
        smoke_path=args.smoke,
        task_root=args.task_root,
        tripcount_summary_path=args.tripcount_summary,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
