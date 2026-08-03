#!/usr/bin/env python3
"""Independent fail-closed checks for the 36-pair reference-score search."""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
from pathlib import Path


RESOURCES = ("LUT", "FF", "DSP", "BRAM_18K", "URAM")


def ratio_quality(ratio: float) -> float:
    return 1.0 - 1.0 / (1.0 + max(ratio, 0.0)) ** 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--analysis-json", type=Path, required=True)
    parser.add_argument("--analysis-csv", type=Path, required=True)
    parser.add_argument("--analysis-md", type=Path, required=True)
    parser.add_argument("--search-script", type=Path, required=True)
    args = parser.parse_args()

    ast.parse(args.search_script.read_text(), filename=str(args.search_script))
    analysis = json.loads(args.analysis_json.read_text())
    evidence_paths = sorted(args.raw_root.glob("*/evidence.json"))
    evidence = [json.loads(path.read_text()) for path in evidence_paths]
    tasks = analysis["tasks"]
    task_ids = [task["task_id"] for task in tasks]

    assert analysis["production_formula_modified"] is False
    assert analysis["external_api_calls"] == 0
    assert analysis["recommended_scope"] == "reference_validation_only_not_general_candidate_qor"
    assert len(evidence) == len(tasks) == 36
    assert len(set(task_ids)) == 36
    assert set(task_ids) == {item["task_id"] for item in evidence}
    assert all(item["api"]["request_count"] == 0 for item in evidence)
    assert all(
        item["pair"]["starter_sha256"] != item["pair"]["reference_sha256"]
        for item in evidence
    )
    assert all(item["reference_csim"]["ok"] and item["reference_synth"]["ok"] for item in evidence)

    for task in tasks:
        expected_source = 1.01 if task["source_different"] else 1.0
        expected_validity = 2.0 if task["validity_rescue"] else 1.0
        expected_performance = max(1.0, task["performance_ratio"]) ** 0.55
        expected_area = max(1.0, task["area_ratio"]) ** 0.45
        expected_ratio = (
            expected_source
            * expected_validity
            * expected_performance
            * expected_area
        )
        expected_score = (
            100.0 * int(task["reference_valid"]) * ratio_quality(expected_ratio)
        )
        assert math.isclose(task["source_factor"], expected_source, rel_tol=0, abs_tol=1e-15)
        assert math.isclose(task["validity_factor"], expected_validity, rel_tol=0, abs_tol=1e-15)
        assert math.isclose(task["evidence_ratio"], expected_ratio, rel_tol=0, abs_tol=1e-12)
        assert math.isclose(task["final_reference_score"], expected_score, rel_tol=0, abs_tol=1e-12)
        if task["source_different"]:
            assert task["final_reference_score"] > 75.0
        for side in ("starter_resources", "reference_resources"):
            resources = task[side]
            if resources is not None:
                assert set(resources) >= set(RESOURCES)

    summary = analysis["summary"]
    assert summary["pair_count"] == 36
    assert summary["strict_above_75_required_count"] == 36
    assert summary["strict_above_75_pass_count"] == 36
    assert summary["all_required_pairs_strictly_above_75"] is True
    assert summary["minimum_final_score"] > 75.0
    assert summary["reference_valid_count"] == 36
    assert summary["source_different_count"] == 36
    assert summary["raw_hardware_identical_count"] == 7
    assert summary["starter_dominates_count"] == 6
    assert summary["validity_rescue_count"] == 7
    assert sum(item.get("recommended", False) for item in analysis["search_comparison"]) == 1
    assert next(
        item for item in analysis["search_comparison"] if item.get("recommended")
    )["meets_all_36"] is True

    with args.analysis_csv.open(newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == 36
    assert {row["task_id"] for row in csv_rows} == set(task_ids)
    markdown = args.analysis_md.read_text()
    assert "Required pairs above 75: **36/36**" in markdown
    assert "DO NOT use this formula" not in markdown
    assert "Do not use this formula to rank arbitrary agent submissions" in markdown
    assert all(task_id.removeprefix("amd_intro__") in markdown for task_id in task_ids)

    print(
        "verified: 36/36 source-different valid references score >75; "
        "formula recomputed independently; API requests=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
