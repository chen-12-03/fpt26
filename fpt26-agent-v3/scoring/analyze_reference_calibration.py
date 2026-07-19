"""Analyze frozen reference calibration evidence through the authoritative scorer."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scoring import __version__ as scoring_version
from scoring.scoring_v3 import (
    RESOURCES,
    SCHEMA_VERSION,
    W_PERFORMANCE,
    Anchor,
    QoREvidence,
    TaskScoringConfig,
    ValidityGates,
    calculate_qor_components,
    grade_standardized_qor,
    hardware_qor,
)


REQUIRED_WEIGHTS = (0.50, 0.52, 0.55, 0.60)


def _latency(report: dict[str, Any]) -> int | None:
    return report.get("latency_worst") or report.get("latency_avg")


def _anchor(report: dict[str, Any]) -> Anchor:
    return Anchor(
        source="starter",
        valid=True,
        latency=_latency(report),
        ii=report.get("interval_max"),
        clock_ns=report.get("clock_period_ns"),
        resources=dict(report["resources"]),
        available=dict(report["available"]),
        hash="fresh_starter_csynth",
    )


def _candidate(report: dict[str, Any]) -> QoREvidence:
    return QoREvidence(
        candidate_latency=_latency(report),
        candidate_ii=report.get("interval_max"),
        candidate_clock_ns=report.get("clock_period_ns"),
        candidate_resources=dict(report["resources"]),
    )


def _config(record: dict[str, Any]) -> TaskScoringConfig:
    target = record["target"]
    return TaskScoringConfig(
        task_id=record["task_id"],
        requires_cosim=bool(target["requires_cosim"]),
        task_clock_ns=float(target["clock_ns"]),
    )


def _gates(record: dict[str, Any]) -> ValidityGates:
    return ValidityGates(
        hidden_csim_pass=bool(record["reference_hidden_csim"]["ok"]),
        synth_pass=bool(record["reference_synth"]["ok"]),
    )


def _pareto_audit(record: dict[str, Any]) -> dict[str, Any]:
    starter = record["starter_synth"]["report"]
    reference = record["reference_synth"]["report"]
    target_clock = float(record["target"]["clock_ns"])
    starter_latency = _latency(starter)
    reference_latency = _latency(reference)

    dimensions: dict[str, dict[str, Any]] = {}
    if starter_latency is not None and reference_latency is not None:
        starter_time = max(
            target_clock,
            starter.get("clock_period_ns") or target_clock,
        ) * starter_latency
        reference_time = max(
            target_clock,
            reference.get("clock_period_ns") or target_clock,
        ) * reference_latency
        dimensions["performance_time_ns"] = {
            "starter": starter_time,
            "reference": reference_time,
            "reference_no_better": reference_time >= starter_time,
            "reference_strictly_worse": reference_time > starter_time,
        }

    starter_ii = starter.get("interval_max")
    reference_ii = reference.get("interval_max")
    if starter_ii is not None and reference_ii is not None:
        dimensions["ii"] = {
            "starter": starter_ii,
            "reference": reference_ii,
            "reference_no_better": reference_ii >= starter_ii,
            "reference_strictly_worse": reference_ii > starter_ii,
        }

    for resource in RESOURCES:
        starter_value = starter["resources"].get(resource)
        reference_value = reference["resources"].get(resource)
        if isinstance(starter_value, int) and isinstance(reference_value, int):
            dimensions[f"resource_{resource}"] = {
                "starter": starter_value,
                "reference": reference_value,
                "reference_no_better": reference_value >= starter_value,
                "reference_strictly_worse": reference_value > starter_value,
            }

    all_no_better = bool(dimensions) and all(
        dimension["reference_no_better"] for dimension in dimensions.values()
    )
    any_strictly_worse = any(
        dimension["reference_strictly_worse"] for dimension in dimensions.values()
    )
    any_better = any(
        not dimension["reference_no_better"] for dimension in dimensions.values()
    )
    return {
        "definition": (
            "reference is dominated only when every valid performance, II, "
            "and resource dimension is no better and at least one is worse"
        ),
        "dimensions": dimensions,
        "reference_pareto_dominated": all_no_better and any_strictly_worse,
        "tradeoff": any_better and any_strictly_worse,
    }


def _weight_boundary(performance_ratio: float, area_ratio: float) -> dict[str, Any]:
    log_performance = math.log(performance_ratio)
    log_area = math.log(area_ratio)
    slope = log_performance - log_area
    if math.isclose(slope, 0.0, abs_tol=1e-15):
        return {
            "kind": "all" if log_area >= 0 else "none",
            "boundary": None,
        }
    boundary = -log_area / slope
    return {
        "kind": "lower" if slope > 0 else "upper",
        "boundary": boundary,
    }


def analyze(evidence_roots: list[Path]) -> dict[str, Any]:
    evidence_paths = sorted(
        path
        for root in evidence_roots
        for path in root.glob("*/repeat_*/evidence.json")
    )
    if not evidence_paths:
        raise RuntimeError("no evidence.json files found")

    grouped: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
    for path in evidence_paths:
        record = json.loads(path.read_text())
        stages = (
            record["reference_hidden_csim"],
            record["starter_synth"],
            record["reference_synth"],
        )
        if not all(stage["ok"] and stage["return_code"] == 0 for stage in stages):
            raise RuntimeError(f"failed tool stage in {path}")
        grouped[record["task_id"]].append((path, record))

    task_results: dict[str, Any] = {}
    conservative_constraints: list[dict[str, Any]] = []
    score_distributions: dict[str, list[float]] = defaultdict(list)
    unscorable_ppa: list[str] = []
    pareto_dominated_ppa: list[str] = []
    class_counts: dict[str, int] = defaultdict(int)
    source_identity_record_count = 0
    source_identity_xml_match_count = 0

    weights = sorted(set(
        REQUIRED_WEIGHTS
        + (
            round(W_PERFORMANCE - 0.05, 2),
            round(W_PERFORMANCE - 0.01, 2),
            W_PERFORMANCE,
            round(W_PERFORMANCE + 0.01, 2),
            round(W_PERFORMANCE + 0.05, 2),
        )
    ))

    for task_id, entries in sorted(grouped.items()):
        first_record = entries[0][1]
        class_name = first_record["classification"]["class"]
        if any(
            record["classification"] != first_record["classification"]
            for _, record in entries
        ):
            raise RuntimeError(f"classification changed across repeats: {task_id}")
        if any(
            record["sources"]["starter_sha256"]
            != first_record["sources"]["starter_sha256"]
            or record["sources"]["reference_sha256"]
            != first_record["sources"]["reference_sha256"]
            for _, record in entries
        ):
            raise RuntimeError(f"source changed across repeats: {task_id}")
        class_counts[class_name] += 1
        repeats: list[dict[str, Any]] = []
        for path, record in entries:
            starter_report = record["starter_synth"]["report"]
            reference_report = record["reference_synth"]["report"]
            repeat: dict[str, Any] = {
                "evidence": str(path),
                "repeat_index": record["repeat_index"],
                "starter_csynth_xml_sha256": record["starter_synth"]["csynth_xml_sha256"],
                "reference_csynth_xml_sha256": record["reference_synth"]["csynth_xml_sha256"],
                "pareto": _pareto_audit(record),
            }
            if record["sources"]["starter_reference_identical"]:
                source_identity_record_count += 1
                if (
                    repeat["starter_csynth_xml_sha256"]
                    != repeat["reference_csynth_xml_sha256"]
                ):
                    raise RuntimeError(
                        f"source-identical starter/reference XML differs: {path}"
                    )
                source_identity_xml_match_count += 1
            if (
                _latency(starter_report) is not None
                and _latency(reference_report) is not None
                and not record["target"]["requires_cosim"]
            ):
                cfg = _config(record)
                anchor = _anchor(starter_report)
                candidate = _candidate(reference_report)
                components = calculate_qor_components(cfg, anchor, candidate)
                repeat["qor_components_exact"] = asdict(components)
                if class_name == "ppa_reference":
                    standardized = grade_standardized_qor(
                        cfg,
                        anchor,
                        candidate,
                        gates=_gates(record),
                    )
                    if not standardized.valid:
                        raise RuntimeError(
                            f"scorable PPA reference failed standardized gates: {path}"
                        )
                    repeat["standardized_scorecard"] = asdict(standardized)
                    repeat["weight_scores"] = {
                        f"{weight:.2f}": 100.0 * hardware_qor(
                            components.performance_ratio,
                            components.area_ratio,
                            performance_weight=weight,
                        )
                        for weight in weights
                    }
            repeats.append(repeat)

        pareto_dominated = any(
            repeat["pareto"]["reference_pareto_dominated"]
            for repeat in repeats
        )
        if class_name == "ppa_reference" and pareto_dominated:
            pareto_dominated_ppa.append(task_id)

        scorable_repeats = [
            repeat for repeat in repeats if "qor_components_exact" in repeat
        ]
        if class_name == "ppa_reference" and not scorable_repeats:
            unscorable_ppa.append(task_id)

        if class_name == "ppa_reference" and scorable_repeats:
            conservative_performance = min(
                repeat["qor_components_exact"]["performance_ratio"]
                for repeat in scorable_repeats
            )
            conservative_area = min(
                repeat["qor_components_exact"]["area_ratio"]
                for repeat in scorable_repeats
            )
            constraint = {
                "task_id": task_id,
                "repeat_count": len(scorable_repeats),
                "conservative_performance_ratio": conservative_performance,
                "conservative_area_ratio": conservative_area,
                "observed_performance_ratio_min": min(
                    repeat["qor_components_exact"]["performance_ratio"]
                    for repeat in scorable_repeats
                ),
                "observed_performance_ratio_max": max(
                    repeat["qor_components_exact"]["performance_ratio"]
                    for repeat in scorable_repeats
                ),
                "observed_area_ratio_min": min(
                    repeat["qor_components_exact"]["area_ratio"]
                    for repeat in scorable_repeats
                ),
                "observed_area_ratio_max": max(
                    repeat["qor_components_exact"]["area_ratio"]
                    for repeat in scorable_repeats
                ),
                "unique_starter_csynth_xml_hashes": sorted({
                    repeat["starter_csynth_xml_sha256"]
                    for repeat in scorable_repeats
                }),
                "unique_reference_csynth_xml_hashes": sorted({
                    repeat["reference_csynth_xml_sha256"]
                    for repeat in scorable_repeats
                }),
                **_weight_boundary(conservative_performance, conservative_area),
            }
            constraint["weight_scores"] = {
                f"{weight:.2f}": 100.0 * hardware_qor(
                    conservative_performance,
                    conservative_area,
                    performance_weight=weight,
                )
                for weight in weights
            }
            conservative_constraints.append(constraint)
            for weight_text, score in constraint["weight_scores"].items():
                score_distributions[weight_text].append(score)

        task_results[task_id] = {
            "classification": first_record["classification"],
            "source_identity": first_record["sources"]["starter_reference_identical"],
            "repeat_count": len(repeats),
            "repeats": repeats,
        }

    lower = 0.5
    upper = 1.0
    infeasible: list[str] = []
    for constraint in conservative_constraints:
        if constraint["kind"] == "lower":
            lower = max(lower, constraint["boundary"])
        elif constraint["kind"] == "upper":
            upper = min(upper, constraint["boundary"])
        elif constraint["kind"] == "none":
            infeasible.append(constraint["task_id"])

    distribution_summary = {}
    for weight_text, scores in sorted(score_distributions.items()):
        distribution_summary[weight_text] = {
            "count": len(scores),
            "minimum": min(scores),
            "maximum": max(scores),
            "below_75": sum(score < 75.0 for score in scores),
            "equal_75": sum(math.isclose(score, 75.0, abs_tol=1e-12) for score in scores),
        }

    final_weight_text = f"{W_PERFORMANCE:.2f}"
    final_scores = score_distributions[final_weight_text]
    nontrivial_constraints = [
        constraint
        for constraint in conservative_constraints
        if constraint["kind"] != "all"
    ]
    nontrivial_final_scores = [
        constraint["weight_scores"][final_weight_text]
        for constraint in nontrivial_constraints
    ]
    binding_lower_task_ids = [
        constraint["task_id"]
        for constraint in conservative_constraints
        if constraint["kind"] == "lower"
        and math.isclose(constraint["boundary"], lower, abs_tol=1e-15)
    ]
    return {
        "schema_version": 1,
        "scoring_version": scoring_version,
        "scoring_schema": SCHEMA_VERSION,
        "weights": {
            "production_performance": W_PERFORMANCE,
            "production_area": 1.0 - W_PERFORMANCE,
            "evaluated_performance_weights": weights,
        },
        "evidence": {
            "roots": [str(root.resolve()) for root in evidence_roots],
            "record_count": len(evidence_paths),
            "unique_task_count": len(grouped),
            "tool_stage_count": 3 * len(evidence_paths),
            "source_identity_record_count": source_identity_record_count,
            "source_identity_xml_match_count": source_identity_xml_match_count,
        },
        "classification_counts": dict(sorted(class_counts.items())),
        "ppa": {
            "scorable_task_count": len(conservative_constraints),
            "unscorable_task_ids": unscorable_ppa,
            "pareto_dominated_task_ids": pareto_dominated_ppa,
            "constraints": conservative_constraints,
        },
        "global_feasible_interval": {
            "performance_priority_domain": "w > 0.5",
            "lower_boundary": lower,
            "upper_boundary": upper,
            "nonempty": not infeasible and lower < upper,
            "infeasible_task_ids": infeasible,
            "chosen_weight": W_PERFORMANCE,
            "chosen_strictly_interior": lower < W_PERFORMANCE < upper,
            "chosen_distance_from_lower": W_PERFORMANCE - lower,
            "chosen_distance_from_upper": upper - W_PERFORMANCE,
            "chosen_minimum_standardized_score": min(final_scores),
            "chosen_minimum_score_margin_above_75": min(final_scores) - 75.0,
            "binding_lower_task_ids": binding_lower_task_ids,
            "nontrivial_constraint_count": len(nontrivial_constraints),
            "chosen_nontrivial_minimum_standardized_score": (
                min(nontrivial_final_scores) if nontrivial_final_scores else None
            ),
            "chosen_nontrivial_score_margin_above_75": (
                min(nontrivial_final_scores) - 75.0
                if nontrivial_final_scores else None
            ),
        },
        "weight_distribution": distribution_summary,
        "tasks": task_results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite output: {args.output}")
    result = analyze(args.evidence_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        f"reference calibration: records={result['evidence']['record_count']} "
        f"tasks={result['evidence']['unique_task_count']} "
        f"scorable_ppa={result['ppa']['scorable_task_count']} "
        f"unscorable_ppa={len(result['ppa']['unscorable_task_ids'])} "
        f"interval=({result['global_feasible_interval']['lower_boundary']}, "
        f"{result['global_feasible_interval']['upper_boundary']}) "
        f"chosen={W_PERFORMANCE} "
        f"output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
