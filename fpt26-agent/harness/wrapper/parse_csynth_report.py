#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def _to_int(value: str) -> int | None:
    value = value.strip().replace("~", "")
    if value in {"", "-", "N/A"}:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _to_float_ns(value: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*ns", value)
    if not match:
        return None
    return float(match.group(1))


def _split_table_row(line: str) -> list[str]:
    return [part.strip() for part in line.strip().strip("|").split("|")]


def discover_csynth_report(run_dir: Path) -> Path:
    candidates = sorted(run_dir.rglob("*_csynth.rpt"))
    if not candidates:
        raise FileNotFoundError(f"no *_csynth.rpt found under run directory: {run_dir}")
    preferred = [path for path in candidates if "/reports/" in path.as_posix()]
    return preferred[0] if preferred else candidates[0]


def infer_run_dir(report_path: Path) -> Path | None:
    parts = report_path.parts
    if "reports" in parts:
        reports_index = parts.index("reports")
        if reports_index > 0:
            return Path(*parts[:reports_index])
    if "syn" in parts:
        syn_index = parts.index("syn")
        if syn_index >= 3:
            return Path(*parts[: syn_index - 2])
    return None


def parse_csynth_text(text: str, report_path: Path) -> tuple[dict[str, Any], list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []

    if "Vitis HLS Report" not in text:
        errors.append("input does not look like a Vitis HLS csynth report")

    metrics: dict[str, Any] = {
        "target_clock_ns": None,
        "estimated_clock_ns": None,
        "latency_cycles": {"min": None, "max": None},
        "ii": None,
        "resources": {"lut": None, "ff": None, "bram": None, "dsp": None},
    }

    clock_match = re.search(
        r"\|\s*ap_clk\s*\|\s*([^|]+)\|\s*([^|]+)\|",
        text,
    )
    if clock_match:
        metrics["target_clock_ns"] = _to_float_ns(clock_match.group(1))
        metrics["estimated_clock_ns"] = _to_float_ns(clock_match.group(2))
    else:
        warnings.append("clock summary row was not found")

    latency_match = re.search(
        r"\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*[^|]+\|\s*[^|]+\|\s*(\d+|-)\s*\|\s*(\d+|-)\s*\|",
        text,
    )
    if latency_match:
        metrics["latency_cycles"]["min"] = _to_int(latency_match.group(1))
        metrics["latency_cycles"]["max"] = _to_int(latency_match.group(2))
        ii_min = _to_int(latency_match.group(3))
        ii_max = _to_int(latency_match.group(4))
        metrics["ii"] = ii_max if ii_min == ii_max else ii_max
    else:
        warnings.append("latency summary row was not found")

    total_row = None
    for line in text.splitlines():
        if re.match(r"\|\s*Total\s*\|", line):
            total_row = _split_table_row(line)
            if len(total_row) >= 6:
                break
    if total_row and len(total_row) >= 6:
        metrics["resources"]["bram"] = _to_int(total_row[1])
        metrics["resources"]["dsp"] = _to_int(total_row[2])
        metrics["resources"]["ff"] = _to_int(total_row[3])
        metrics["resources"]["lut"] = _to_int(total_row[4])
    else:
        warnings.append("resource total row was not found")

    for key, value in {
        "target_clock_ns": metrics["target_clock_ns"],
        "estimated_clock_ns": metrics["estimated_clock_ns"],
        "latency_cycles.min": metrics["latency_cycles"]["min"],
        "latency_cycles.max": metrics["latency_cycles"]["max"],
        "ii": metrics["ii"],
        "resources.lut": metrics["resources"]["lut"],
        "resources.ff": metrics["resources"]["ff"],
        "resources.bram": metrics["resources"]["bram"],
        "resources.dsp": metrics["resources"]["dsp"],
    }.items():
        if value is None:
            warnings.append(f"missing metric: {key}")

    return metrics, warnings, errors


def stage_status(run_dir: Path | None, stage: str) -> str | None:
    if run_dir is None:
        return None
    logs_dir = run_dir / "logs"
    if stage == "csim":
        for path in [logs_dir / "csim.stdout.log", logs_dir / "hls_run_tcl.log"]:
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
                if "CSim done with 0 errors" in text:
                    return "pass"
                if "CSIM Failed" in text or "csim_design' failed" in text:
                    return "fail"
        return None
    if stage == "synth":
        for path in [logs_dir / "synth.stdout.log", logs_dir / "hls_run_tcl.log"]:
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
                if "Finished Command csynth_design" in text:
                    return "pass"
                if "csynth_design" in text and ("ERROR:" in text or "failed" in text.lower()):
                    return "fail"
        return None
    return None


def build_report(report_path: Path, run_dir: Path | None) -> dict[str, Any]:
    text = report_path.read_text(encoding="utf-8", errors="replace")
    metrics, warnings, errors = parse_csynth_text(text, report_path)

    task_id = run_dir.parent.name if run_dir else None
    candidate_id = run_dir.name if run_dir else None
    csim_status = stage_status(run_dir, "csim")
    synth_status = stage_status(run_dir, "synth") or ("pass" if not errors else "fail")

    if csim_status is None:
        warnings.append("csim status log was not found")
    if synth_status is None:
        warnings.append("synth status log was not found")

    status = "pass" if not errors and synth_status == "pass" and csim_status in {"pass", None} else "fail"

    return {
        "status": status,
        "task_id": task_id,
        "candidate_id": candidate_id,
        "stages": {
            "csim": csim_status,
            "synth": synth_status,
            "cosim": "not_run",
        },
        "metrics": metrics,
        "artifacts": {
            "csynth_report": str(report_path),
        },
        "warnings": warnings,
        "errors": errors,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse a Vitis HLS csynth.rpt into report.json.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run-dir", type=Path, help="Run directory containing a csynth report.")
    source.add_argument("--report", type=Path, help="Path to a specific *_csynth.rpt file.")
    parser.add_argument("--output", type=Path, help="Output JSON path. Defaults to <run-dir>/report.json.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.run_dir:
            run_dir = args.run_dir.resolve()
            if not run_dir.is_dir():
                raise NotADirectoryError(f"run directory does not exist: {run_dir}")
            report_path = discover_csynth_report(run_dir).resolve()
        else:
            report_path = args.report.resolve()
            if not report_path.is_file():
                raise FileNotFoundError(f"report file does not exist: {report_path}")
            run_dir = infer_run_dir(report_path)

        result = build_report(report_path, run_dir)
        output_path = args.output.resolve() if args.output else ((run_dir / "report.json") if run_dir else report_path.with_name("report.json"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

        if result["errors"]:
            for error in result["errors"]:
                print(f"error: {error}", file=sys.stderr)
            return 1
        print(str(output_path))
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
