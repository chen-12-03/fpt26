"""Audit the fresh 97-task real-API/Vitis corpus and publish PPA evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent.runner import _prepare_cpp17_sources
from llm4hls.report import SynthReport, parse_csynth_xml
from llm4hls.task import load_task
from scoring import __version__ as scoring_version
from scoring.scoring_v3 import (
    SCHEMA_VERSION,
    Anchor,
    QoREvidence,
    TaskScoringConfig,
    calculate_qor_components,
    hardware_qor,
)


REPRESENTATIVES = {
    "dotProduct_optimize": "only observed slower-but-smaller point; official reference trade-off",
    "c2hlsc__add_round_key": "neutral final/reference identity control",
    "gnnbuilder__gather_node_neighbors": "lowest-composite faster-but-larger point near neutral",
    "rosetta__optical_flow__outer_product": "approximately 2x speed for 2x DSP trade-off",
    "c2hlsc__cusums": "moderate faster-but-larger trade-off",
    "machsuite__gemm_blocked": "extreme speedup with extreme FF growth",
    "c2hlsc__block": "large clock-aware speedup with moderate LUT growth",
    "polybench__trmm": "small performance gain with no worst-resource growth",
    "polybench__cholesky": "balanced faster-and-smaller Pareto improvement",
    "machsuite__aes_aes": "strongest observed faster-and-smaller Pareto improvement",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _workspace_path(value: str, workspace_root: Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.parts[:2] != ("/", "workspace"):
        raise RuntimeError(f"unexpected container path: {value}")
    result = workspace_root.joinpath(*path.parts[2:]).resolve()
    if not result.is_relative_to(workspace_root.resolve()) or not result.exists():
        raise RuntimeError(f"invalid or missing artifact path: {value}")
    return result


def _latency(report: SynthReport) -> int | None:
    if report.latency_worst is not None:
        return report.latency_worst
    return report.latency_avg


def _stage(report: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [
        stage for stage in report["execution_trace"]["grading_results"]
        if stage["stage"] == name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {name} stage for {report['task_id']}")
    stage = matches[0]
    if stage.get("ok") is not True or stage.get("return_code") != 0:
        raise RuntimeError(f"failed {name} stage for {report['task_id']}")
    if stage["kind"] in {"synth", "cosim"} and "vitis-run v2025.2" not in stage.get("log", ""):
        raise RuntimeError(f"missing Vitis banner in {name} for {report['task_id']}")
    return stage


def _synth(
    report: dict[str, Any],
    stage_name: str,
    workspace_root: Path,
) -> tuple[Path, Path, SynthReport]:
    stage = _stage(report, stage_name)
    artifact_dir = _workspace_path(stage["artifact_dir"], workspace_root)
    matches = sorted(artifact_dir.glob("synth_proj/*/syn/report/csynth.xml"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one csynth.xml under {artifact_dir}")
    return artifact_dir, matches[0], parse_csynth_xml(matches[0])


def _task_dir(task_root: Path, task_id: str) -> Path:
    candidates = [task_root / "generated" / task_id, task_root / "official" / task_id]
    matches = [path for path in candidates if path.is_dir()]
    if len(matches) != 1:
        raise RuntimeError(f"cannot resolve task directory: {task_id}")
    return matches[0]


def _launcher_records(run_roots: list[Path]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for root in run_roots:
        summary = json.loads((root / "shard_summary.json").read_text())
        for record in summary["records"]:
            task_id = record["task_id"]
            if task_id in records:
                raise RuntimeError(f"duplicate launcher record: {task_id}")
            records[task_id] = record
    return records


def _api(report: dict[str, Any]) -> dict[str, Any]:
    llm = report.get("llm") or {}
    usage = llm.get("token_usage") or {}
    if llm.get("client") != "OpenAICompatClient":
        raise RuntimeError(f"non-real client for {report['task_id']}")
    if (
        usage.get("complete") is not True
        or usage.get("request_count", 0) < 1
        or usage.get("request_count") != usage.get("response_count")
        or usage.get("failed_request_count") != 0
        or usage.get("unreported_response_count") != 0
        or usage.get("total_tokens")
        != usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
    ):
        raise RuntimeError(f"invalid API usage for {report['task_id']}: {usage}")
    return {
        "client": llm["client"],
        "model": llm["model"],
        "temperature": llm["temperature"],
        "max_tokens": llm["max_tokens"],
        "token_usage": usage,
    }


def _brief_synth(report: SynthReport, xml_path: Path) -> dict[str, Any]:
    return {
        "clock_period_ns": report.clock_period_ns,
        "latency_best": report.latency_best,
        "latency_avg": report.latency_avg,
        "latency_worst": report.latency_worst,
        "interval_min": report.interval_min,
        "interval_max": report.interval_max,
        "resources": dict(report.resources),
        "available": dict(report.available),
        "pipeline_type": report.pipeline_type,
        "loop_metrics": [dict(loop) for loop in report.loop_metrics],
        "csynth_xml": str(xml_path),
        "csynth_xml_sha256": _sha256(xml_path),
    }


def analyze(
    workspace_root: Path,
    task_root: Path,
    run_roots: list[Path],
    reference_calibration_report: Path,
) -> dict[str, Any]:
    launcher = _launcher_records(run_roots)
    expected_tasks = {
        path.parent.name
        for family in ("generated", "official")
        for path in (task_root / family).glob("*/task.toml")
    }
    if len(expected_tasks) != 97 or set(launcher) != expected_tasks:
        raise RuntimeError("launcher coverage is not exactly the 97-task corpus")

    calibration = json.loads(reference_calibration_report.read_text())
    expected_unscorable = set(calibration["ppa"]["unscorable_task_ids"])
    task_results: dict[str, Any] = {}
    token_totals = {
        "request_count": 0,
        "response_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "failed_request_count": 0,
        "unreported_response_count": 0,
    }
    outcome_counts: dict[str, int] = {}
    quadrant_counts: dict[str, int] = {}

    for task_id in sorted(expected_tasks):
        record = launcher[task_id]
        report_path = _workspace_path(record["run_report"], workspace_root)
        report = json.loads(report_path.read_text())
        if report.get("task_id") != task_id:
            raise RuntimeError(f"task/report mismatch: {task_id}")
        api = _api(report)
        for key in token_totals:
            token_totals[key] += api["token_usage"][key]

        if task_id in expected_unscorable:
            if (
                record.get("return_code") != 4
                or report.get("status") != "failed"
                or report.get("stop_reason") != "no_valid_anchor"
            ):
                raise RuntimeError(f"unexpected unscorable outcome: {task_id}")
            outcome = "expected_no_valid_anchor"
        else:
            if record.get("return_code") != 0 or report.get("status") != "completed":
                raise RuntimeError(f"unexpected finite-task outcome: {task_id}")
            outcome = "completed"
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1

        _stage(report, "hidden_csim")
        _stage(report, "starter_synth")
        if task_id == "residual_stream_deadlock":
            _stage(report, "hidden_cosim")
        candidate_dir, candidate_xml, candidate = _synth(
            report, "candidate_synth", workspace_root
        )
        _, reference_xml, reference = _synth(
            report, "reference_synth", workspace_root
        )

        task = load_task(_task_dir(task_root, task_id))
        final_artifacts = sorted(report_path.parent.glob("final_*.cpp"))
        if len(final_artifacts) != 1:
            raise RuntimeError(f"expected one final artifact: {task_id}")
        candidate_source = candidate_dir / task.kernel_name
        prepared_final = _prepare_cpp17_sources({
            task.kernel_name: final_artifacts[0].read_text()
        })[task.kernel_name]
        if not candidate_source.is_file() or candidate_source.read_text() != prepared_final:
            raise RuntimeError(f"final artifact does not match candidate synth source: {task_id}")

        candidate_latency = _latency(candidate)
        reference_latency = _latency(reference)
        ppa: dict[str, Any] | None = None
        if candidate_latency is not None and reference_latency is not None:
            anchor = Anchor(
                source="reference",
                valid=True,
                latency=reference_latency,
                ii=reference.interval_max,
                clock_ns=reference.clock_period_ns,
                resources=dict(reference.resources),
                available=dict(reference.available),
                hash=_sha256(reference_xml),
            )
            evidence = QoREvidence(
                candidate_latency=candidate_latency,
                candidate_ii=candidate.interval_max,
                candidate_clock_ns=candidate.clock_period_ns,
                candidate_resources=dict(candidate.resources),
            )
            # This report compares C-synthesis PPA only; required RTL co-sim is
            # separately enforced above for the structural official task.
            cfg = TaskScoringConfig(
                task_id=task_id,
                task_type=task.type,
                task_clock_ns=task.clock_ns,
            )
            components = calculate_qor_components(cfg, anchor, evidence)
            performance = components.performance_ratio
            area = components.area_ratio
            tolerance = 1e-12
            perf_class = (
                "faster" if performance > 1 + tolerance
                else "slower" if performance < 1 - tolerance
                else "same"
            )
            area_class = (
                "smaller" if area > 1 + tolerance
                else "larger" if area < 1 - tolerance
                else "same"
            )
            quadrant = f"{perf_class}_{area_class}"
            quadrant_counts[quadrant] = quadrant_counts.get(quadrant, 0) + 1
            ppa = {
                "comparison": "final_best_vs_reference",
                "qor_components_exact": asdict(components),
                "quadrant": quadrant,
                "standardized_hardware_score": {
                    "0.55": 100.0 * hardware_qor(performance, area, performance_weight=0.55),
                    "0.60": 100.0 * hardware_qor(performance, area, performance_weight=0.60),
                },
            }
        elif task_id not in expected_unscorable:
            raise RuntimeError(f"unexpected missing finite PPA metrics: {task_id}")
        elif candidate_latency is not None or reference_latency is not None:
            raise RuntimeError(f"asymmetric undef latency: {task_id}")

        task_results[task_id] = {
            "outcome": outcome,
            "mode": report["mode"],
            "run_report": str(report_path),
            "run_report_sha256": _sha256(report_path),
            "launcher_return_code": record["return_code"],
            "launcher_elapsed_s": record["elapsed_s"],
            "real_api": api,
            "final_artifact": str(final_artifacts[0]),
            "final_artifact_sha256": _sha256(final_artifacts[0]),
            "final_best_synth": _brief_synth(candidate, candidate_xml),
            "reference_synth": _brief_synth(reference, reference_xml),
            "ppa": ppa,
        }

    if set(REPRESENTATIVES) - set(task_results):
        raise RuntimeError("representative task is absent")
    representatives = []
    for task_id, reason in REPRESENTATIVES.items():
        result = task_results[task_id]
        if result["ppa"] is None:
            raise RuntimeError(f"representative is not PPA-scorable: {task_id}")
        representatives.append({
            "task_id": task_id,
            "selection_reason": reason,
            "outcome": result["outcome"],
            "final_best_synth": result["final_best_synth"],
            "reference_synth": result["reference_synth"],
            "ppa": result["ppa"],
            "run_report": result["run_report"],
            "final_artifact": result["final_artifact"],
        })

    return {
        "report_schema": 1,
        "purpose": "fresh_all_task_real_api_vitis_and_typical_ppa",
        "scoring_version": scoring_version,
        "scoring_schema": SCHEMA_VERSION,
        "run_roots": [str(path.resolve()) for path in run_roots],
        "coverage": {
            "expected_task_count": 97,
            "run_report_count": len(task_results),
            "unique_task_count": len(task_results),
            "outcome_counts": dict(sorted(outcome_counts.items())),
            "required_grading_stages_all_passed": True,
            "final_artifacts_all_match_candidate_synth_sources": True,
        },
        "real_api_summary": {
            "client": "OpenAICompatClient",
            "models": sorted({result["real_api"]["model"] for result in task_results.values()}),
            "token_totals": token_totals,
            "secrets_recorded": False,
        },
        "vitis_summary": {
            "tool": "vitis-run v2025.2",
            "build": "6295257",
            "paired_final_reference_synth_task_count": 97,
            "finite_ppa_task_count": sum(result["ppa"] is not None for result in task_results.values()),
            "undef_ppa_task_count": sum(result["ppa"] is None for result in task_results.values()),
            "ppa_quadrant_counts": dict(sorted(quadrant_counts.items())),
        },
        "reference_calibration_report": {
            "path": str(reference_calibration_report.resolve()),
            "sha256": _sha256(reference_calibration_report),
            "expected_unscorable_task_ids": sorted(expected_unscorable),
        },
        "representative_selection": {
            "count": len(representatives),
            "method": "cover every observed PPA quadrant plus neutral, boundary, moderate, and extreme trade-offs",
            "tasks": representatives,
        },
        "tasks": task_results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--task-root", required=True, type=Path)
    parser.add_argument("--run-root", action="append", required=True, type=Path)
    parser.add_argument("--reference-calibration-report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite output: {args.output}")
    result = analyze(
        args.workspace_root.resolve(),
        args.task_root.resolve(),
        [path.resolve() for path in args.run_root],
        args.reference_calibration_report.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        f"all-real audit: tasks={result['coverage']['run_report_count']} "
        f"requests={result['real_api_summary']['token_totals']['request_count']} "
        f"tokens={result['real_api_summary']['token_totals']['total_tokens']} "
        f"finite_ppa={result['vitis_summary']['finite_ppa_task_count']} "
        f"representatives={result['representative_selection']['count']} "
        f"output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
