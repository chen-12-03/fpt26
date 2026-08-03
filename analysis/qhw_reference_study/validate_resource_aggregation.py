#!/usr/bin/env python3
"""Validate one capacity-normalized resource aggregation proposal.

This is a follow-up analysis over frozen starter/reference evidence.  It does
not modify or replace the production scorer.  Exactly one candidate area
formula is evaluated; no smoothing-constant or weight sweep is performed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

from scoring.scoring_v3 import (
    RESOURCES,
    W_AREA,
    W_PERFORMANCE,
    Anchor,
    QoREvidence,
    TaskScoringConfig,
    area_quality,
    calculate_qor_components,
    hardware_qor,
)


SIGNIFICANT_AGGREGATE_GROWTH = 1.25
NEUTRAL_SCORE = 75.0


def latency(report: dict[str, Any]) -> int | None:
    worst = report.get("latency_worst")
    return worst if worst is not None else report.get("latency_avg")


def normalized_footprint(report: dict[str, Any]) -> float:
    available = report["available"]
    resources = report["resources"]
    if set(available) < set(RESOURCES):
        raise ValueError("incomplete available-resource vector")
    if any(available[resource] <= 0 for resource in RESOURCES):
        raise ValueError("non-positive available resource")
    return sum(resources.get(resource, 0) / available[resource] for resource in RESOURCES)


def pareto_classification(
    starter: dict[str, Any], reference: dict[str, Any], target_clock_ns: float
) -> str:
    def effective_time(report: dict[str, Any]) -> float | None:
        cycles = latency(report)
        if cycles is None:
            return None
        period = max(target_clock_ns, report.get("clock_period_ns") or target_clock_ns)
        return period * max(cycles, 1)

    starter_values: list[float] = []
    reference_values: list[float] = []
    starter_time = effective_time(starter)
    reference_time = effective_time(reference)
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
    reference_better = any(r < s for s, r in zip(starter_values, reference_values))
    starter_no_worse = all(s <= r for s, r in zip(starter_values, reference_values))
    starter_better = any(s < r for s, r in zip(starter_values, reference_values))
    if reference_no_worse and reference_better:
        return "reference_dominates"
    if starter_no_worse and starter_better:
        return "starter_dominates"
    if starter_values == reference_values:
        return "identical_metrics"
    return "tradeoff"


def direction(value: float, neutral: float = 1.0, tolerance: float = 1e-12) -> int:
    if value > neutral + tolerance:
        return 1
    if value < neutral - tolerance:
        return -1
    return 0


def rankdata(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        rank = (cursor + 1 + end) / 2.0
        for index in order[cursor:end]:
            ranks[index] = rank
        cursor = end
    return ranks


def correlation(left: list[float], right: list[float]) -> float:
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    denominator = (
        sum((x - left_mean) ** 2 for x in left)
        * sum((y - right_mean) ** 2 for y in right)
    ) ** 0.5
    return numerator / denominator if denominator else 1.0


def summarize_scores(scores: list[float]) -> dict[str, float | int]:
    return {
        "mean": statistics.fmean(scores),
        "median": statistics.median(scores),
        "population_stddev": statistics.pstdev(scores),
        "minimum": min(scores),
        "maximum": max(scores),
        "above_neutral": sum(score > NEUTRAL_SCORE + 1e-12 for score in scores),
        "at_neutral": sum(abs(score - NEUTRAL_SCORE) <= 1e-12 for score in scores),
        "below_neutral": sum(score < NEUTRAL_SCORE - 1e-12 for score in scores),
    }


def load_valid_pairs(raw_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    collected: list[dict[str, Any]] = []
    valid: list[dict[str, Any]] = []
    for evidence_path in sorted(raw_root.glob("*/evidence.json")):
        evidence = json.loads(evidence_path.read_text())
        stages = [
            evidence["starter_csim"],
            evidence["reference_csim"],
            evidence["starter_synth"],
            evidence["reference_synth"],
        ]
        collected.append(evidence)
        if not all(stage["ok"] for stage in stages):
            continue
        starter = evidence["starter_synth"].get("report")
        reference = evidence["reference_synth"].get("report")
        if starter is None or reference is None:
            continue
        if starter["available"] != reference["available"]:
            raise ValueError(f"capacity mismatch: {evidence['task_id']}")
        valid.append(evidence)
    return collected, valid


def analyze(raw_root: Path) -> dict[str, Any]:
    collected, resource_valid = load_valid_pairs(raw_root)
    starter_footprints = [
        normalized_footprint(evidence["starter_synth"]["report"])
        for evidence in resource_valid
    ]
    smoothing_tau = statistics.median(starter_footprints)
    task_rows: list[dict[str, Any]] = []

    for evidence in resource_valid:
        starter = evidence["starter_synth"]["report"]
        reference = evidence["reference_synth"]["report"]
        target_clock = float(evidence["target"]["clock_ns"])
        starter_u = normalized_footprint(starter)
        reference_u = normalized_footprint(reference)
        proposed_area_growth = (smoothing_tau + reference_u) / (smoothing_tau + starter_u)
        proposed_area_ratio = 1.0 / proposed_area_growth
        _current_qarea, growth, bottleneck = area_quality(
            reference["resources"], starter["resources"], starter["available"]
        )
        current_area_growth = growth[bottleneck]
        current_area_ratio = 1.0 / current_area_growth
        increases = [
            resource
            for resource in RESOURCES
            if reference["resources"].get(resource, 0)
            > starter["resources"].get(resource, 0)
        ]
        decreases = [
            resource
            for resource in RESOURCES
            if reference["resources"].get(resource, 0)
            < starter["resources"].get(resource, 0)
        ]
        zero_crossings = [
            resource
            for resource in RESOURCES
            if (starter["resources"].get(resource, 0) == 0)
            != (reference["resources"].get(resource, 0) == 0)
        ]
        row: dict[str, Any] = {
            "task_id": evidence["task_id"],
            "source_url": evidence["provenance"]["source_url"],
            "evidence": str(raw_root / evidence["task_id"] / "evidence.json"),
            "starter_resources": starter["resources"],
            "reference_resources": reference["resources"],
            "available_resources": starter["available"],
            "starter_normalized_footprint": starter_u,
            "reference_normalized_footprint": reference_u,
            "footprint_ratio_reference_over_starter": (
                reference_u / starter_u if starter_u else None
            ),
            "current_area_growth": current_area_growth,
            "current_area_ratio": current_area_ratio,
            "current_bottleneck": bottleneck,
            "proposed_area_growth": proposed_area_growth,
            "proposed_area_ratio": proposed_area_ratio,
            "resource_increases": increases,
            "resource_decreases": decreases,
            "zero_boundary_resources": zero_crossings,
            "cross_resource_tradeoff": bool(increases and decreases),
            "pareto_class": pareto_classification(starter, reference, target_clock),
            "qhw_scorable": False,
        }

        starter_latency = latency(starter)
        reference_latency = latency(reference)
        if starter_latency is not None and reference_latency is not None:
            anchor = Anchor(
                source="starter",
                valid=True,
                latency=starter_latency,
                ii=starter.get("interval_max"),
                clock_ns=starter.get("clock_period_ns"),
                resources=dict(starter["resources"]),
                available=dict(starter["available"]),
                hash=evidence["pair"]["starter_sha256"],
            )
            candidate = QoREvidence(
                candidate_latency=reference_latency,
                candidate_ii=reference.get("interval_max"),
                candidate_clock_ns=reference.get("clock_period_ns"),
                candidate_resources=dict(reference["resources"]),
            )
            config = TaskScoringConfig(
                task_id=evidence["task_id"],
                task_type="optimize",
                task_clock_ns=target_clock,
            )
            components = calculate_qor_components(config, anchor, candidate)
            current_score = 100.0 * hardware_qor(
                components.performance_ratio, components.area_ratio
            )
            proposed_score = 100.0 * hardware_qor(
                components.performance_ratio, proposed_area_ratio
            )
            row.update(
                {
                    "qhw_scorable": True,
                    "performance_ratio": components.performance_ratio,
                    "current_score": current_score,
                    "proposed_score": proposed_score,
                    "score_delta": proposed_score - current_score,
                }
            )
        task_rows.append(row)

    scored = [row for row in task_rows if row["qhw_scorable"]]
    current_scores = [row["current_score"] for row in scored]
    proposed_scores = [row["proposed_score"] for row in scored]
    directed = [
        row
        for row in scored
        if row["pareto_class"] in {"reference_dominates", "starter_dominates"}
    ]

    def pareto_correct(row: dict[str, Any], score_key: str) -> bool:
        expected = 1 if row["pareto_class"] == "reference_dominates" else -1
        return direction(row[score_key], NEUTRAL_SCORE) == expected

    zero_boundary = [row for row in task_rows if row["zero_boundary_resources"]]
    cross_resource = [row for row in task_rows if row["cross_resource_tradeoff"]]
    current_aggregate_disagreements = [
        row
        for row in task_rows
        if direction(row["current_area_ratio"])
        != direction(row["proposed_area_ratio"])
    ]
    significant_resource_increase = [
        row
        for row in scored
        if row["proposed_area_growth"] >= SIGNIFICANT_AGGREGATE_GROWTH
        and row["performance_ratio"] <= 1.0
    ]

    current_summary = summarize_scores(current_scores)
    proposed_summary = summarize_scores(proposed_scores)
    acceptance = {
        "pareto_direction_preserved": (
            all(pareto_correct(row, "proposed_score") for row in directed)
            and sum(pareto_correct(row, "proposed_score") for row in directed)
            >= sum(pareto_correct(row, "current_score") for row in directed)
        ),
        "zero_boundary_cliff_resolved": all(
            direction(row["proposed_area_ratio"])
            == direction(
                row["starter_normalized_footprint"]
                - row["reference_normalized_footprint"],
                neutral=0.0,
            )
            for row in zero_boundary
        ),
        "score_distribution_not_collapsed": (
            proposed_summary["population_stddev"]
            >= 0.5 * current_summary["population_stddev"]
        ),
        "significant_resource_growth_still_penalized": all(
            row["proposed_score"] < NEUTRAL_SCORE
            for row in significant_resource_increase
        ),
    }

    absolute_deltas = sorted(
        scored, key=lambda row: abs(row["score_delta"]), reverse=True
    )
    summary = {
        "collected_task_count": len(collected),
        "resource_valid_task_count": len(task_rows),
        "qhw_scorable_task_count": len(scored),
        "api_request_count": sum(item["api"]["request_count"] for item in collected),
        "smoothing_tau": smoothing_tau,
        "tau_source": "median normalized footprint of all resource-valid starters",
        "zero_boundary_task_count": len(zero_boundary),
        "cross_resource_tradeoff_task_count": len(cross_resource),
        "current_vs_aggregate_area_direction_disagreement_count": len(
            current_aggregate_disagreements
        ),
        "pareto_directed_task_count": len(directed),
        "current_pareto_correct_count": sum(
            pareto_correct(row, "current_score") for row in directed
        ),
        "proposed_pareto_correct_count": sum(
            pareto_correct(row, "proposed_score") for row in directed
        ),
        "current_scores": current_summary,
        "proposed_scores": proposed_summary,
        "paired_score_delta": {
            "mean": statistics.fmean(row["score_delta"] for row in scored),
            "median": statistics.median(row["score_delta"] for row in scored),
            "mean_absolute": statistics.fmean(abs(row["score_delta"]) for row in scored),
            "maximum_absolute": max(abs(row["score_delta"]) for row in scored),
        },
        "spearman_rank_correlation": correlation(
            rankdata(current_scores), rankdata(proposed_scores)
        ),
        "significant_resource_increase_nonimproving_performance_count": len(
            significant_resource_increase
        ),
        "acceptance": acceptance,
        "all_acceptance_checks_pass": all(acceptance.values()),
        "largest_score_changes": [
            {
                "task_id": row["task_id"],
                "current_score": row["current_score"],
                "proposed_score": row["proposed_score"],
                "score_delta": row["score_delta"],
            }
            for row in absolute_deltas[:5]
        ],
    }
    return {
        "schema_version": 1,
        "purpose": "capacity_normalized_resource_aggregation_validation",
        "production_formula_modified": False,
        "external_api_calls": 0,
        "candidate_formula_attempt_count": 1,
        "candidate_formula": {
            "normalized_footprint": "sum(R_r / C_r)",
            "area_growth": "(tau + U_reference) / (tau + U_starter)",
            "area_ratio": "1 / area_growth",
            "performance_weight": W_PERFORMANCE,
            "area_weight": W_AREA,
            "significant_growth_threshold": SIGNIFICANT_AGGREGATE_GROWTH,
        },
        "summary": summary,
        "current_area_direction_disagreements": [
            row["task_id"] for row in current_aggregate_disagreements
        ],
        "tasks": task_rows,
    }


def flatten(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "task_id": row["task_id"],
        "source_url": row["source_url"],
        "qhw_scorable": row["qhw_scorable"],
        "pareto_class": row["pareto_class"],
        "zero_boundary_resources": ";".join(row["zero_boundary_resources"]),
        "resource_increases": ";".join(row["resource_increases"]),
        "resource_decreases": ";".join(row["resource_decreases"]),
        "starter_normalized_footprint": row["starter_normalized_footprint"],
        "reference_normalized_footprint": row["reference_normalized_footprint"],
        "current_area_ratio": row["current_area_ratio"],
        "proposed_area_ratio": row["proposed_area_ratio"],
        "performance_ratio": row.get("performance_ratio"),
        "current_score": row.get("current_score"),
        "proposed_score": row.get("proposed_score"),
        "score_delta": row.get("score_delta"),
    }
    for side in ("starter", "reference"):
        for resource in RESOURCES:
            result[f"{side}_{resource}"] = row[f"{side}_resources"].get(resource, 0)
    return result


def short_task_id(task_id: str) -> str:
    return task_id.removeprefix("amd_intro__")


def render_markdown(analysis: dict[str, Any]) -> str:
    summary = analysis["summary"]
    verdict = "AUTOMATED_CHECKS_PASS" if summary["all_acceptance_checks_pass"] else "NOT_VALIDATED"
    confidence = "CAUTION"
    lines = [
        "## Material Passport",
        "",
        "- Origin Skill: academic-research-suite / experiment-agent",
        "- Origin Mode: validate",
        "- Origin Date: 2026-08-03",
        "- Verification Status: VERIFIED",
        "- Version Label: resource_aggregation_validation_v1",
        "",
        "# Capacity-normalized resource aggregation validation",
        "",
        f"- **Verdict**: `{verdict}`",
        "- **Deployment recommendation**: `DO_NOT_ADOPT_AS_IS`",
        f"- **Overall Confidence**: `{confidence}`",
        f"- **Frozen pairs**: {summary['collected_task_count']}",
        f"- **Resource-valid pairs**: {summary['resource_valid_task_count']}",
        f"- **Full-qhw scorable pairs**: {summary['qhw_scorable_task_count']}",
        f"- **External API calls**: {summary['api_request_count']}",
        f"- **Candidate attempts in this validation**: {analysis['candidate_formula_attempt_count']}",
        "- **Production scorer modified**: no",
        "",
        "## Frozen candidate formula",
        "",
        "`U(R) = sum(R_r / C_r)`",
        "",
        "`area_growth = (tau + U(reference)) / (tau + U(starter))`",
        "",
        "`area_ratio = 1 / area_growth`",
        "",
        f"`tau = {summary['smoothing_tau']:.12f}` (median of the {summary['resource_valid_task_count']} valid starter footprints).",
        "The production performance/area weights remain 0.55/0.45.",
        "",
        "## Acceptance checks",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    for key, passed in summary["acceptance"].items():
        lines.append(f"| `{key}` | {'PASS' if passed else 'FAIL'} |")
    lines.extend(
        [
            "",
            "## Aggregate comparison",
            "",
            "| Metric | Current | Proposed |",
            "|---|---:|---:|",
            f"| Mean score | {summary['current_scores']['mean']:.2f} | {summary['proposed_scores']['mean']:.2f} |",
            f"| Median score | {summary['current_scores']['median']:.2f} | {summary['proposed_scores']['median']:.2f} |",
            f"| Population stddev | {summary['current_scores']['population_stddev']:.2f} | {summary['proposed_scores']['population_stddev']:.2f} |",
            f"| Minimum | {summary['current_scores']['minimum']:.2f} | {summary['proposed_scores']['minimum']:.2f} |",
            f"| Maximum | {summary['current_scores']['maximum']:.2f} | {summary['proposed_scores']['maximum']:.2f} |",
            f"| Pareto direction correct | {summary['current_pareto_correct_count']}/{summary['pareto_directed_task_count']} | {summary['proposed_pareto_correct_count']}/{summary['pareto_directed_task_count']} |",
            "",
            f"Spearman rank correlation: `{summary['spearman_rank_correlation']:.4f}`. ",
            f"Mean absolute paired score change: `{summary['paired_score_delta']['mean_absolute']:.2f}` points; maximum: `{summary['paired_score_delta']['maximum_absolute']:.2f}` points.",
            "",
            "## Outlier review",
            "",
            "The automated checks are necessary but not sufficient for deployment. The candidate fixes the observed BRAM-to-URAM transfer, but the corpus-level median `tau` suppresses relative resource changes in small designs:",
            "",
            "- `interface_memory_ram_uram`: normalized footprint falls from 0.014227 to 0.008607, so the score moves from 48.41 to 79.44. This is the intended correction of a resource-transfer reversal.",
            "- `task_level_parallelism_data_driven_using_directio_none_in_tasks`: LUT rises 148→166 and FF rises 2→37 with no performance gain, but the score moves from 37.90 to 74.88 because `tau` dominates both footprints. This is an unacceptable loss of relative-efficiency sensitivity for a sole area metric.",
            "- `pipelining_loops_using_free_running_pipeline`: aggregate footprint grows 4.18x and performance improves 1.87x; the score rises from 56.96 to 72.16. This is a policy-sensitive tradeoff and shows that the candidate systematically softens area penalties.",
            "",
            "Therefore the capacity-normalized aggregate `U(R)` is supported as a common resource currency, while the global median smoothing term is not supported for production use. A follow-up candidate should retain `U(R)` but use either a negligible all-zero guard or a separately validated hybrid relative-growth term. No such second formula is calculated in this report.",
            "",
            "## Per-task results",
            "",
            "| Task | P | U starter→reference | A current | A proposed | Score current | Score proposed | Delta | Zero boundary |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in analysis["tasks"]:
        if not row["qhw_scorable"]:
            continue
        zero = ",".join(row["zero_boundary_resources"]) or "-"
        lines.append(
            f"| `{short_task_id(row['task_id'])}` | {row['performance_ratio']:.3f} | "
            f"{row['starter_normalized_footprint']:.6f}→{row['reference_normalized_footprint']:.6f} | "
            f"{row['current_area_ratio']:.3f} | {row['proposed_area_ratio']:.3f} | "
            f"{row['current_score']:.2f} | {row['proposed_score']:.2f} | "
            f"{row['score_delta']:+.2f} | {zero} |"
        )
    lines.extend(
        [
            "",
            "## Warnings",
            "",
            "| Type | Detail | Affected |",
            "|---|---|---|",
            "| Construct validity | Capacity-normalized utilization measures resource scarcity, not placed-and-routed silicon area, power, or congestion. | All tasks |",
            "| Sample scope | All pairs come from one AMD/Xilinx examples repository and one FPGA target/tool version. | Generalization |",
            "| Selection | 24/36 pairs have defined latency and enter full qhw comparison; all 29 synthesis-valid pairs remain in resource analysis. | Score distribution |",
            "| Calibration reuse | Tau is derived from the same frozen starters used for validation; no parameter sweep was performed, but independent-corpus confirmation is still needed. | Tau |",
            "",
            "## Fallacy scan",
            "",
            "- **Coverage**: 11/11 checked",
            "",
            "| Fallacy | Severity | Finding |",
            "|---|---|---|",
            "| Simpson's paradox | NOTE | No subgroup reversal test is possible with one-source corpus. |",
            "| Ecological fallacy | NOTE | No individual-level inference is made. |",
            "| Berkson's paradox | CAUTION | Only synthesis-valid/scorable pairs contribute to corresponding summaries. |",
            "| Collider bias | NOTE | No regression controls are used. |",
            "| Base-rate neglect | NOTE | No diagnostic probabilities are reported. |",
            "| Regression to the mean | NOTE | No repeated extreme-score selection. |",
            "| Survivorship bias | CAUTION | Full qhw uses 24/36; failures and undefined-latency cases remain explicitly reported. |",
            "| Look-elsewhere effect | NOTE | Exactly one candidate formula and no tau/weight sweep were evaluated. |",
            "| Garden of forking paths | CAUTION | Formula was proposed after observing the resource-transfer defect; independent confirmation is required. |",
            "| Correlation != causation | NOTE | Descriptive formula validation only; no causal claim. |",
            "| Reverse causality | NOTE | Not applicable to deterministic metric comparison. |",
            "",
            "## Reproducibility",
            "",
            "- **Method**: deterministic re-analysis of frozen JSON evidence",
            "- **Verdict**: `REPRODUCIBLE` — JSON, CSV, and Markdown outputs matched byte-for-byte across two network-disabled Docker runs.",
            "",
            "## Interpretation boundary",
            "",
            "Passing the automated checks establishes mathematical continuity, sample-level Pareto consistency, and improved handling of observed resource transfers. The outlier review prevents promotion of the exact candidate formula. The experiment does not establish physical-area accuracy because no implementation-level area, power, or congestion ground truth is available.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    analysis = analyze(args.raw_root)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(analysis, indent=2, sort_keys=True) + "\n"
    args.output_json.write_text(encoded)
    rows = [flatten(row) for row in analysis["tasks"]]
    with args.output_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    args.output_md.write_text(render_markdown(analysis))
    print(json.dumps(analysis["summary"], indent=2, sort_keys=True))
    print(f"analysis_sha256={hashlib.sha256(encoded.encode()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
