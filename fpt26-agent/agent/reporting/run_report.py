from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.competition_agent import AgentRunResult


def write_experimental_report(
    result: AgentRunResult,
    *,
    mode: str,
    scoring: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if result.run_directory is None:
        raise ValueError("run_directory is required before writing report")
    run_dir = Path(result.run_directory)
    report_dir = run_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=False)
    report = build_experimental_report(result, mode=mode, scoring=scoring)
    report["paths"] = {
        **report.get("paths", {}),
        "report_dir": str(report_dir),
        "report_json": str(report_dir / "report.json"),
        "report_txt": str(report_dir / "report.txt"),
    }
    (report_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (report_dir / "report.txt").write_text(render_experimental_report(report) + "\n", encoding="utf-8")
    return report


def attach_report_to_manifest(
    result: AgentRunResult,
    report: dict[str, Any],
    *,
    scoring: dict[str, Any] | None = None,
) -> None:
    if result.run_manifest_path is None:
        return
    manifest_path = Path(result.run_manifest_path)
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["reporting"] = {
        "report": _report_manifest_summary(report),
        "scoring": _scoring_manifest_summary(scoring),
    }
    _write_json_atomic(manifest_path, manifest)


def build_experimental_report(
    result: AgentRunResult,
    *,
    mode: str,
    scoring: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = result.task_context
    stage_results = [stage.to_dict() for stage in result.stage_results]
    return {
        "schema_version": "fpt26-agent-experimental-report-v1",
        "task": {
            "task_id": result.task_id,
            "task_type": context.task_type,
            "top_function": context.top_function,
            "target_part": context.target_part,
            "requested_clock_ns": context.requested_clock_ns,
            "requires_cosim": context.requires_cosim,
            "description": context.description,
        },
        "agent": {
            "mode": mode,
            "status": result.status,
            "initial_condition": result.initial_condition.to_dict(),
            "selected_candidate_id": result.selected_candidate_id,
            "final_kernel_sha256": result.final_kernel_sha256,
            "stop_reason": result.stop_reason,
            "repair_status": result.repair_status,
            "optimization_status": result.optimization_status,
            "structural_repair_status": result.structural_repair_status,
        },
        "verification": _verification_summary(stage_results),
        "ppa": _ppa_summary(result, stage_results, scoring),
        "budget": result.budget,
        "llm_usage": result.llm_usage,
        "scoring": scoring,
        "artifacts": _artifact_summary(stage_results),
        "paths": {
            "run_directory": result.run_directory,
            "run_manifest": result.run_manifest_path,
        },
    }


def render_experimental_report(report: dict[str, Any]) -> str:
    task = report["task"]
    agent = report["agent"]
    verification = report["verification"]
    ppa = report["ppa"]
    scoring = report.get("scoring")
    lines = [
        f"=== Experimental Report: {task['task_id']} ===",
        f"  task type              : {task['task_type']}",
        f"  top function           : {task['top_function']}",
        f"  target                 : {task['target_part']} @ {task['requested_clock_ns']} ns",
        f"  mode                   : {agent['mode']}",
        f"  status                 : {agent['status']}",
        f"  selected candidate     : {agent['selected_candidate_id']}",
        f"  initial condition      : {agent['initial_condition']['condition']}",
        "",
        "--- Verification ---",
        f"  csim                   : {verification.get('csim_status')}",
        f"  synth                  : {verification.get('synth_status')}",
        f"  cosim                  : {verification.get('cosim_status')}",
        "",
        "--- PPA ---",
        f"  estimated clock ns     : {ppa.get('estimated_clock_ns')}",
        f"  latency min/max        : {ppa.get('latency_min')} / {ppa.get('latency_max')}",
        f"  II min/max             : {ppa.get('ii_min')} / {ppa.get('ii_max')}",
        f"  resources              : LUT={ppa.get('lut')} FF={ppa.get('ff')} DSP={ppa.get('dsp')} BRAM={ppa.get('bram')} URAM={ppa.get('uram')}",
    ]
    if scoring is not None:
        lines.extend(
            [
                "",
                "--- Official Scorecard ---",
                f"  functional hidden TB   : {_pass_fail(scoring.get('functional_pass'))}",
                f"  synthesizable          : {_pass_fail(scoring.get('synth_pass'))}",
                f"  cosim                  : {_pass_fail(scoring.get('cosim_pass')) if scoring.get('cosim_pass') is not None else 'N/A'}",
                f"  baseline latency       : {scoring.get('baseline_latency')}",
                f"  candidate latency      : {scoring.get('candidate_latency')}",
                f"  acceleration           : {scoring.get('acceleration')}",
                f"  score                  : {scoring.get('score')}",
            ]
        )
    lines.extend(
        [
            "",
            "--- Budget And Tokens ---",
            f"  HLS budget             : {report['budget'].get('spent')}/{report['budget'].get('total')} credits",
            f"  LLM tokens             : {report['llm_usage'].get('total_tokens')}",
            "",
            "--- Paths ---",
            f"  run directory          : {report['paths'].get('run_directory')}",
            f"  run manifest           : {report['paths'].get('run_manifest')}",
            f"  report json            : {report['paths'].get('report_json')}",
        ]
    )
    return "\n".join(lines)


def _verification_summary(stage_results: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for stage in ("csim", "synth", "cosim"):
        matches = [item for item in stage_results if item.get("stage") == stage]
        latest = matches[-1] if matches else None
        summary[f"{stage}_status"] = latest.get("status") if latest else "not_run"
        summary[f"{stage}_summary"] = latest.get("summary") if latest else None
    summary["stage_results"] = stage_results
    return summary


def _ppa_summary(
    result: AgentRunResult,
    stage_results: list[dict[str, Any]],
    scoring: dict[str, Any] | None,
) -> dict[str, Any]:
    metrics = dict(result.final_metrics or result.baseline_metrics or {})
    if not metrics:
        for stage in reversed(stage_results):
            if stage.get("stage") == "synth" and isinstance(stage.get("metrics"), dict):
                metrics = dict(stage["metrics"])
                break
    if scoring and isinstance(scoring.get("candidate_report"), dict):
        report = scoring["candidate_report"]
        resources = report.get("resources") or {}
        metrics = {
            **metrics,
            "estimated_clock_ns": report.get("clock_period_ns"),
            "latency_min": report.get("latency_best"),
            "latency_max": report.get("latency_worst"),
            "ii_min": report.get("interval_min"),
            "ii_max": report.get("interval_max"),
            "lut": resources.get("LUT"),
            "ff": resources.get("FF"),
            "dsp": resources.get("DSP"),
            "bram": resources.get("BRAM_18K"),
            "uram": resources.get("URAM"),
        }
    return {
        key: metrics.get(key)
        for key in (
            "estimated_clock_ns",
            "latency_min",
            "latency_max",
            "ii_min",
            "ii_max",
            "lut",
            "ff",
            "dsp",
            "bram",
            "uram",
        )
    }


def _artifact_summary(stage_results: list[dict[str, Any]]) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    for index, stage in enumerate(stage_results, start=1):
        key = f"{stage.get('stage', 'unknown')}_{index}"
        artifacts[key] = stage.get("artifacts", {})
    return artifacts


def _pass_fail(value: Any) -> str:
    if value is True:
        return "PASS"
    if value is False:
        return "FAIL"
    return "N/A"


def _report_manifest_summary(report: dict[str, Any]) -> dict[str, Any]:
    paths = report.get("paths") if isinstance(report.get("paths"), dict) else {}
    return {
        "schema_version": report.get("schema_version"),
        "report_json": paths.get("report_json"),
        "report_txt": paths.get("report_txt"),
        "verification": report.get("verification"),
        "ppa": report.get("ppa"),
    }


def _scoring_manifest_summary(scoring: dict[str, Any] | None) -> dict[str, Any] | None:
    if scoring is None:
        return None
    paths = scoring.get("paths") if isinstance(scoring.get("paths"), dict) else {}
    return {
        "task_id": scoring.get("task_id"),
        "difficulty": scoring.get("difficulty"),
        "functional_pass": scoring.get("functional_pass"),
        "synth_pass": scoring.get("synth_pass"),
        "cosim_pass": scoring.get("cosim_pass"),
        "baseline_latency": scoring.get("baseline_latency"),
        "candidate_latency": scoring.get("candidate_latency"),
        "acceleration": scoring.get("acceleration"),
        "is_opt": scoring.get("is_opt"),
        "score": scoring.get("score"),
        "scorecard_json": paths.get("scorecard_json"),
        "scorecard_txt": paths.get("scorecard_txt"),
        "official_grade_root": paths.get("official_grade_root"),
    }


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)
