#!/usr/bin/env python3
"""Run CSim + Synth smoke gates for imported public HLS tasks."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from agent.testbench import normalize_task_testbench_data
from llm4hls.task import load_task
from llm4hls.tools import CSimTool, SynthTool


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--task-root", type=Path, default=Path("tasks/generated"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only-unvalidated", action="store_true")
    parser.add_argument(
        "--allow-missing-score-metrics",
        action="store_true",
        help=(
            "Legacy mode: count CSim+Synth tasks as passed even when Vitis "
            "does not report latency/II. Default requires scoreable metrics."
        ),
    )
    parser.add_argument("--min-passed", type=int, default=70)
    args = parser.parse_args()

    raw = json.loads(args.manifest.read_text(encoding="utf-8"))
    records = list(raw.get("imported") or [])
    if args.limit:
        records = records[: args.limit]

    previous: dict[str, dict[str, object]] = {}
    if args.output.is_file():
        old = json.loads(args.output.read_text(encoding="utf-8"))
        previous = {
            str(item["task_id"]): item for item in old.get("results", [])
        }

    results: list[dict[str, object]] = []
    started = time.monotonic()
    for index, record in enumerate(records, start=1):
        task_id = str(record["task_id"])
        if args.only_unvalidated and task_id in previous:
            results.append(previous[task_id])
            continue
        task_dir = args.task_root / task_id
        task = load_task(task_dir)
        normalize_task_testbench_data(task)
        files = task.assemble(
            task.kernel_code,
            task.public_tb_code,
            task.public_tb_name,
        )
        task_work = args.work_root / task_id
        csim = CSimTool().run(
            task_work / "csim",
            files,
            task.top,
            task.part,
            task.clock_ns,
            data_files=getattr(task, "data_files", None),
        )
        synth = None
        if csim.ok:
            synth = SynthTool().run(
                task_work / "synth",
                files,
                [task.kernel_name],
                task.top,
                task.part,
                task.clock_ns,
            )
        measurable_latency_ok = bool(
            synth and synth.report and synth.report.latency_worst is not None
        )
        measurable_ii_ok = bool(
            synth and synth.report and synth.report.interval_max is not None
        )
        scoreable_synth_ok = bool(
            synth and synth.ok and measurable_latency_ok and measurable_ii_ok
        )
        passed = bool(
            csim.ok
            and synth
            and synth.ok
            and (
                args.allow_missing_score_metrics
                or scoreable_synth_ok
            )
        )
        result = {
            "task_id": task_id,
            "source": record.get("source"),
            "source_path": record.get("source_path"),
            "top_function": task.top,
            "csim_ok": csim.ok,
            "csim_phase": csim.phase,
            "csim_elapsed_s": round(csim.elapsed_s, 3),
            "synth_ok": bool(synth and synth.ok),
            "synth_phase": synth.phase if synth else "not_run",
            "synth_elapsed_s": round(synth.elapsed_s, 3) if synth else 0.0,
            "measurable_latency_ok": measurable_latency_ok,
            "measurable_ii_ok": measurable_ii_ok,
            "scoreable_synth_ok": scoreable_synth_ok,
            "passed": passed,
            "work_dir": str(task_work),
        }
        if synth and synth.report:
            result["latency_worst"] = synth.report.latency_worst
            result["interval_max"] = synth.report.interval_max
            result["clock_period_ns"] = synth.report.clock_period_ns
            result["resources"] = synth.report.resources
        results.append(result)
        _write(args.output, raw, results, started)
        print(
            f"{index}/{len(records)} {task_id} "
            f"csim={result['csim_phase']} synth={result['synth_phase']} "
            f"passed={result['passed']}",
            flush=True,
        )

    _write(args.output, raw, results, started)
    passed = sum(1 for item in results if item.get("passed") is True)
    print(f"passed={passed} total={len(results)} output={args.output}")
    return 0 if passed >= args.min_passed else 1


def _write(
    output: Path,
    manifest: dict[str, object],
    results: list[dict[str, object]],
    started: float,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    passed = [item for item in results if item.get("passed") is True]
    failed = [item for item in results if item.get("passed") is not True]
    by_source: dict[str, int] = {}
    for item in passed:
        source = str(item.get("source") or "unknown")
        by_source[source] = by_source.get(source, 0) + 1
    payload = {
        "schema_version": 1,
        "purpose": "public_hls_task_csim_synth_smoke",
        "source_manifest": str(manifest.get("purpose", "public_hls_task_import")),
        "total_checked": len(results),
        "passed_count": len(passed),
        "failed_count": len(failed),
        "passed_by_source": dict(sorted(by_source.items())),
        "scoreable_count": sum(
            1 for item in results if item.get("scoreable_synth_ok") is True
        ),
        "metric_incomplete_task_ids": [
            str(item["task_id"])
            for item in results
            if item.get("synth_ok") is True
            and item.get("scoreable_synth_ok") is not True
        ],
        "elapsed_s": round(time.monotonic() - started, 3),
        "results": results,
        "passed_task_ids": [str(item["task_id"]) for item in passed],
        "failed_task_ids": [str(item["task_id"]) for item in failed],
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
