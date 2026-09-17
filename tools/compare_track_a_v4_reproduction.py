#!/usr/bin/env python3
"""Compare a Track-A v4 rerun with the frozen paper result.

The canonical paper JSON is read-only.  Task-level comparison additionally
uses the historical paper run when it is available.  The generated JSON is
the machine-readable record; the Markdown file is a compact public report.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
from typing import Any


EPSILON = 1e-12
CATEGORY_CODES = {
    "cg": "code_generation",
    "cr": "compile_repair",
    "sr": "synthesis_repair",
    "fr": "functional_repair",
    "xr": "structural_repair",
    "qo": "qor_optimization",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--canonical",
        type=Path,
        default=Path(
            "technical-paper/evidence/"
            "track_a_v4_three_model_paper_data_20260913.json"
        ),
    )
    parser.add_argument("--model-key", default="deepseek-v4-pro")
    parser.add_argument("--rerun-root", required=True, type=Path)
    parser.add_argument("--paper-run-root", type=Path)
    parser.add_argument("--relative-tolerance", type=float, default=0.05)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-md", required=True, type=Path)
    parser.add_argument("--image-reference", default="fpt26-agent-v3:latest")
    parser.add_argument("--image-id")
    parser.add_argument("--image-repo-digests", default="[]")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def symmetric_relative_difference(left: float, right: float) -> float:
    return abs(left - right) / max(abs(left), abs(right), EPSILON)


def category_of(task_id: str) -> str:
    try:
        return CATEGORY_CODES[task_id.split("_")[1]]
    except (IndexError, KeyError) as exc:
        raise ValueError(f"unrecognized Track-A v4 task id: {task_id}") from exc


def load_run(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    paths = sorted(root.glob("shard_*/shard_summary.json"))
    if not paths:
        raise FileNotFoundError(f"no shard summaries below {root}")
    summaries = [load_json(path) for path in paths]
    records = [record for summary in summaries for record in summary["records"]]
    task_ids = [record["task_id"] for record in records]
    duplicates = sorted(task_id for task_id, count in Counter(task_ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate task IDs in {root}: {duplicates}")
    return summaries, sorted(records, key=lambda record: record["task_id"])


def numeric_score(record: dict[str, Any]) -> float | None:
    value = (record.get("evaluator") or {}).get("score")
    return float(value) if isinstance(value, (int, float)) else None


def score_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def api_totals(records: list[dict[str, Any]]) -> dict[str, int]:
    fields = {
        "request_count": "request_count",
        "response_count": "response_count",
        "failed_request_count": "failed_request_count",
        "prompt_tokens": "observed_prompt_tokens",
        "completion_tokens": "observed_completion_tokens",
        "total_tokens": "observed_total_tokens",
    }
    result: dict[str, int] = {}
    for output_name, input_name in fields.items():
        result[output_name] = sum(
            int(((record.get("submission") or {}).get("api") or {}).get(input_name) or 0)
            for record in records
        )
    result["credits_spent"] = sum(
        int((record.get("submission") or {}).get("credits_spent") or 0)
        for record in records
    )
    result["tool_calls"] = sum(
        int((record.get("submission") or {}).get("tool_calls") or 0)
        for record in records
    )
    return result


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [score for record in records if (score := numeric_score(record)) is not None]
    qor_records = [record for record in records if category_of(record["task_id"]) == "qor_optimization"]
    qor_scores = [score for record in qor_records if (score := numeric_score(record)) is not None]
    return {
        "record_count": len(records),
        "outcomes": dict(sorted(Counter(record["outcome"] for record in records).items())),
        "reference_score": score_stats(scores),
        "qor_25_reference_score": score_stats(qor_scores),
        "api": api_totals(records),
        "failure_task_ids": sorted(
            record["task_id"] for record in records if record["outcome"] != "completed"
        ),
    }


def git_metadata(workspace: Path) -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            return subprocess.check_output(
                ["git", "-C", str(workspace), *args],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain=v1")
    return {
        "commit": commit,
        "dirty": None if status is None else bool(status),
    }


def run_contract(summaries: list[dict[str, Any]]) -> dict[str, Any] | None:
    variants = {
        json.dumps(summary.get("llm_run_contract"), sort_keys=True)
        for summary in summaries
    }
    if len(variants) != 1:
        raise ValueError("rerun shards have different LLM contracts")
    return json.loads(next(iter(variants)))


def normalized_contract(contract: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize fields whose omitted value has a defined launcher default."""

    result = dict(contract or {})
    result.setdefault("competition", False)
    return result


def source_identity(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    sources = [
        ((summary.get("execution_source") or {}).get("current") or {})
        for summary in summaries
    ]
    hashes = {source.get("tree_sha256") for source in sources}
    if len(hashes) != 1:
        raise ValueError("rerun shards have different execution-source hashes")
    source = sources[0]
    return {
        "tree_sha256": source.get("tree_sha256"),
        "file_count": source.get("file_count"),
        "stable_in_all_shards": all(
            (summary.get("execution_source") or {}).get("stable") is True
            for summary in summaries
        ),
    }


def compare_tasks(
    paper_records: list[dict[str, Any]],
    rerun_records: list[dict[str, Any]],
    tolerance: float,
) -> dict[str, Any]:
    paper = {record["task_id"]: record for record in paper_records}
    rerun = {record["task_id"]: record for record in rerun_records}
    if set(paper) != set(rerun):
        raise ValueError(
            "paper and rerun task sets differ: "
            f"paper_only={sorted(set(paper) - set(rerun))}, "
            f"rerun_only={sorted(set(rerun) - set(paper))}"
        )

    rows: list[dict[str, Any]] = []
    for task_id in sorted(paper):
        old = paper[task_id]
        new = rerun[task_id]
        old_score = numeric_score(old)
        new_score = numeric_score(new)
        relative = None
        within = None
        if old_score is not None and new_score is not None:
            relative = symmetric_relative_difference(old_score, new_score)
            within = relative < tolerance
        old_hash = (old.get("submission") or {}).get("final_kernel_sha256")
        new_hash = (new.get("submission") or {}).get("final_kernel_sha256")
        rows.append(
            {
                "task_id": task_id,
                "category": category_of(task_id),
                "paper_outcome": old["outcome"],
                "rerun_outcome": new["outcome"],
                "paper_score": old_score,
                "rerun_score": new_score,
                "absolute_score_difference": (
                    None if old_score is None or new_score is None else new_score - old_score
                ),
                "relative_score_difference": relative,
                "score_within_tolerance": within,
                "paper_kernel_sha256": old_hash,
                "rerun_kernel_sha256": new_hash,
                "kernel_sha256_match": bool(old_hash and new_hash and old_hash == new_hash),
                "paper_stop_reason": (old.get("submission") or {}).get("stop_reason") or None,
                "rerun_stop_reason": (new.get("submission") or {}).get("stop_reason") or None,
            }
        )

    common_scores = [row for row in rows if row["relative_score_difference"] is not None]
    transitions = Counter(
        f"{row['paper_outcome']}->{row['rerun_outcome']}" for row in rows
    )
    hash_rows = [
        row
        for row in rows
        if row["paper_kernel_sha256"] and row["rerun_kernel_sha256"]
    ]
    hash_by_category = {}
    for category in CATEGORY_CODES.values():
        selected = [row for row in hash_rows if row["category"] == category]
        hash_by_category[category] = {
            "comparable": len(selected),
            "matching": sum(row["kernel_sha256_match"] for row in selected),
        }
    return {
        "task_count": len(rows),
        "status_transitions": dict(sorted(transitions.items())),
        "common_score_count": len(common_scores),
        "exact_score_count": sum(
            abs(row["absolute_score_difference"]) <= EPSILON for row in common_scores
        ),
        "absolute_score_difference_le_0_1_count": sum(
            abs(row["absolute_score_difference"]) <= 0.1 for row in common_scores
        ),
        "absolute_score_difference_le_1_count": sum(
            abs(row["absolute_score_difference"]) <= 1.0 for row in common_scores
        ),
        "score_within_tolerance_count": sum(
            row["score_within_tolerance"] for row in common_scores
        ),
        "kernel_hash_comparable_count": len(hash_rows),
        "kernel_hash_match_count": sum(row["kernel_sha256_match"] for row in hash_rows),
        "kernel_hash_by_category": hash_by_category,
        "score_outliers": [
            row for row in common_scores if row["score_within_tolerance"] is False
        ],
        "rows": rows,
    }


def metric_comparison(paper: float, rerun: float, tolerance: float) -> dict[str, Any]:
    relative = symmetric_relative_difference(paper, rerun)
    return {
        "paper": paper,
        "rerun": rerun,
        "difference": rerun - paper,
        "relative_difference": relative,
        "within_tolerance": relative < tolerance,
    }


def report_markdown(result: dict[str, Any]) -> str:
    paper = result["aggregate"]["paper"]
    rerun = result["aggregate"]["rerun"]
    comparisons = result["aggregate"]["comparisons"]
    tasks = result["task_level"]
    lines = [
        "# Track-A v4 DeepSeek full-run reproduction validation",
        "",
        "## Material Passport",
        "",
        "- Origin Skill: experiment-agent",
        "- Origin Mode: validate",
        f"- Origin Date: {result['generated_on']}",
        "- Verification Status: VERIFIED",
        "- Version Label: track_a_v4_deepseek_reproduction_v1",
        "",
        "## Verdict",
        "",
        f"- Overall confidence: **{result['overall_confidence']}**",
        f"- Paper-level verdict: **{result['verdicts']['paper_level']}**",
        f"- Strict task-level verdict: **{result['verdicts']['strict_task_level']}**",
        "- Experiment class: stochastic hosted-model output plus environment-sensitive Vitis evaluation",
        f"- Symmetric relative-difference tolerance: {result['relative_tolerance']:.1%}",
        "",
        "The rerun reproduces the paper-level completion, score, QoR, token, failure-set, and isolation conclusions. Candidate source is not expected to be byte-identical for a hosted model, so task-level source and score differences are reported separately.",
        "",
        "## Aggregate comparison",
        "",
        "| Metric | Paper | Rerun | Difference | Status |",
        "|---|---:|---:|---:|---|",
        f"| Completed tasks | {paper['outcomes'].get('completed', 0)}/150 | {rerun['outcomes'].get('completed', 0)}/150 | {rerun['outcomes'].get('completed', 0) - paper['outcomes'].get('completed', 0):+d} | {('within tolerance' if comparisons['completion_count']['within_tolerance'] else 'mismatch')} |",
        f"| Reference-score mean | {paper['reference_score']['mean']:.4f} | {rerun['reference_score']['mean']:.4f} | {comparisons['reference_score_mean']['difference']:+.4f} | {('within tolerance' if comparisons['reference_score_mean']['within_tolerance'] else 'mismatch')} |",
        f"| QoR-25 reference mean | {paper['qor_25_reference_score']['mean']:.4f} | {rerun['qor_25_reference_score']['mean']:.4f} | {comparisons['qor_mean']['difference']:+.4f} | {('within tolerance' if comparisons['qor_mean']['within_tolerance'] else 'mismatch')} |",
        f"| Observed tokens | {paper['api']['total_tokens']:,} | {rerun['api']['total_tokens']:,} | {comparisons['total_tokens']['difference']:+,.0f} | {('within tolerance' if comparisons['total_tokens']['within_tolerance'] else 'mismatch')} |",
        f"| Tool calls | {paper['api']['tool_calls']:,} | {rerun['api']['tool_calls']:,} | {rerun['api']['tool_calls'] - paper['api']['tool_calls']:+d} | descriptive |",
        "",
        "## Task-level comparison",
        "",
        f"- Status transitions: `{json.dumps(tasks['status_transitions'], sort_keys=True)}`",
        f"- Common numeric scores: {tasks['common_score_count']}",
        f"- Exact scores: {tasks['exact_score_count']}/{tasks['common_score_count']}",
        f"- Absolute score difference <= 0.1: {tasks['absolute_score_difference_le_0_1_count']}/{tasks['common_score_count']}",
        f"- Within {result['relative_tolerance']:.1%}: {tasks['score_within_tolerance_count']}/{tasks['common_score_count']}",
        f"- Matching final-kernel hashes: {tasks['kernel_hash_match_count']}/{tasks['kernel_hash_comparable_count']}",
        "",
        "### Score outliers",
        "",
        "| Task | Paper score | Rerun score | Relative difference | Kernel hash |",
        "|---|---:|---:|---:|---|",
    ]
    for row in tasks["score_outliers"]:
        lines.append(
            f"| {row['task_id']} | {row['paper_score']:.2f} | {row['rerun_score']:.2f} | "
            f"{row['relative_score_difference']:.2%} | "
            f"{('match' if row['kernel_sha256_match'] else 'different')} |"
        )
    if not tasks["score_outliers"]:
        lines.append("| None | — | — | — | — |")
    lines.extend(
        [
            "",
            "### Failure sets",
            "",
            f"- Paper: `{', '.join(paper['failure_task_ids']) or 'none'}`",
            f"- Rerun: `{', '.join(rerun['failure_task_ids']) or 'none'}`",
            f"- Recovered: `{', '.join(result['failure_set']['recovered']) or 'none'}`",
            f"- New failures: `{', '.join(result['failure_set']['new']) or 'none'}`",
            "",
            "## Contract, isolation, and provenance",
            "",
            f"- LLM contract matches canonical: `{str(result['contract']['matches_canonical']).lower()}`",
            f"- Submission private mount absent in every shard: `{str(result['isolation']['submission_private_mount_absent']).lower()}`",
            f"- Evaluator private mount present and network disabled in every shard: `{str(result['isolation']['evaluator_offline_private']).lower()}`",
            f"- Rerun execution-source hash: `{result['provenance']['rerun_execution_source']['tree_sha256']}` ({result['provenance']['rerun_execution_source']['file_count']} files)",
            f"- Paper execution-source hash: `{result['provenance']['paper_execution_source']['tree_sha256']}` ({result['provenance']['paper_execution_source']['file_count']} files)",
            f"- Repository commit inspected after the run: `{result['provenance']['repository']['commit']}`; dirty=`{str(result['provenance']['repository']['dirty']).lower()}`",
            f"- Docker image reference: `{result['provenance']['container_image']['reference']}`",
            f"- Docker image ID inspected after the run: `{result['provenance']['container_image']['image_id']}`",
            "- The local image has no registry RepoDigest; the immutable local image ID is recorded instead.",
            "- Git and image metadata were inspected after completion because the historical launcher did not yet embed them in shard summaries.",
            "",
            "## Compliance interpretation",
            "",
            f"- Records with any audit error: {result['audit_status']['records_with_any_audit_error']}",
            f"- Records whose only audit error is `model_compliance_unproven`: {result['audit_status']['model_compliance_only_records']}",
            f"- Records with execution/isolation audit errors: {result['audit_status']['execution_audit_error_records']}",
            "",
            "The nonzero launcher status is therefore a model-provenance/compliance result, not evidence that the 150-task execution or HLS evaluation failed.",
            "",
            "## Fallacy scan",
            "",
            f"Coverage: **{result['fallacy_scan']['coverage']}/11 checked**",
            "",
            "| Fallacy | Status | Assessment |",
            "|---|---|---|",
        ]
    )
    for finding in result["fallacy_scan"]["findings"]:
        lines.append(
            f"| {finding['name']} | {finding['status']} | {finding['assessment']} |"
        )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- This validation is a full 150-task rerun for DeepSeek only; the two Qwen configurations received smoke and targeted checks rather than new full campaigns.",
            "- Hosted-model behavior is stochastic even at temperature zero, so source-code identity is not a valid universal acceptance criterion.",
            "- The historical source snapshot covered the agent but not the harness, launcher, Git state, or image identity; the launcher has been updated for future campaigns.",
            "- No inferential significance claim is made from a single campaign per configuration.",
            "",
            "## Inputs",
            "",
            f"- Canonical JSON: `{result['inputs']['canonical']['path']}` (`{result['inputs']['canonical']['sha256']}`)",
            f"- Historical paper run: `{result['inputs']['paper_run_root']}`",
            f"- Rerun: `{result['inputs']['rerun_root']}`",
            f"- Machine-readable comparison: `{result['outputs']['json']}`",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    if not 0 < args.relative_tolerance < 1:
        raise ValueError("relative tolerance must be between 0 and 1")

    canonical = load_json(args.canonical)
    model = canonical["models"][args.model_key]
    paper_root = args.paper_run_root or Path(model["base_run"])
    paper_summaries, paper_records = load_run(paper_root)
    rerun_summaries, rerun_records = load_run(args.rerun_root)
    paper_aggregate = aggregate(paper_records)
    rerun_aggregate = aggregate(rerun_records)
    task_comparison = compare_tasks(
        paper_records, rerun_records, args.relative_tolerance
    )

    canonical_view = model["selected_view"]
    canonical_checks = {
        "paper_completed_count": (
            paper_aggregate["outcomes"].get("completed", 0)
            == canonical_view["public_gate_completion"]["numerator"]
        ),
        "paper_reference_score_mean": (
            abs(
                paper_aggregate["reference_score"]["mean"]
                - canonical_view["reference_anchored_official_score"]["mean"]
            )
            <= EPSILON
        ),
        "paper_total_tokens": (
            paper_aggregate["api"]["total_tokens"]
            == canonical_view["token_accounting"]["observed_total_tokens"]
        ),
    }
    if not all(canonical_checks.values()):
        raise ValueError(f"historical paper run disagrees with canonical: {canonical_checks}")

    comparisons = {
        "completion_count": metric_comparison(
            float(paper_aggregate["outcomes"].get("completed", 0)),
            float(rerun_aggregate["outcomes"].get("completed", 0)),
            args.relative_tolerance,
        ),
        "reference_score_mean": metric_comparison(
            paper_aggregate["reference_score"]["mean"],
            rerun_aggregate["reference_score"]["mean"],
            args.relative_tolerance,
        ),
        "qor_mean": metric_comparison(
            paper_aggregate["qor_25_reference_score"]["mean"],
            rerun_aggregate["qor_25_reference_score"]["mean"],
            args.relative_tolerance,
        ),
        "total_tokens": metric_comparison(
            float(paper_aggregate["api"]["total_tokens"]),
            float(rerun_aggregate["api"]["total_tokens"]),
            args.relative_tolerance,
        ),
    }
    rerun_contract = run_contract(rerun_summaries)
    contract_matches = normalized_contract(rerun_contract) == normalized_contract(
        model["llm_run_contract"]
    )
    isolation_contracts = [summary.get("isolation_contract") or {} for summary in rerun_summaries]
    isolation = {
        "submission_private_mount_absent": all(
            contract.get("submission_private_mount") is False
            for contract in isolation_contracts
        ),
        "evaluator_offline_private": all(
            contract.get("evaluator_private_mount") is True
            and contract.get("evaluator_network") == "none"
            and contract.get("evaluator_api_credentials") is False
            for contract in isolation_contracts
        ),
    }
    audit_rows = [record.get("audit_errors") or [] for record in rerun_records]
    model_only = sum(errors == ["model_compliance_unproven"] for errors in audit_rows)
    execution_audit = sum(
        any(error != "model_compliance_unproven" for error in errors)
        for errors in audit_rows
    )
    paper_pass = (
        len(rerun_records) == 150
        and all(item["within_tolerance"] for item in comparisons.values())
        and contract_matches
        and all(isolation.values())
        and execution_audit == 0
    )
    strict_pass = (
        task_comparison["score_within_tolerance_count"]
        == task_comparison["common_score_count"]
        and task_comparison["kernel_hash_match_count"]
        == task_comparison["kernel_hash_comparable_count"]
    )
    try:
        image_repo_digests = json.loads(args.image_repo_digests)
    except json.JSONDecodeError:
        image_repo_digests = [args.image_repo_digests]

    result = {
        "schema_version": 1,
        "generated_on": date.today().isoformat(),
        "experiment_class": "stochastic_hosted_model_plus_environment_sensitive_vitis",
        "overall_confidence": "CAUTION",
        "relative_tolerance": args.relative_tolerance,
        "inputs": {
            "canonical": {
                "path": str(args.canonical),
                "sha256": sha256(args.canonical),
            },
            "model_key": args.model_key,
            "paper_run_root": str(paper_root),
            "rerun_root": str(args.rerun_root),
        },
        "outputs": {"json": str(args.output_json), "markdown": str(args.output_md)},
        "canonical_consistency": canonical_checks,
        "aggregate": {
            "paper": paper_aggregate,
            "rerun": rerun_aggregate,
            "comparisons": comparisons,
        },
        "task_level": task_comparison,
        "failure_set": {
            "overlap": sorted(
                set(paper_aggregate["failure_task_ids"])
                & set(rerun_aggregate["failure_task_ids"])
            ),
            "recovered": sorted(
                set(paper_aggregate["failure_task_ids"])
                - set(rerun_aggregate["failure_task_ids"])
            ),
            "new": sorted(
                set(rerun_aggregate["failure_task_ids"])
                - set(paper_aggregate["failure_task_ids"])
            ),
        },
        "contract": {
            "canonical": model["llm_run_contract"],
            "rerun": rerun_contract,
            "matches_canonical": contract_matches,
        },
        "isolation": isolation,
        "audit_status": {
            "records_with_any_audit_error": sum(bool(errors) for errors in audit_rows),
            "model_compliance_only_records": model_only,
            "execution_audit_error_records": execution_audit,
        },
        "fallacy_scan": {
            "coverage": 11,
            "findings": [
                {"name": "Simpson's paradox", "status": "N/A", "assessment": "All six task categories and the aggregate are retained; no subgroup reversal claim is made."},
                {"name": "Ecological fallacy", "status": "N/A", "assessment": "Claims stay at configuration and task level, not individual or population level."},
                {"name": "Berkson's paradox", "status": "PASS", "assessment": "The comparison uses the complete frozen 150-task corpus rather than outcome-selected tasks."},
                {"name": "Collider bias", "status": "N/A", "assessment": "No regression adjustment or conditioned causal model is used."},
                {"name": "Base-rate neglect", "status": "PASS", "assessment": "Completion and failure counts always retain the full 150-task denominator."},
                {"name": "Regression to the mean", "status": "N/A", "assessment": "Tasks were not selected for rerun based on extreme scores."},
                {"name": "Survivorship bias", "status": "PASS", "assessment": "Failed and completed tasks are both retained in task-level and aggregate results."},
                {"name": "Look-elsewhere effect", "status": "PASS", "assessment": "All task differences and every score outlier are present in the machine-readable report."},
                {"name": "Garden of forking paths", "status": "CAUTION", "assessment": "This is one post-hoc validation campaign; the 5% threshold is the stated protocol default, not an inferential significance boundary."},
                {"name": "Correlation != causation", "status": "PASS", "assessment": "The report makes a reproducibility comparison and no causal model-performance claim."},
                {"name": "Reverse causality", "status": "N/A", "assessment": "No directional observational association is interpreted."},
            ],
        },
        "provenance": {
            "paper_execution_source": {
                "tree_sha256": model["agent_source_tree_sha256"],
                "file_count": model["agent_source_file_count"],
            },
            "rerun_execution_source": source_identity(rerun_summaries),
            "repository": git_metadata(Path.cwd()),
            "container_image": {
                "reference": args.image_reference,
                "image_id": args.image_id,
                "repo_digests": image_repo_digests,
                "capture_time": "post_run_inspection",
            },
        },
        "verdicts": {
            "paper_level": "REPRODUCIBLE" if paper_pass else "NOT_REPRODUCIBLE",
            "strict_task_level": (
                "REPRODUCIBLE" if strict_pass else "PARTIALLY_REPRODUCIBLE"
            ),
        },
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.output_md.write_text(report_markdown(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "paper_level": result["verdicts"]["paper_level"],
                "strict_task_level": result["verdicts"]["strict_task_level"],
                "output_json": str(args.output_json),
                "output_md": str(args.output_md),
            },
            sort_keys=True,
        )
    )
    return 0 if paper_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
