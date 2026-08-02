#!/usr/bin/env python3
"""Render the frozen qhw study as a self-contained Chinese Markdown report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def latency(report: dict[str, Any]) -> Any:
    return report.get("latency_worst") or report.get("latency_avg")


def metric(value: Any, digits: int = 3) -> str:
    if value is None:
        return "undef"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def short_id(task_id: str) -> str:
    return task_id.removeprefix("amd_intro__")


def rel_raw(task_id: str, side: str, kernel: str) -> str:
    return f"../../runs/qhw_reference_study_20260801/raw/{task_id}/{side}_synth/{kernel}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.analysis.read_text())
    scored = [task for task in data["tasks"] if task["scorable"]]
    excluded = [task for task in data["tasks"] if not task["scorable"]]
    clear = [
        task
        for task in scored
        if task["pareto_class"] in {"reference_dominates", "starter_dominates"}
    ]
    current_correct = sum(
        (
            task["current"]["standardized_score"] > 75.0
            if task["pareto_class"] == "reference_dominates"
            else task["current"]["standardized_score"] < 75.0
        )
        for task in clear
    )
    alternative_correct = sum(
        (
            task["alternative"]["standardized_score"] > 75.0
            if task["pareto_class"] == "reference_dominates"
            else task["alternative"]["standardized_score"] < 75.0
        )
        for task in clear
    )
    crossing = [
        task
        for task in scored
        if (task["current"]["standardized_score"] > 75.0)
        != (task["alternative"]["standardized_score"] > 75.0)
    ]

    lines = [
        "# qhw 评分可信度：公开 starter/reference Vitis 实证",
        "",
        "## 结论",
        "",
        (
            "在本次可评分的 24 个独立公开示例上，当前 `performance=0.55 / "
            "area=0.45` **能够反映综合后、硬件层级的 QoR 优劣，暂不建议改权重**。"
        ),
        "",
        (
            f"明确 Pareto 有方向的 {len(clear)} 项中，当前权重判断正确 "
            f"{current_correct}/{len(clear)}：4 个 reference 全维不劣且至少一维更优的任务"
            "均高于 starter 中性分 75；5 个 starter 反向支配 reference 的任务均低于 75。"
        ),
        "",
        (
            "唯一允许的替代试算为 `0.60 / 0.40`。它的明确 Pareto 方向正确率仍是 "
            f"{alternative_correct}/{len(clear)}，没有增加；均分从 "
            f"{data['summary']['current_score_mean']:.2f} 升至 "
            f"{data['summary']['alternative_score_mean']:.2f}，中位数仍为 75。"
        ),
        "",
        (
            "因此 `0.60 / 0.40` 只是更偏向性能的政策选择，不是本数据支持的更准确校准。"
            "它会减轻面积爆炸惩罚，例如 `pipelining_loops_using_free_running_pipeline` "
            "在最坏资源增长 9× 时由 56.96 升至 61.12。"
        ),
        "",
        "## 数据与可复现口径",
        "",
        "- 上游：[`Xilinx/Vitis-HLS-Introductory-Examples`](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples)，固定 commit `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`，Apache-2.0。仓库通过普通 `git clone` 下拉，没有使用 GitHub API。",
        "- 来源核验：对本地 task 声明的 source file set 重新计算 SHA-256，与刚下拉 commit 的内容逐项一致；完整结果见 [upstream_audit.json](results/upstream_audit.json)。",
        "- pair 构造：reference 是公开上游代码；starter 仅删除会影响调度、并行或存储映射的 HLS pragma，保留接口 pragma 与只影响报告的 `LOOP_TRIPCOUNT`。每个 task 的被删指令、源码哈希和实际两版源码都在证据中。",
        "- 工具：Vitis HLS 2025.2 build 6295257；目标 `xcu55c-fsvh2892-2L-e`；约束 5 ns。starter/reference 各跑一次 C-sim 与 C synthesis。",
        "- 样本：共采集 36 个不同 source path/source hash；29 个四阶段全通过；其中 24 个双方 latency 有限，作为正式评分样本。其余 12 个不被静默删除，见文末筛除表。",
        "- API：所有 evidence 均为 `api.request_count=0`；容器没有挂载 API env file，也没有模型 backend。",
        "- 分数：使用生产实现 `scoring/scoring_v3.py` 的 `P^0.55 × A^0.45` 和 `1-1/(1+r)^2`，以 starter 为 anchor；为隔离硬件质量，报告 `efficiency=1` 的标准化分数。当前 task 没有冻结 workload case，故 II 完整报告但没有再次并入分数。",
        "- 替代试算：严格只有一次，固定为 `P^0.60 × A^0.40`；生产评分文件未修改。",
        "",
        "## 24 个正式任务的来源与 pair 证明",
        "",
        "`S`/`R` 链接是实际送入 Vitis 的 starter/reference 源码；哈希列给出完整 source-set SHA-256。",
        "",
        "| # | Task | GitHub 固定来源 | 上游 source SHA-256 | 删除 pragma | 实际 pair | 证据 |",
        "|---:|---|---|---|---:|---|---|",
    ]
    for index, task in enumerate(scored, 1):
        kernel = task["removed_directives"][0].get("kernel_name", "")
        # kernel_name is stored beside, rather than inside, removed_directives.
        evidence = json.loads(
            (Path("runs/qhw_reference_study_20260801/raw") / task["task_id"] / "evidence.json").read_text()
        )
        kernel = evidence["pair"]["kernel_name"]
        source = f"[link]({task['source_url']})"
        pair = (
            f"[S]({rel_raw(task['task_id'], 'starter', kernel)}) / "
            f"[R]({rel_raw(task['task_id'], 'reference', kernel)})"
        )
        evidence_link = (
            f"[JSON](../../runs/qhw_reference_study_20260801/raw/"
            f"{task['task_id']}/evidence.json)"
        )
        lines.append(
            f"| T{index:02d} | `{short_id(task['task_id'])}` | {source} | "
            f"`{task['source_sha256']}` | {task['removed_directive_count']} | "
            f"{pair} | {evidence_link} |"
        )

    lines += [
        "",
        "## 全部正式任务的综合指标与分数",
        "",
        "`L/II/clk` 为 worst latency cycles / top interval / estimated clock ns；资源均为 starter→reference。`P` 已纳入 5 ns target 与 estimated clock；`A=1/max(resource growth)`。",
        "",
        "| # | S L/II/clk | R L/II/clk | LUT | FF | DSP | BRAM | URAM | P | A | 0.55/0.45 | 0.60/0.40 | Pareto |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for index, task in enumerate(scored, 1):
        starter = task["starter"]
        reference = task["reference"]
        sres = starter["resources"]
        rres = reference["resources"]
        components = task["qor_components"]
        lines.append(
            "| T%02d | %s/%s/%s | %s/%s/%s | %s→%s | %s→%s | %s→%s | %s→%s | %s→%s | %.3f | %.3f | %.2f | %.2f | `%s` |"
            % (
                index,
                metric(latency(starter)),
                metric(starter.get("interval_max")),
                metric(starter.get("clock_period_ns")),
                metric(latency(reference)),
                metric(reference.get("interval_max")),
                metric(reference.get("clock_period_ns")),
                sres["LUT"], rres["LUT"],
                sres["FF"], rres["FF"],
                sres["DSP"], rres["DSP"],
                sres["BRAM_18K"], rres["BRAM_18K"],
                sres["URAM"], rres["URAM"],
                components["performance_ratio"],
                components["area_ratio"],
                task["current"]["standardized_score"],
                task["alternative"]["standardized_score"],
                task["pareto_class"],
            )
        )

    lines += [
        "",
        "机器可读全字段（含 best/avg/worst latency、全部资源、两组分数）见 [task_metrics.csv](results/task_metrics.csv) 与 [analysis.json](results/analysis.json)。",
        "",
        "## 评分行为判断",
        "",
        "1. **能识别真实全维优化。** `array_partition_block_cyclic`、`dsp_fir_decimator`、`misc_rtl_as_blackbox`、`simple_fifos` 四项 reference 被 starter Pareto 支配关系反转后，当前分数都从中性 75 向上移动。",
        "2. **不会因源码含“优化 pragma”就盲目加分。** 例如 `static_array_ram` latency 1→12，当前仅 32.04；`directio_none_in_tasks` 新增大量 FF/LUT，当前 37.90。评分依据综合结果而非代码表面。",
        "3. **能表达性能/面积交换。** `array_stencil_2d` 的有效性能比 456×、最坏资源约 32×，仍得 97.98；`using_free_running_pipeline` 仅 1.87× 性能、最坏资源 9×，得 56.96。二者方向符合当前性能稍优先、面积仍受约束的设计。",
        "4. **主要不足不在 0.55/0.45。** 当前 `A` 使用最坏资源增长和统一 1-unit floor。`ram_uram` 把 57 BRAM 映射为 8 URAM，虽可能是器件资源重映射，却因 URAM 0→8 被当作 8× 瓶颈，得 48.41。仅调性能/面积指数无法辨别资源替换是否更适合目标器件。",
        "5. **II 语义仍需任务化。** 表中 top interval 有明显改善，但当前评分在没有冻结 workload case 时不使用 II；这避免重复计分，却不能完整评价持续流吞吐。",
        "",
        "## 唯一替代系数试算与建议",
        "",
        f"本次只计算了 `0.60/0.40` 一组替代值。高于 75 的 task 从 {data['summary']['current_above_neutral_count']} 增至 {data['summary']['alternative_above_neutral_count']}；唯一跨过 75 的是 `{short_id(crossing[0]['task_id']) if crossing else '无'}`。明确 Pareto 方向正确数不变。",
        "",
        "建议：**生产系数保持 0.55/0.45**。若竞赛政策明确要把“latency/throughput 优先于可部署面积”提升一个档位，0.60/0.40 是本次唯一有实测表格支持的备选；但它不是更准确，只是更偏性能，并会弱化 8–9× 资源增长的惩罚。",
        "",
        "若后续要实质提升可信度，优先级应是：先把 area 从“最坏原始计数增长”升级为容量归一化、能识别 BRAM↔URAM/DSP 替换的资源代价，再为流式 task 冻结 workload 以启用 II；不应先继续调两个指数。",
        "",
        "## 未进入 24 项评分集的 12 个候选",
        "",
        "这些 task 同样保留来源、两版源码与工具产物，但不能合法使用 starter anchor 计算当前 qhw。",
        "",
        "| Task | 原因 | starter C-sim | reference C-sim | starter synth | reference synth | 可用指标摘要 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for task in excluded:
        starter = task.get("starter") or {}
        reference = task.get("reference") or {}
        summary = (
            f"L {metric(latency(starter))}→{metric(latency(reference))}; "
            f"II {metric(starter.get('interval_max'))}→{metric(reference.get('interval_max'))}; "
            f"LUT {metric(starter.get('resources', {}).get('LUT'))}→"
            f"{metric(reference.get('resources', {}).get('LUT'))}"
        )
        lines.append(
            f"| `{short_id(task['task_id'])}` | `{task['unscorable_reason']}` | "
            f"{task['starter_csim_pass']} | {task['reference_csim_pass']} | "
            f"{task['starter_synth_pass']} | {task['reference_synth_pass']} | {summary} |"
        )

    lines += [
        "",
        "## 局限",
        "",
        "- 24 项有不同 source path/source hash，但都来自同一个 AMD/Xilinx 示例仓库，不能代表所有 HLS corpus。",
        "- starter 是可审计的 pragma ablation，不是上游作者单独发布并命名的 baseline；因此结论针对“代码级 pragma 优化能否在 qhw 中反映”，不等同于专家手工架构重写的全部情形。",
        "- 本报告使用 C-synthesis estimate；没有 place-and-route、功耗或板级吞吐。",
        "- 7 个 starter 无法综合、5 个双方 latency 为 `undef`，说明 benchmark 构造必须先做有效性门，不能只看是否存在两份源码。",
        "",
    ]
    args.output.write_text("\n".join(lines))
    print(f"wrote {args.output} with {len(scored)} scored and {len(excluded)} excluded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
