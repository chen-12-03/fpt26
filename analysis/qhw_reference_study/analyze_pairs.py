#!/usr/bin/env python3
"""Analyze frozen pair evidence with current weights and one alternative.

Exactly one non-production coefficient pair is evaluated: performance/area
0.60/0.40.  The production scorer remains unchanged.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scoring.scoring_v3 import (
    RESOURCES,
    W_AREA,
    W_PERFORMANCE,
    Anchor,
    QoREvidence,
    TaskScoringConfig,
    calculate_qor_components,
    hardware_qor,
)


ALTERNATIVE_PERFORMANCE_WEIGHT = 0.60
ALTERNATIVE_AREA_WEIGHT = 0.40


def latency(report: dict[str, Any]) -> int | None:
    return report.get("latency_worst") or report.get("latency_avg")


def effective_time(report: dict[str, Any], target_clock_ns: float) -> float | None:
    cycles = latency(report)
    if cycles is None:
        return None
    period = max(target_clock_ns, report.get("clock_period_ns") or target_clock_ns)
    return period * max(cycles, 1)


def pareto_classification(
    starter: dict[str, Any], reference: dict[str, Any], target_clock_ns: float
) -> str:
    starter_values: list[float] = []
    reference_values: list[float] = []
    starter_time = effective_time(starter, target_clock_ns)
    reference_time = effective_time(reference, target_clock_ns)
    if starter_time is not None and reference_time is not None:
        starter_values.append(starter_time)
        reference_values.append(reference_time)
    starter_ii = starter.get("interval_max")
    reference_ii = reference.get("interval_max")
    if starter_ii is not None and reference_ii is not None:
        starter_values.append(float(starter_ii))
        reference_values.append(float(reference_ii))
    for resource in RESOURCES:
        starter_values.append(float(starter["resources"].get(resource, 0)))
        reference_values.append(float(reference["resources"].get(resource, 0)))

    reference_no_worse = all(r <= s for s, r in zip(starter_values, reference_values))
    reference_strict_better = any(r < s for s, r in zip(starter_values, reference_values))
    starter_no_worse = all(s <= r for s, r in zip(starter_values, reference_values))
    starter_strict_better = any(s < r for s, r in zip(starter_values, reference_values))
    if reference_no_worse and reference_strict_better:
        return "reference_dominates"
    if starter_no_worse and starter_strict_better:
        return "starter_dominates"
    if starter_values == reference_values:
        return "identical_metrics"
    return "tradeoff"


def source_audit_map(path: Path) -> dict[str, dict[str, Any]]:
    audit = json.loads(path.read_text())
    return {record["task_id"]: record for record in audit["tasks"]}


def analyze(raw_root: Path, upstream_audit: Path) -> dict[str, Any]:
    audit_by_task = source_audit_map(upstream_audit)
    results: list[dict[str, Any]] = []
    for evidence_path in sorted(raw_root.glob("*/evidence.json")):
        evidence = json.loads(evidence_path.read_text())
        stages = (
            evidence["starter_csim"],
            evidence["reference_csim"],
            evidence["starter_synth"],
            evidence["reference_synth"],
        )
        all_stages_pass = all(stage["ok"] for stage in stages)
        starter_report = evidence["starter_synth"].get("report")
        reference_report = evidence["reference_synth"].get("report")
        target_clock = float(evidence["target"]["clock_ns"])
        task_result: dict[str, Any] = {
            "task_id": evidence["task_id"],
            "evidence": str(evidence_path),
            "source_url": evidence["provenance"]["source_url"],
            "source_path": evidence["provenance"]["source_path"],
            "repo_commit": evidence["provenance"]["repo_commit"],
            "source_sha256": evidence["provenance"]["source_sha256"],
            "upstream_hash_verified": audit_by_task[evidence["task_id"]][
                "source_hash_match"
            ],
            "starter_sha256": evidence["pair"]["starter_sha256"],
            "reference_sha256": evidence["pair"]["reference_sha256"],
            "removed_directive_count": evidence["pair"][
                "removed_directive_count"
            ],
            "removed_directives": evidence["pair"]["removed_directives"],
            "starter_csim_pass": evidence["starter_csim"]["ok"],
            "reference_csim_pass": evidence["reference_csim"]["ok"],
            "starter_synth_pass": evidence["starter_synth"]["ok"],
            "reference_synth_pass": evidence["reference_synth"]["ok"],
            "all_stages_pass": all_stages_pass,
            "api_request_count": evidence["api"]["request_count"],
            "starter": starter_report,
            "reference": reference_report,
            "scorable": False,
            "unscorable_reason": "",
        }
        if not all_stages_pass:
            task_result["unscorable_reason"] = "one_or_more_tool_stages_failed"
            results.append(task_result)
            continue
        if starter_report is None or reference_report is None:
            task_result["unscorable_reason"] = "missing_synthesis_report"
            results.append(task_result)
            continue
        if latency(starter_report) is None or latency(reference_report) is None:
            task_result["unscorable_reason"] = "latency_undef"
            task_result["pareto_class"] = pareto_classification(
                starter_report, reference_report, target_clock
            )
            results.append(task_result)
            continue

        anchor = Anchor(
            source="starter",
            valid=True,
            latency=latency(starter_report),
            ii=starter_report.get("interval_max"),
            clock_ns=starter_report.get("clock_period_ns"),
            resources=dict(starter_report["resources"]),
            available=dict(starter_report["available"]),
            hash=evidence["pair"]["starter_sha256"],
        )
        candidate = QoREvidence(
            candidate_latency=latency(reference_report),
            candidate_ii=reference_report.get("interval_max"),
            candidate_clock_ns=reference_report.get("clock_period_ns"),
            candidate_resources=dict(reference_report["resources"]),
        )
        cfg = TaskScoringConfig(
            task_id=evidence["task_id"],
            task_type="optimize",
            task_clock_ns=target_clock,
        )
        components = calculate_qor_components(cfg, anchor, candidate)
        current_qhw = hardware_qor(
            components.performance_ratio,
            components.area_ratio,
        )
        alternative_qhw = hardware_qor(
            components.performance_ratio,
            components.area_ratio,
            performance_weight=ALTERNATIVE_PERFORMANCE_WEIGHT,
        )
        task_result.update(
            {
                "scorable": True,
                "unscorable_reason": "",
                "qor_components": asdict(components),
                "pareto_class": pareto_classification(
                    starter_report, reference_report, target_clock
                ),
                "current": {
                    "performance_weight": W_PERFORMANCE,
                    "area_weight": W_AREA,
                    "q_hw": current_qhw,
                    "standardized_score": 100.0 * current_qhw,
                },
                "alternative": {
                    "performance_weight": ALTERNATIVE_PERFORMANCE_WEIGHT,
                    "area_weight": ALTERNATIVE_AREA_WEIGHT,
                    "q_hw": alternative_qhw,
                    "standardized_score": 100.0 * alternative_qhw,
                },
            }
        )
        results.append(task_result)

    scorable = [result for result in results if result["scorable"]]
    current_scores = [result["current"]["standardized_score"] for result in scorable]
    alternative_scores = [
        result["alternative"]["standardized_score"] for result in scorable
    ]
    current_sign_correct = [
        (result["current"]["standardized_score"] > 75.0)
        == (result["pareto_class"] == "reference_dominates")
        for result in scorable
        if result["pareto_class"] in {"reference_dominates", "starter_dominates"}
    ]
    alternative_sign_correct = [
        (result["alternative"]["standardized_score"] > 75.0)
        == (result["pareto_class"] == "reference_dominates")
        for result in scorable
        if result["pareto_class"] in {"reference_dominates", "starter_dominates"}
    ]
    return {
        "schema_version": 1,
        "purpose": "qhw_starter_reference_study_analysis",
        "formula_source": "fpt26-agent-v3/scoring/scoring_v3.py",
        "production_weights": {
            "performance": W_PERFORMANCE,
            "area": W_AREA,
        },
        "alternative_attempt_count": 1,
        "alternative_weights": {
            "performance": ALTERNATIVE_PERFORMANCE_WEIGHT,
            "area": ALTERNATIVE_AREA_WEIGHT,
        },
        "score_mode": "standardized_qor_efficiency_1",
        "ii_applied_to_score": False,
        "summary": {
            "collected_task_count": len(results),
            "all_four_stages_pass_count": sum(r["all_stages_pass"] for r in results),
            "scorable_task_count": len(scorable),
            "unscorable_task_count": len(results) - len(scorable),
            "api_request_count": sum(r["api_request_count"] for r in results),
            "pareto_counts": {
                key: sum(r.get("pareto_class") == key for r in results)
                for key in (
                    "reference_dominates",
                    "starter_dominates",
                    "tradeoff",
                    "identical_metrics",
                )
            },
            "current_score_mean": statistics.fmean(current_scores),
            "current_score_median": statistics.median(current_scores),
            "alternative_score_mean": statistics.fmean(alternative_scores),
            "alternative_score_median": statistics.median(alternative_scores),
            "current_pareto_direction_accuracy": (
                statistics.fmean(current_sign_correct) if current_sign_correct else None
            ),
            "alternative_pareto_direction_accuracy": (
                statistics.fmean(alternative_sign_correct)
                if alternative_sign_correct
                else None
            ),
            "current_above_neutral_count": sum(score > 75.0 for score in current_scores),
            "alternative_above_neutral_count": sum(
                score > 75.0 for score in alternative_scores
            ),
        },
        "tasks": results,
    }


def flatten_for_csv(task: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "task_id": task["task_id"],
        "source_url": task["source_url"],
        "source_sha256": task["source_sha256"],
        "upstream_hash_verified": task["upstream_hash_verified"],
        "starter_sha256": task["starter_sha256"],
        "reference_sha256": task["reference_sha256"],
        "removed_directive_count": task["removed_directive_count"],
        "starter_csim_pass": task["starter_csim_pass"],
        "reference_csim_pass": task["reference_csim_pass"],
        "starter_synth_pass": task["starter_synth_pass"],
        "reference_synth_pass": task["reference_synth_pass"],
        "scorable": task["scorable"],
        "unscorable_reason": task["unscorable_reason"],
        "pareto_class": task.get("pareto_class", ""),
    }
    for side in ("starter", "reference"):
        report = task.get(side) or {}
        row[f"{side}_latency_best"] = report.get("latency_best")
        row[f"{side}_latency_avg"] = report.get("latency_avg")
        row[f"{side}_latency_worst"] = report.get("latency_worst")
        row[f"{side}_ii"] = report.get("interval_max")
        row[f"{side}_clock_ns"] = report.get("clock_period_ns")
        resources = report.get("resources", {})
        for resource in RESOURCES:
            row[f"{side}_{resource}"] = resources.get(resource)
    components = task.get("qor_components", {})
    row["performance_ratio"] = components.get("performance_ratio")
    row["area_ratio"] = components.get("area_ratio")
    row["area_growth"] = components.get("area_growth")
    row["bottleneck_resource"] = components.get("bottleneck_resource")
    row["current_score_0.55_0.45"] = task.get("current", {}).get(
        "standardized_score"
    )
    row["alternative_score_0.60_0.40"] = task.get("alternative", {}).get(
        "standardized_score"
    )
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--upstream-audit", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    args = parser.parse_args()

    analysis = analyze(args.raw_root, args.upstream_audit)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(analysis, indent=2, sort_keys=True) + "\n"
    args.output_json.write_text(encoded)
    rows = [flatten_for_csv(task) for task in analysis["tasks"]]
    with args.output_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(analysis["summary"], indent=2, sort_keys=True))
    print(f"analysis_sha256={hashlib.sha256(encoded.encode()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
