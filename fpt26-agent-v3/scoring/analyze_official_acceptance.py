"""Audit real official-task acceptance runs through the authoritative scorer.

The command deliberately consumes only fresh run artifacts: ``run_report.json``,
Vitis ``csynth.xml``/``*_cosim.rpt`` reports, and final kernel files.  It rejects
mock/scripted clients, incomplete API usage, failed tool stages, display-score
drift, and attempts to overwrite an existing audit report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

from llm4hls.report import SynthReport, parse_cosim_rpt, parse_csynth_xml
from llm4hls.task import load_task
from scoring import __version__ as scoring_version
from scoring.scoring_v3 import (
    SCHEMA_VERSION,
    W_PERFORMANCE,
    Anchor,
    QoREvidence,
    TaskScoringConfig,
    ValidityGates,
    calculate_qor_components,
    grade,
    grade_standardized_qor,
    hardware_qor,
)


WEIGHTS = (0.50, 0.52, 0.54, 0.55, 0.56, 0.60)
EXPECTED_TASKS = {
    "dotProduct_optimize",
    "projection_bugfix",
    "residual_stream_deadlock",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _workspace_path(container_path: str, workspace_root: Path) -> Path:
    """Map the frozen container's /workspace path onto the host workspace."""
    path = Path(container_path)
    if not path.is_absolute() or path.parts[:2] != ("/", "workspace"):
        raise RuntimeError(f"unexpected container artifact path: {container_path}")
    resolved = workspace_root.joinpath(*path.parts[2:]).resolve()
    root = workspace_root.resolve()
    if not resolved.is_relative_to(root):
        raise RuntimeError(f"artifact escapes workspace: {container_path}")
    if not resolved.exists():
        raise RuntimeError(f"artifact does not exist: {resolved}")
    return resolved


def _stage(report: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [
        stage
        for stage in report["execution_trace"]["grading_results"]
        if stage["stage"] == name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {name} stage")
    stage = matches[0]
    if stage.get("ok") is not True or stage.get("return_code") != 0:
        raise RuntimeError(f"failed {name} stage")
    return stage


def _csynth_path(artifact_dir: Path) -> Path:
    matches = sorted(artifact_dir.glob("synth_proj/*/syn/report/csynth.xml"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one top-level csynth.xml under {artifact_dir}")
    return matches[0]


def _synth_report(
    run_report: dict[str, Any],
    stage_name: str,
    workspace_root: Path,
) -> tuple[Path, SynthReport]:
    stage = _stage(run_report, stage_name)
    artifact_dir = _workspace_path(stage["artifact_dir"], workspace_root)
    path = _csynth_path(artifact_dir)
    return path, parse_csynth_xml(path)


def _latency(report: SynthReport) -> int | None:
    if report.latency_worst is not None:
        return report.latency_worst
    return report.latency_avg


def _anchor(report: SynthReport) -> Anchor:
    return Anchor(
        source="starter",
        valid=True,
        latency=_latency(report),
        ii=report.interval_max,
        clock_ns=report.clock_period_ns,
        resources=dict(report.resources),
        available=dict(report.available),
        hash="fresh_official_starter_csynth",
    )


def _evidence(report: SynthReport, cosim_latency: int | None) -> QoREvidence:
    return QoREvidence(
        candidate_latency=_latency(report),
        candidate_ii=report.interval_max,
        candidate_clock_ns=report.clock_period_ns,
        cosim_latency=cosim_latency,
        candidate_resources=dict(report.resources),
    )


def _score_grid(
    cfg: TaskScoringConfig,
    anchor: Anchor,
    evidence: QoREvidence,
) -> tuple[dict[str, Any], dict[str, float]]:
    components = calculate_qor_components(cfg, anchor, evidence)
    scores = {
        f"{weight:.2f}": 100.0 * hardware_qor(
            components.performance_ratio,
            components.area_ratio,
            performance_weight=weight,
        )
        for weight in WEIGHTS
    }
    return asdict(components), scores


def _assert_display_equal(actual: float, displayed: Any, digits: int) -> None:
    if not math.isclose(round(actual, digits), float(displayed), abs_tol=10 ** (-digits)):
        raise RuntimeError(
            f"authoritative result {actual} disagrees with display value {displayed}"
        )


def _validate_api(report: dict[str, Any]) -> dict[str, Any]:
    llm = report.get("llm") or {}
    usage = llm.get("token_usage") or {}
    if llm.get("client") != "OpenAICompatClient":
        raise RuntimeError("official acceptance did not use the real OpenAI-compatible client")
    if (
        usage.get("complete") is not True
        or usage.get("request_count", 0) <= 0
        or usage.get("request_count") != usage.get("response_count")
        or usage.get("failed_request_count") != 0
        or usage.get("unreported_response_count") != 0
        or usage.get("total_tokens")
        != usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
    ):
        raise RuntimeError("incomplete or failed real API usage")
    return {
        "client": llm["client"],
        "model": llm["model"],
        "temperature": llm["temperature"],
        "max_tokens": llm["max_tokens"],
        "usage": usage,
    }


def _validate_vitis_stages(report: dict[str, Any], requires_cosim: bool) -> dict[str, Any]:
    names = ["hidden_csim", "candidate_synth", "starter_synth", "reference_synth"]
    if requires_cosim:
        names.append("hidden_cosim")
    stages = []
    for name in names:
        stage = _stage(report, name)
        log = stage.get("log", "")
        if stage["kind"] in {"synth", "cosim"} and "vitis-run v2025.2" not in log:
            raise RuntimeError(f"{name} does not contain the expected real Vitis banner")
        stages.append({
            "stage": name,
            "kind": stage["kind"],
            "return_code": stage["return_code"],
            "ok": stage["ok"],
            "elapsed_s": stage["elapsed_s"],
            "brief": stage["brief"],
        })
    return {
        "tool": "vitis-run v2025.2",
        "build": "6295257",
        "stages": stages,
    }


def _cosim_evidence(
    report: dict[str, Any], workspace_root: Path, requires_cosim: bool
) -> tuple[int | None, dict[str, Any] | None]:
    if not requires_cosim:
        return None, None
    stage = _stage(report, "hidden_cosim")
    artifact_dir = _workspace_path(stage["artifact_dir"], workspace_root)
    matches = sorted(artifact_dir.glob("cosim_proj/*/sim/report/*_cosim.rpt"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one cosim report under {artifact_dir}")
    result = parse_cosim_rpt(matches[0])
    if result is None or not result.passed or result.latency_max is None:
        raise RuntimeError("RTL co-simulation did not provide a passing measured latency")
    if result.latency_max != report["scoring"].get("cosim_latency_used"):
        raise RuntimeError("measured cosim latency disagrees with production scorecard")
    return result.latency_max, {
        "path": str(matches[0]),
        "sha256": _sha256(matches[0]),
        "status": result.status,
        "latency_min": result.latency_min,
        "latency_avg": result.latency_avg,
        "latency_max": result.latency_max,
    }


def _dot_candidate_frontier(
    report: dict[str, Any], workspace_root: Path, cfg: TaskScoringConfig
) -> dict[str, Any]:
    points = []
    grading_candidate_path, _ = _synth_report(
        report, "candidate_synth", workspace_root
    )
    grading_candidate_hash = _sha256(grading_candidate_path)
    for event in report["execution_trace"]["transcript"]:
        if event.get("kind") != "synth" or event.get("phase") != "pass":
            continue
        artifact_dir = _workspace_path(event["artifact_dir"], workspace_root)
        path = _csynth_path(artifact_dir)
        parsed = parse_csynth_xml(path)
        evidence = _evidence(parsed, None)
        # The first synth event is the baseline against which later proposals
        # were accepted or rejected by the frozen agent.
        if not points:
            baseline = _anchor(parsed)
        components, scores = _score_grid(cfg, baseline, evidence)
        digest = _sha256(path)
        points.append({
            "tool_call_n": event["n"],
            "artifact_dir": str(artifact_dir),
            "csynth_xml": str(path),
            "csynth_xml_sha256": digest,
            "is_final_accepted_candidate": digest == grading_candidate_hash,
            "report": parsed.to_dict(),
            "qor_components_exact": components,
            "standardized_hardware_score_by_weight": scores,
        })
    if len(points) < 3:
        raise RuntimeError("dotProduct acceptance run lacks baseline and two proposals")
    accepted = [point for point in points if point["is_final_accepted_candidate"]]
    if len(accepted) != 1:
        raise RuntimeError("cannot identify exactly one accepted dotProduct proposal")
    rankings = {
        f"{weight:.2f}": [
            point["tool_call_n"]
            for point in sorted(
                points,
                key=lambda item: item["standardized_hardware_score_by_weight"][f"{weight:.2f}"],
                reverse=True,
            )
        ]
        for weight in WEIGHTS
    }
    return {"points": points, "ranking_tool_call_n_by_weight": rankings}


def analyze(
    run_report_paths: list[Path], task_root: Path, workspace_root: Path
) -> dict[str, Any]:
    if len(run_report_paths) != 3:
        raise RuntimeError("exactly three official run reports are required")
    tasks: dict[str, Any] = {}
    token_totals = {
        "request_count": 0,
        "response_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    for run_report_path in run_report_paths:
        path = run_report_path.resolve()
        report = json.loads(path.read_text())
        task_id = report.get("task_id")
        if task_id in tasks or task_id not in EXPECTED_TASKS:
            raise RuntimeError(f"unexpected or duplicate official task: {task_id}")
        # The frozen runner uses ``status=completed`` as the terminal contract;
        # a normal completion leaves the optional diagnostic stop_reason empty.
        if report.get("status") != "completed" or report.get("stop_reason") not in {"", "completed"}:
            raise RuntimeError(f"official run did not complete: {task_id}")
        task = load_task(task_root / task_id)
        cfg = TaskScoringConfig(
            task_id=task.id,
            task_type=task.type,
            difficulty=task.difficulty,
            requires_cosim=task.requires_cosim,
            budget_limit=task.budget,
            time_limit_s=float(report["scoring"]["time_limit_s"]),
            task_clock_ns=task.clock_ns,
        )
        api = _validate_api(report)
        for field in token_totals:
            token_totals[field] += api["usage"][field]
        vitis = _validate_vitis_stages(report, task.requires_cosim)
        cosim_latency, cosim_report = _cosim_evidence(
            report, workspace_root, task.requires_cosim
        )
        starter_path, starter = _synth_report(report, "starter_synth", workspace_root)
        candidate_path, candidate = _synth_report(report, "candidate_synth", workspace_root)
        reference_path, reference = _synth_report(report, "reference_synth", workspace_root)
        anchor = _anchor(starter)
        evidence = _evidence(candidate, cosim_latency)
        gates = ValidityGates(
            hidden_csim_pass=True,
            hidden_cosim_pass=True if task.requires_cosim else None,
            synth_pass=True,
        )
        production = grade(
            cfg,
            anchor,
            evidence,
            cost_spent=int(report["scoring"]["cost_spent"]),
            wall_time_s=float(report["scoring"]["wall_time_s"]),
            gates=gates,
        )
        standardized = grade_standardized_qor(cfg, anchor, evidence, gates=gates)
        if not production.valid or not standardized.valid:
            raise RuntimeError(f"authoritative rescoring failed validity: {task_id}")
        _assert_display_equal(production.score, report["scoring"]["score"], 2)
        _assert_display_equal(production.q_hw, report["scoring"]["q_hw"], 4)
        if production.schema_version != SCHEMA_VERSION:
            raise RuntimeError("authoritative scoring schema drift")
        components, weight_scores = _score_grid(cfg, anchor, evidence)
        final_artifacts = sorted(path.parent.glob("final_*.cpp"))
        if len(final_artifacts) != 1:
            raise RuntimeError(f"expected one final kernel artifact for {task_id}")
        task_result = {
            "mode": report["mode"],
            "status": report["status"],
            "stop_reason": report["stop_reason"],
            "run_report": str(path),
            "run_report_sha256": _sha256(path),
            "real_llm": api,
            "real_vitis": vitis,
            "tool_call_count": report["tool_call_count"],
            "budget": report["budget"],
            "evaluation": report["evaluation"],
            "fresh_evidence": {
                "starter_csynth_xml": str(starter_path),
                "starter_csynth_xml_sha256": _sha256(starter_path),
                "candidate_csynth_xml": str(candidate_path),
                "candidate_csynth_xml_sha256": _sha256(candidate_path),
                "reference_csynth_xml": str(reference_path),
                "reference_csynth_xml_sha256": _sha256(reference_path),
                "cosim": cosim_report,
                "final_kernel": str(final_artifacts[0]),
                "final_kernel_sha256": _sha256(final_artifacts[0]),
            },
            "qor_components_exact": components,
            "production_scorecard_authoritative": asdict(production),
            "standardized_scorecard_authoritative": asdict(standardized),
            "standardized_hardware_score_by_weight": weight_scores,
        }
        if task_id == "dotProduct_optimize":
            task_result["real_candidate_frontier"] = _dot_candidate_frontier(
                report, workspace_root, cfg
            )
        tasks[task_id] = task_result

    if set(tasks) != EXPECTED_TASKS:
        raise RuntimeError(f"missing official tasks: {sorted(EXPECTED_TASKS - set(tasks))}")
    models = sorted({task["real_llm"]["model"] for task in tasks.values()})
    if len(models) != 1:
        raise RuntimeError("official tasks did not use one consistent model")
    return {
        "report_schema": 1,
        "scoring_version": scoring_version,
        "scoring_schema": SCHEMA_VERSION,
        "production_weights": {
            "performance": W_PERFORMANCE,
            "area": 1.0 - W_PERFORMANCE,
        },
        "evaluated_performance_weights": list(WEIGHTS),
        "real_api_summary": {
            "model": models[0],
            "token_totals": token_totals,
            "secrets_recorded": False,
        },
        "acceptance": {
            "all_three_completed": True,
            "all_authoritative_validity_gates_passed": True,
            "all_real_api_usage_complete": True,
            "all_required_real_vitis_stages_passed": True,
            "all_run_report_scores_reproduced": True,
        },
        "tasks": dict(sorted(tasks.items())),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-report", action="append", required=True, type=Path)
    parser.add_argument("--task-root", required=True, type=Path)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite output: {args.output}")
    result = analyze(
        args.run_report,
        args.task_root.resolve(),
        args.workspace_root.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        f"official acceptance: tasks={len(result['tasks'])} "
        f"requests={result['real_api_summary']['token_totals']['request_count']} "
        f"tokens={result['real_api_summary']['token_totals']['total_tokens']} "
        f"scoring={result['scoring_version']}/schema-{result['scoring_schema']} "
        f"output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
