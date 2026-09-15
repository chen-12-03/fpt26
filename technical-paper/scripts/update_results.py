#!/usr/bin/env python3
"""Regenerate paper macros from the committed Track-A v4 evidence."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


MODEL_SPECS = (
    ("DeepSeek", "deepseek-v4-pro", "DeepSeek V4 Pro", False),
    ("QwenThreeFive", "qwen3.5-122b-a10b", "Qwen3.5-122B-A10B", True),
    ("QwenThreeSix", "qwen3.6-27b", "Qwen3.6-27B", True),
)

CATEGORY_ORDER = (
    "code_generation",
    "compile_repair",
    "synthesis_repair",
    "functional_repair",
    "structural_repair",
    "qor_optimization",
)


def command(name: str, value: str) -> str:
    return rf"\newcommand{{\{name}}}{{{value}}}"


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def percent(value: float) -> str:
    return f"{value:.1f}\\%"


def millions(value: int) -> str:
    return f"{value / 1_000_000:.3f}"


def validate_inputs(data: dict[str, Any], mapping: dict[str, Any]) -> None:
    if data.get("schema_version") != 1:
        raise ValueError("unsupported paper-data schema")
    if mapping.get("schema_version") != 1:
        raise ValueError("unsupported evaluator-mapping schema")

    task_count = int(data["frozen_release"]["task_count"])
    tasks = mapping["tasks"]
    if mapping.get("task_count") != task_count or len(tasks) != task_count:
        raise ValueError("paper data and evaluator mapping use different task counts")
    if len({row["public_task_id"] for row in tasks}) != task_count:
        raise ValueError("evaluator mapping contains duplicate public task IDs")

    expected_models = {key for _, key, _, _ in MODEL_SPECS}
    if set(data["models"]) != expected_models:
        raise ValueError("paper data does not contain the expected three endpoints")
    for _, key, _, _ in MODEL_SPECS:
        view = data["models"][key]["selected_view"]
        if view["public_gate_completion"]["denominator"] != task_count:
            raise ValueError(f"{key}: selected view has the wrong denominator")
        if set(view["categories"]) != set(CATEGORY_ORDER):
            raise ValueError(f"{key}: category set differs from the paper contract")

    common = data["common_qor_subset"]
    if common["task_count"] != len(common["task_ids"]):
        raise ValueError("common QoR task count does not match its ID list")


def corpus_counts(mapping: dict[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in mapping["tasks"]:
        url = row["source_url"]
        if "/sharc-lab/hls-eval/" in url:
            counts["hls_eval"] += 1
        elif "/Xilinx/Vitis-HLS-Introductory-Examples/" in url:
            counts["intro"] += 1
        elif "/Xilinx/Vitis_Accel_Examples/" in url:
            counts["accel"] += 1
        elif "/Xilinx/Vitis-HLS-Performance-Pragma/" in url:
            counts["performance_pragma"] += 1
        else:
            raise ValueError(f"unclassified source URL: {url}")
    return counts


def render_results(data: dict[str, Any], mapping: dict[str, Any]) -> str:
    task_count = int(data["frozen_release"]["task_count"])
    generated_on = data["generated_on"]
    source_counts = corpus_counts(mapping)
    unique_sources = len({row["source_path"] for row in mapping["tasks"]})
    first_view = data["models"][MODEL_SPECS[0][1]]["selected_view"]
    tasks_per_category = first_view["categories"][CATEGORY_ORDER[0]]["task_count"]
    required_cosim = first_view["categories"]["structural_repair"]["task_count"]

    lines = [
        f"% Audited from the canonical Track-A v4 dataset generated on {generated_on}.",
        "% Source: evidence/track_a_v4_three_model_paper_data_20260913.json",
        "% Primary comparison: one final selected-record campaign result per endpoint.",
        command("CorpusTaskCount", str(task_count)),
        command("TasksPerCategory", str(tasks_per_category)),
        command("RequiredCosimTaskCount", str(required_cosim)),
        command("TotalModelTaskRuns", str(task_count * len(MODEL_SPECS))),
        "",
        "% Frozen v4 corpus provenance.",
        command("HLSEvalTaskCount", str(source_counts["hls_eval"])),
        command("IntroExampleTaskCount", str(source_counts["intro"])),
        command("AccelExampleTaskCount", str(source_counts["accel"])),
        command("PerformancePragmaTaskCount", str(source_counts["performance_pragma"])),
        command("UniqueSourcePathCount", str(unique_sources)),
    ]

    for prefix, key, display, lower_bound in MODEL_SPECS:
        row = data["models"][key]
        view = row["selected_view"]
        outcomes = view["outcomes"]
        public = view["public_gate_completion"]
        api_clean = view["api_clean_agent_completion"]
        qor = view["qor_25"]
        selected_tokens = view["token_accounting"]
        all_tokens = row["selection"]["all_attempt_token_accounting"]
        common = data["common_qor_subset"]["models"][key]
        comments = [f"% {display}."]
        if lower_bound:
            if prefix == "QwenThreeFive":
                comments = [
                    f"% {display}. Token totals are lower bounds because failed requests",
                    "% omit usage.",
                ]
            else:
                comments = [
                    f"% {display}. Token totals are lower bounds because failed requests omit usage."
                ]
        lines.extend(
            [
                "",
                *comments,
                command(f"{prefix}SuccessCount", str(public["numerator"])),
                command(f"{prefix}FailureCount", str(outcomes.get("failed", 0))),
                command(
                    f"{prefix}InfrastructureErrorCount",
                    str(outcomes.get("infrastructure_error", 0)),
                ),
                command(f"{prefix}SuccessRate", percent(public["percent"])),
                command(f"{prefix}ApiCleanCount", str(api_clean["numerator"])),
                command(f"{prefix}ApiCleanDenominator", str(api_clean["denominator"])),
                command(f"{prefix}ApiCleanRate", percent(api_clean["percent"])),
                command(f"{prefix}QorProxyCount", str(qor["available_count"])),
                command(
                    f"{prefix}QorProxy",
                    f"{qor['submission_starter_anchored_proxy']['mean']:.2f}",
                ),
                command(
                    f"{prefix}CommonQorProxy",
                    f"{common['submission_starter_anchored_proxy_mean']:.2f}",
                ),
                command(
                    f"{prefix}TokensM",
                    millions(selected_tokens["observed_total_tokens"]),
                ),
                command(
                    f"{prefix}AllAttemptTokensM",
                    millions(all_tokens["observed_total_tokens"]),
                ),
                command(f"{prefix}Credits", f"{selected_tokens['credits_spent']:,}"),
                command(
                    f"{prefix}ToolCalls", str(selected_tokens["submission_tool_calls"])
                ),
                command(f"{prefix}ApiRequests", str(selected_tokens["request_count"])),
                command(f"{prefix}ApiResponses", str(selected_tokens["response_count"])),
                command(
                    f"{prefix}ApiFailures", str(selected_tokens["failed_request_count"])
                ),
            ]
        )

    category_rows = []
    token_rows = []
    for _, key, display, lower_bound in MODEL_SPECS:
        view = data["models"][key]["selected_view"]
        category_rows.append(
            " & ".join(
                [display]
                + [
                    f"{view['categories'][category]['outcomes'].get('completed', 0)}/"
                    f"{view['categories'][category]['task_count']}"
                    for category in CATEGORY_ORDER
                ]
            )
            + r" \\"
        )
        selected_total = millions(view["token_accounting"]["observed_total_tokens"])
        all_total = millions(
            data["models"][key]["selection"]["all_attempt_token_accounting"][
                "observed_total_tokens"
            ]
        )
        marker = r"$\geq$" if lower_bound else ""
        token_rows.append(
            " & ".join(
                [
                    display,
                    marker + selected_total,
                    marker + all_total,
                    f"{view['token_accounting']['credits_spent']:,}",
                ]
            )
            + r" \\"
        )
    lines.extend(
        [
            "",
            "% Repository-only appendix rows, ordered as code generation, compile repair,",
            "% synthesis repair, functional repair, structural repair, and QoR optimization.",
            command("CategorySuccessRows", "%\n" + "\n".join(category_rows) + "\n"),
            command("TokenAccountingRows", "%\n" + "\n".join(token_rows) + "\n"),
        ]
    )
    return "\n".join(lines) + "\n"


def render_evaluator_results(data: dict[str, Any]) -> str:
    lines = [
        "% Audited from evidence/track_a_v4_three_model_paper_data_20260913.json.",
        "% Counts use the final selected record for every task.",
    ]
    total_evaluated = 0
    total_hidden = 0
    for prefix, key, display, _ in MODEL_SPECS:
        view = data["models"][key]["selected_view"]
        hidden = view["evaluator_hidden_correctness"]
        reference = view["reference_anchored_official_score"]
        qor = view["qor_25"]["evaluator_reference_anchored_score"]
        common = data["common_qor_subset"]["models"][key]
        total_evaluated += hidden["denominator"]
        total_hidden += hidden["numerator"]
        lines.extend(
            [
                "",
                f"% {display}.",
                command(f"{prefix}EvaluatorReportCount", str(hidden["denominator"])),
                command(f"{prefix}HiddenCorrectCount", str(hidden["numerator"])),
                command(f"{prefix}ReferenceScoreableCount", str(reference["count"])),
                command(
                    f"{prefix}ValidityOnlyCount",
                    str(reference["validity_only_completed_count"]),
                ),
                command(f"{prefix}ReferenceMeanScoreable", f"{reference['mean']:.2f}"),
                command(f"{prefix}ReferenceQorScoreableCount", str(qor["count"])),
                command(f"{prefix}ReferenceQorMean", f"{qor['mean']:.2f}"),
                command(
                    f"{prefix}CommonReferenceQorMean",
                    f"{common['evaluator_reference_anchored_score_mean']:.2f}",
                ),
            ]
        )
    lines.extend(
        [
            "",
            "% Aggregate and paired-comparison subset.",
            command("IndependentEvaluatedCount", str(total_evaluated)),
            command("IndependentHiddenCorrectCount", str(total_hidden)),
            command("CommonQorTaskCount", str(data["common_qor_subset"]["task_count"])),
        ]
    )
    return "\n".join(lines) + "\n"


def write_or_check(path: Path, rendered: str, check: bool) -> None:
    if check:
        if not path.is_file() or path.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"generated output is stale: {path}")
        print(f"verified {path}")
        return
    path.write_text(rendered, encoding="utf-8")
    print(f"wrote {path}")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=repo_root
        / "technical-paper/evidence/track_a_v4_three_model_paper_data_20260913.json",
    )
    parser.add_argument("--mapping", type=Path)
    parser.add_argument(
        "--results-output",
        type=Path,
        default=repo_root / "technical-paper/results_generated.tex",
    )
    parser.add_argument(
        "--evaluator-output",
        type=Path,
        default=repo_root / "technical-paper/evaluator_results_generated.tex",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify committed outputs without writing files",
    )
    args = parser.parse_args()

    data = load_json(args.input)
    mapping_path = args.mapping
    if mapping_path is None:
        mapping_path = (
            repo_root
            / data["frozen_release"]["path"]
            / "evaluator_private/EVALUATOR_MAPPING.json"
        )
    mapping = load_json(mapping_path)
    validate_inputs(data, mapping)
    write_or_check(args.results_output, render_results(data, mapping), args.check)
    write_or_check(
        args.evaluator_output,
        render_evaluator_results(data),
        args.check,
    )


if __name__ == "__main__":
    main()
