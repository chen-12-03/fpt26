#!/usr/bin/env python3
"""Keep only CSim+Synth-passing public HLS tasks in tasks/generated."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--smoke", type=Path, required=True)
    parser.add_argument("--task-root", type=Path, default=Path("tasks/generated"))
    parser.add_argument(
        "--failed-root",
        type=Path,
        default=Path("/tmp/fpt26_failed_public_hls_tasks"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tasks/generated/public_hls_validated_tasks_manifest.json"),
    )
    parser.add_argument(
        "--allow-missing-score-metrics",
        action="store_true",
        help=(
            "Legacy mode: keep CSim+Synth-passing tasks even when smoke "
            "reports no latency/II. Default keeps only scoreable tasks."
        ),
    )
    args = parser.parse_args()

    candidates = json.loads(args.candidate_manifest.read_text(encoding="utf-8"))
    smoke = json.loads(args.smoke.read_text(encoding="utf-8"))
    records = {str(item["task_id"]): item for item in candidates.get("imported", [])}
    smoke_results = {str(item["task_id"]): item for item in smoke.get("results", [])}
    passed_ids, failed_ids, metric_incomplete_ids = _classify_smoke_results(
        smoke_results,
        allow_missing_score_metrics=args.allow_missing_score_metrics,
    )

    args.failed_root.mkdir(parents=True, exist_ok=True)
    moved = []
    for task_id in sorted(failed_ids):
        source = args.task_root / task_id
        if not source.exists():
            continue
        dest = args.failed_root / task_id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(source), str(dest))
        moved.append({"task_id": task_id, "moved_to": str(dest)})

    by_source: dict[str, int] = {}
    passed = []
    failed = []
    for task_id in sorted(passed_ids):
        record = dict(records.get(task_id) or {"task_id": task_id})
        result = smoke_results.get(task_id) or {}
        record["csim_ok"] = result.get("csim_ok")
        record["synth_ok"] = result.get("synth_ok")
        record["scoreable_synth_ok"] = _scoreable_synth_ok(result)
        record["measurable_latency_ok"] = result.get("measurable_latency_ok")
        record["measurable_ii_ok"] = result.get("measurable_ii_ok")
        record["latency_worst"] = result.get("latency_worst")
        record["interval_max"] = result.get("interval_max")
        record["clock_period_ns"] = result.get("clock_period_ns")
        record["resources"] = result.get("resources")
        passed.append(record)
        source_name = str(record.get("source") or "unknown")
        by_source[source_name] = by_source.get(source_name, 0) + 1
    for task_id in sorted(failed_ids):
        record = dict(records.get(task_id) or {"task_id": task_id})
        record["smoke"] = smoke_results.get(task_id) or {}
        failed.append(record)

    payload = {
        "schema_version": 1,
        "purpose": "public_hls_validated_task_manifest",
        "candidate_count": len(records),
        "validated_count": len(passed),
        "failed_count": len(failed),
        "validated_by_source": dict(sorted(by_source.items())),
        "csim_synth_smoke": {
            "path": str(args.smoke),
            "passed_count": smoke.get("passed_count"),
            "failed_count": smoke.get("failed_count"),
            "total_checked": smoke.get("total_checked"),
        },
        "scoreable_gate": {
            "allow_missing_score_metrics": args.allow_missing_score_metrics,
            "metric_incomplete_count": len(metric_incomplete_ids),
            "metric_incomplete_task_ids": sorted(metric_incomplete_ids),
        },
        "validated": passed,
        "failed_candidates": failed,
        "moved_failed_candidates": moved,
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"validated={len(passed)} failed={len(failed)} "
        f"moved={len(moved)} output={args.output}"
    )
    return 0 if len(passed) >= 100 else 1

def _classify_smoke_results(
    smoke_results: dict[str, dict[str, object]],
    *,
    allow_missing_score_metrics: bool,
) -> tuple[set[str], set[str], set[str]]:
    passed_ids: set[str] = set()
    failed_ids: set[str] = set()
    metric_incomplete_ids: set[str] = set()
    for task_id, result in smoke_results.items():
        base_ok = bool(result.get("csim_ok") and result.get("synth_ok"))
        scoreable = _scoreable_synth_ok(result)
        if base_ok and not scoreable:
            metric_incomplete_ids.add(task_id)
        if base_ok and (allow_missing_score_metrics or scoreable):
            passed_ids.add(task_id)
        else:
            failed_ids.add(task_id)
    return passed_ids, failed_ids, metric_incomplete_ids


def _scoreable_synth_ok(result: dict[str, object]) -> bool:
    if result.get("scoreable_synth_ok") is True:
        return True
    if result.get("synth_ok") is not True:
        return False
    latency_ok = result.get("latency_worst") is not None
    interval_ok = (
        result.get("interval_max") is not None
        if "interval_max" in result
        else True
    )
    return latency_ok and interval_ok


if __name__ == "__main__":
    raise SystemExit(main())
