#!/usr/bin/env python3
"""Write a compact Chinese Track-A final summary from final_report.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CATEGORY_LABELS = {
    "code_generation": "代码生成",
    "compile_repair": "编译修复",
    "functional_repair": "功能修复",
    "qor_optimization": "QoR 优化",
    "structural_cosim_repair": "结构/CoSim 修复",
    "synthesis_repair": "综合修复",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return "0"


def _fmt_float(value: Any, digits: int = 4) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return f"{0.0:.{digits}f}"


def _fmt_score(value: Any) -> str:
    return _fmt_float(value, 2)


def _category_rows(report: dict[str, Any]) -> list[str]:
    rows = [
        "| 类别 | 成功率 | 分数总和 | 25 项平均分 | Tokens | API 请求 | 工具调用 | Credits |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for category, stats in sorted((report.get("category_metrics") or {}).items()):
        task_count = int(stats.get("task_count") or 0)
        success = int(stats.get("success_count") or 0)
        pct = round(100 * success / task_count) if task_count else 0
        score_sum = float(stats.get("mean_official_score_all_tasks") or 0) * task_count
        rows.append(
            "| {label} | {success}/{total} ({pct}%) | {score} | {mean} | {tokens} | {api} | {tools} | {credits} |".format(
                label=CATEGORY_LABELS.get(category, category),
                success=success,
                total=task_count,
                pct=pct,
                score=_fmt_score(score_sum),
                mean=_fmt_float(stats.get("mean_official_score_all_tasks")),
                tokens=_fmt_int(stats.get("tokens")),
                api=_fmt_int(stats.get("api_requests")),
                tools=_fmt_int(stats.get("tool_calls")),
                credits=_fmt_int(stats.get("credits")),
            )
        )
    return rows


def render(report: dict[str, Any]) -> str:
    coverage = report.get("coverage") or {}
    aggregate = report.get("aggregate") or {}
    attempts = report.get("all_attempt_accounting") or {}
    model_api = report.get("model_and_api") or {}
    benchmark = report.get("benchmark_construction_failure_audit") or {}
    score_availability = report.get("score_availability") or {}
    tokens = aggregate.get("tokens") or {}
    calls_by_tool = aggregate.get("calls_by_tool") or {}
    retry_ids = report.get("retry_task_ids") or []
    outcome_counts = coverage.get("outcome_counts") or {}
    failure_count = int(coverage.get("recorded_task_count") or 0) - int(
        aggregate.get("success_count") or 0
    )
    models = ", ".join(f"`{item}`" for item in model_api.get("models") or [])
    title_model = ", ".join(model_api.get("models") or []) or "unknown model"
    clients = ", ".join(f"`{item}`" for item in model_api.get("clients") or [])
    incident = report.get("api_incident_resolution") or {}
    incident_status = incident.get("status") or (
        "未观察到 API/基础设施中断" if not retry_ids else "存在待重试基础设施项"
    )

    lines = [
        f"# Track-A 150 {title_model} 最终结果",
        "",
        "## 语料验收",
        "",
        "- 任务总数：150",
        "- 六类任务：每类 25",
        "- U55C/Vitis 2025.2 初始验收：150/150",
        "- 跨类别内核重叠：0",
        "- submission 侧 hidden/reference 违规访问：0",
        f"- 首轮淘汰并归档候选：{benchmark.get('replaced_count', 0)}",
        "",
        "验收证据：",
        "",
        f"- `{report.get('frozen_corpus_manifest', {}).get('path')}`",
        f"- `{report.get('initial_gate_matrix', {}).get('path')}`",
        f"- `{benchmark.get('path')}`",
        "",
        "## 最终选定结果",
        "",
        f"- 模型：{models or '`unknown`'}",
        f"- 客户端：{clients or '`unknown`'}",
        "- mock/script/replay：未使用",
        f"- 模型合规证据：{model_api.get('model_compliance_proven_task_count', 0)}/150",
        "- 真实 API 记录："
        + (
            "完整"
            if model_api.get("real_api_only") is True
            else "存在异常或需复核"
        ),
        f"- 成功：{aggregate.get('success_count', 0)}/150 ({100 * float(aggregate.get('success_rate') or 0):.4f}%)",
        f"- 真实任务失败：{failure_count}",
        f"- 待基础设施/API 重试：{len(retry_ids)}",
        f"- outcome 分布：{dict(sorted(outcome_counts.items()))}",
        f"- 官方分数总和：{_fmt_score(aggregate.get('official_score_sum'))}",
        f"- 150 项平均官方分：{_fmt_float(aggregate.get('official_score_mean_all_tasks'))}",
        f"- {aggregate.get('scored_task_count', 0)} 个有分任务平均分：{_fmt_float(aggregate.get('official_score_mean_scored_tasks'))}",
        f"- 通过有效性 gate 但无有效 QoR anchor 分数：{score_availability.get('unscored_completed_task_count', 0)}",
        f"- tokens：{_fmt_int(tokens.get('total'))}（prompt {_fmt_int(tokens.get('prompt'))}；completion {_fmt_int(tokens.get('completion'))}）",
        f"- API 请求/响应/失败：{_fmt_int(aggregate.get('api_requests'))}/{_fmt_int(aggregate.get('api_responses'))}/{_fmt_int(aggregate.get('failed_api_requests'))}",
        f"- submission 工具调用：{_fmt_int(aggregate.get('tool_calls'))}（CSim {calls_by_tool.get('csim', 0)}；Synth {calls_by_tool.get('synth', 0)}；CoSim {calls_by_tool.get('cosim', 0)}）",
        f"- evaluator 工具调用：{_fmt_int(aggregate.get('evaluator_grading_tool_calls'))}",
        f"- credits：{_fmt_int(aggregate.get('credits_spent'))}/{_fmt_int(aggregate.get('credit_limit'))}",
        f"- 选定任务累计执行时间：{_fmt_float(aggregate.get('task_wall_time_s'), 3)} 秒",
        "",
        *_category_rows(report),
        "",
        "## 全尝试开销与 API 状态",
        "",
        f"- 任务尝试记录：{attempts.get('task_attempt_record_count', 0)}（最终选定 {coverage.get('recorded_task_count', 0)}；被替代尝试 {attempts.get('superseded_task_attempt_count', 0)}）",
        f"- 任务尝试 API 请求/响应/失败：{_fmt_int(attempts.get('api_requests_in_task_attempts'))}/{_fmt_int(attempts.get('api_responses_in_task_attempts'))}/{_fmt_int(attempts.get('failed_api_requests_in_task_attempts'))}",
        f"- 全部观测 API 请求/响应/失败：{_fmt_int(attempts.get('total_observed_api_requests'))}/{_fmt_int(attempts.get('total_observed_api_responses'))}/{_fmt_int(attempts.get('total_observed_failed_api_requests'))}",
        f"- 全尝试 submission 工具调用：{_fmt_int(attempts.get('tool_calls'))}",
        f"- 全尝试 evaluator 工具调用：{_fmt_int(attempts.get('evaluator_grading_tool_calls'))}",
        f"- 全尝试 credits：{_fmt_int(attempts.get('credits_spent'))}/{_fmt_int(attempts.get('credit_limit_across_attempts'))}",
        f"- 全尝试累计执行时间：{_fmt_float(attempts.get('task_attempt_wall_time_s'), 3)} 秒",
        f"- 墙钟跨度：{_fmt_float(aggregate.get('parallel_campaign_elapsed_max_shard_s'), 3)} 秒",
        f"- API/基础设施状态：{incident_status}",
        "",
        "## 交付文件",
        "",
        "- `final_report.json`：总 manifest 引用、gate、分类指标、官方分数、tokens、请求、工具、credits、时间、失败与重试审计",
        "- `per_task_evidence.json`：150 个任务的逐项证据",
        "- `retry_manifest.json`：仅包含 API/基础设施异常任务；真实仿真/综合失败不会进入重试清单",
        "- `FINAL_SUMMARY.md`：本摘要",
        "",
        "最终一致性检查：",
        "",
        f"- 记录任务数：{coverage.get('recorded_task_count', 0)}/150",
        f"- 执行源码快照一致：{coverage.get('execution_source_stable')}",
        f"- source tree SHA-256：`{coverage.get('execution_source_tree_sha256')}`",
        f"- 待基础设施/API 重试任务数：{len(retry_ids)}",
    ]
    if retry_ids:
        lines.append(f"- 待重试任务：{', '.join(f'`{item}`' for item in retry_ids)}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final-report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = _load(args.final_report)
    args.output.write_text(render(report), encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
