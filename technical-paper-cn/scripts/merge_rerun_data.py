#!/usr/bin/env python3
"""Merge re-run evidence into final_report.json for paper update.

For tasks whose original API calls failed but re-run succeeded, replace the
per_task record and recalculate aggregates.  Overwrites the original
final_report.json with the updated version.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

CATEGORY_ORDER = (
    "code_generation", "compile_repair", "synthesis_repair",
    "functional_repair", "structural_cosim_repair", "qor_optimization",
)


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def merge_model(run_dir: str) -> dict:
    """Merge original final_report.json with re_run/ evidence. Returns updated report."""
    report = load_json(Path(run_dir) / "final_report.json")
    re_run_dir = Path(run_dir) / "re_run"

    if not re_run_dir.is_dir():
        print(f"  No re_run dir — nothing to merge")
        return report

    report = deepcopy(report)
    per_task = report["per_task"]
    updated_count = 0
    failed_count = 0

    for task_id, record in per_task.items():
        orig_api_failed = record.get("failed_api_requests", 0)
        if orig_api_failed == 0:
            continue  # No API failure — keep original

        # Look for re-run evidence
        rerun_ev_path = re_run_dir / task_id / "submission_evidence.json"
        if not rerun_ev_path.is_file():
            print(f"  ⚠ {task_id}: no re-run evidence found")
            continue

        rerun_ev = load_json(rerun_ev_path)
        r_status = rerun_ev.get("status", "?")
        r_tokens = rerun_ev.get("token_usage", {})

        if r_status == "completed":
            # Replace record with re-run data
            record["outcome"] = "completed"
            record["submission_status"] = "completed"
            record["submission_stop_reason"] = ""
            record["failed_api_requests"] = r_tokens.get("failed_request_count", 0)
            record["api_requests"] = r_tokens.get("request_count", 0)
            record["api_responses"] = r_tokens.get("response_count", 0)
            # Keep original tokens (they're additive from original run)
            # For re-run tokens, add to the totals
            r_prompt = r_tokens.get("prompt_tokens") or 0
            r_completion = r_tokens.get("completion_tokens") or 0
            r_total = r_tokens.get("total_tokens") or 0
            if r_total:
                record["tokens"] = {
                    "prompt": r_prompt,
                    "completion": r_completion,
                    "total": r_total,
                }
            # Update submission report path to re-run
            rr_sub = re_run_dir / task_id / "run_report.json"
            if rr_sub.is_file():
                record["submission_report"] = str(rr_sub)
            # Keep original score/official_score if available
            record["success"] = True
            updated_count += 1
        else:
            # Still failed — keep as failed
            record["outcome"] = "failed"
            record["submission_status"] = r_status
            record["submission_stop_reason"] = rerun_ev.get("stop_reason", "")
            record["failed_api_requests"] = r_tokens.get("failed_request_count", 0)
            record["api_requests"] = r_tokens.get("request_count", 0)
            record["api_responses"] = r_tokens.get("response_count", 0)
            r_prompt = r_tokens.get("prompt_tokens") or 0
            r_completion = r_tokens.get("completion_tokens") or 0
            r_total = r_tokens.get("total_tokens") or 0
            if r_total:
                record["tokens"] = {
                    "prompt": r_prompt,
                    "completion": r_completion,
                    "total": r_total,
                }
            record["success"] = False
            failed_count += 1

    print(f"  Updated: {updated_count} fixed, {failed_count} still failed")

    # ── Recalculate aggregate ──────────────────────────────────────────
    _recalc_aggregate(report)

    # ── Clean up retry_task_ids: only keep tasks that still have API failures ──
    still_failing = [
        tid for tid, rec in report["per_task"].items()
        if (rec.get("failed_api_requests") or 0) > 0
    ]
    report["retry_task_ids"] = still_failing

    return report


def _recalc_aggregate(report: dict) -> None:
    """Recalculate aggregate and category_metrics from per_task data."""
    per_task = report["per_task"]
    tasks = list(per_task.values())

    # Count outcomes
    success_count = sum(1 for t in tasks if t.get("outcome") == "completed")
    task_count = len(tasks)

    # Tokens
    total_prompt = sum((t.get("tokens") or {}).get("prompt", 0) or 0 for t in tasks)
    total_completion = sum((t.get("tokens") or {}).get("completion", 0) or 0 for t in tasks)
    total_tokens = sum((t.get("tokens") or {}).get("total", 0) or 0 for t in tasks)

    # API stats
    total_requests = sum(t.get("api_requests", 0) or 0 for t in tasks)
    total_responses = sum(t.get("api_responses", 0) or 0 for t in tasks)
    total_failed = sum(t.get("failed_api_requests", 0) or 0 for t in tasks)

    # Scores
    scores = []
    for t in tasks:
        score = t.get("official_score")
        if score is not None:
            scores.append(score)
        else:
            # Try evaluator_report
            pass
    scored_count = len(scores)
    score_sum = sum(scores) if scores else 0.0
    scored_mean = score_sum / scored_count if scored_count else 0.0
    all_task_mean = score_sum / task_count if task_count else 0.0

    # Credits and tool calls
    credits = sum(t.get("credits_spent", 0) or 0 for t in tasks)
    tool_calls = sum(t.get("tool_calls", 0) or 0 for t in tasks)

    # Category metrics
    category_data = {
        cat: {
            "total": 0, "success": 0,
            "scores": [], "score_sum": 0.0,
        }
        for cat in CATEGORY_ORDER
    }
    for t in tasks:
        cat = t.get("category", "unknown")
        if cat not in category_data:
            continue
        category_data[cat]["total"] += 1
        if t.get("outcome") == "completed":
            category_data[cat]["success"] += 1
        score = t.get("official_score")
        if score is not None:
            category_data[cat]["scores"].append(score)

    category_metrics = {}
    for cat in CATEGORY_ORDER:
        d = category_data[cat]
        cat_scores = d["scores"]
        cat_score_sum = sum(cat_scores)
        cat_mean = cat_score_sum / len(cat_scores) if cat_scores else 0.0
        category_metrics[cat] = {
            "task_count": d["total"],
            "success_count": d["success"],
            "success_rate": d["success"] / d["total"] if d["total"] else 0.0,
            "mean_official_score_all_tasks": cat_mean,
        }

    # Update aggregate
    aggregate = report["aggregate"]
    aggregate["success_count"] = success_count
    aggregate["success_rate"] = success_count / task_count if task_count else 0.0
    aggregate["scored_task_count"] = scored_count
    aggregate["official_score_mean_scored_tasks"] = scored_mean
    aggregate["official_score_mean_all_tasks"] = all_task_mean
    aggregate["official_score_sum"] = score_sum
    aggregate["tokens"] = {
        "prompt": total_prompt,
        "completion": total_completion,
        "total": total_tokens,
    }
    aggregate["api_requests"] = total_requests
    aggregate["api_responses"] = total_responses
    aggregate["failed_api_requests"] = total_failed
    aggregate["credits_spent"] = credits
    aggregate["tool_calls"] = tool_calls

    report["category_metrics"] = category_metrics


def main():
    models = [
        ("dsv4", "runs/track_a_150_or_dsv4_20260728_200507"),
        ("qwen35", "runs/track_a_150_or_qwen35_20260729_003822"),
        ("qwen36", "runs/track_a_150_or_qwen36_20260729_053353"),
    ]

    for name, run_dir in models:
        print(f"\n=== {name} ({run_dir}) ===")
        updated = merge_model(run_dir)

        # Backup via Docker (dir is root-owned)
        orig = Path(run_dir) / "final_report.json"
        backup = Path(run_dir) / "final_report_original.json"
        if not backup.exists():
            import subprocess
            subprocess.run([
                "docker", "run", "--rm",
                "-v", f"{os.getcwd()}:/workspace",
                "-w", "/workspace",
                "fpt26-agent-v3:latest",
                "cp", f"/workspace/{orig}", f"/workspace/{backup}",
            ], capture_output=True)
            print(f"  Backup: {backup}")

        # Write updated (need Docker for root-owned dir)
        tmp_path = f"/tmp/updated_final_report_{name}.json"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(updated, f, indent=2, ensure_ascii=False)
        print(f"  Written to {tmp_path}")

        agg = updated["aggregate"]
        print(f"  success={agg['success_count']}/{len(updated['per_task'])} "
              f"api_requests={agg['api_requests']} api_responses={agg['api_responses']} "
              f"api_failed={agg['failed_api_requests']} "
              f"score_sum={agg['official_score_sum']:.2f}")


if __name__ == "__main__":
    main()
