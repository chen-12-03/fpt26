# =============================================================================
# FPT26 Track-A Agent v3 — 命令行参数解析 (CLI Argument Parsing)
# =============================================================================
# 【功能概述】
#   本文件定义了 Agent 系统的所有命令行参数。
#   使用 Python 标准库 argparse 实现，不依赖任何第三方库。
#
# 【这是你应该看的第 1 个文件】
#   通过理解命令行参数，你可以快速建立对整个系统功能的全局认知。
#   每个参数对应系统的一项能力或一种运行模式。
#
# 【参数速查表】
#   --task             任务目录路径（必填）
#   --mode             运行模式：auto|baseline|repair|optimize|structural|full
#   --run-role         运行角色：submission（提交者）|evaluator（评分者）
#   --backend          LLM 后端：auto|openrouter|custom|scripted
#   --scoring-profile  评分策略：balanced|extreme_speed|extreme_speed_capped
#   --budget           覆盖任务的 credits 预算上限
#   --competition      启用竞争模式（多条独立策略并行评估）
#   --max-repair-attempts      最大修复尝试次数（默认 3）
#   --max-optimization-rounds  最大优化轮次（默认 5）
#   --max-structural-attempts  最大结构修复尝试次数（默认 3）
#   --final-kernel     待评分的内核文件路径（Evaluator 角色必填）
#   --submission-evidence  Submission 证据文件路径（Evaluator 角色必填）
#   --output-root      输出根目录
#   --quiet            静默模式
#   --no-score         跳过隐藏测试平台评分
# =============================================================================

from __future__ import annotations

import argparse
from pathlib import Path

from scoring.profiles import DEFAULT_SCORING_PROFILE, SCORING_PROFILE_CHOICES


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    解析命令行参数。

    这是稳定的公开 API —— 不要重命名已有的参数标志。

    参数:
        argv: 命令行参数列表，None 表示使用 sys.argv

    返回:
        解析后的 argparse.Namespace 对象
    """
    p = argparse.ArgumentParser(
        description="FPT26 Track-A agent v3 — pipeline-based LLM4HLS agent with V3 scoring"
    )

    # ---- 必填参数 ----
    p.add_argument("--task", required=True, type=Path,
                   help="Path to official task directory")

    # ---- 运行模式 ----
    # mode 决定激活哪些流水线阶段：
    #   auto:       自动根据任务类型选择最合适的模式
    #   baseline:   只运行基线 CSim（不调用 LLM）
    #   repair:     只运行修复循环
    #   optimize:   只运行优化循环（需要代码已通过所有门控）
    #   structural: 只运行结构修复（针对 CoSim 死锁问题）
    #   full:       运行全部阶段（修复 + 优化 + 结构修复）
    p.add_argument("--mode",
                   choices=["auto", "baseline", "repair", "optimize", "structural", "full"],
                   default="auto",
                   help="Agent operating mode")

    # ---- 运行角色 ----
    # submission: 竞赛中的"参赛者"角色 —— 生成优化后的内核代码
    # evaluator:  竞赛中的"裁判"角色 —— 用隐藏测试平台评分
    p.add_argument("--run-role",
                   choices=["submission", "evaluator"], default="submission",
                   help="Submission or evaluator role")

    # ---- Evaluator 专有参数 ----
    p.add_argument("--final-kernel", type=Path, default=None,
                   help="Final kernel artifact to grade (required for evaluator)")

    # ---- 输出控制 ----
    p.add_argument("--output-root", type=Path, default=None,
                   help="Run artifact output root")

    # ---- 预算控制 ----
    # Budget 是云端 credits 的概念，每次工具调用消耗固定数量的 credits
    p.add_argument("--budget", type=int, default=None,
                   help="Override task credit budget")

    # ---- LLM 后端选择 ----
    # auto:       自动检测（优先使用 FPT26_LLM_API_KEY 环境变量）
    # openrouter: 使用 OpenRouter API
    # custom:     使用自定义 OpenAI 兼容 API
    # scripted:   离线回放模式（不调用真实 API，用于测试）
    p.add_argument("--backend",
                   choices=["auto", "openrouter", "custom", "scripted"],
                   default="auto",
                   help="LLM backend selection")

    # ---- 竞争模式 ----
    # 启用后，会并行运行多条独立的优化策略通道，
    # 最后选择 Q_HW 最高的候选代码
    p.add_argument("--competition", action="store_true",
                   help="Evaluate independent optimization strategy lanes")

    # ---- Agent 行为参数 ----
    # 这些参数控制了 LLM Agent 的循环次数上限
    p.add_argument("--max-repair-attempts", type=int, default=None)
    p.add_argument("--max-optimization-rounds", type=int, default=None)
    p.add_argument("--max-structural-attempts", type=int, default=None)

    # ---- 评分配置 ----
    # balanced (0.55/0.45):              均衡模式 —— 性能和面积同等重要
    # extreme_speed (0.70/0.30):          极限速度模式 —— 优先性能
    # extreme_speed_capped (0.70/0.30):   极限速度上限模式 —— 优先性能但不奖励面积增长
    p.add_argument("--no-score", action="store_true",
                   help="Skip hidden-testbench scoring")
    p.add_argument("--submission-evidence", type=Path, default=None,
                   help="Path to submission_evidence.json for evaluator verification")
    p.add_argument("--scoring-profile",
                   choices=SCORING_PROFILE_CHOICES,
                   default=DEFAULT_SCORING_PROFILE,
                   help="Hardware trade-off profile: balanced, extreme_speed, extreme_speed_capped")

    # ---- 日志控制 ----
    p.add_argument("--quiet", action="store_true",
                   help="Suppress step-by-step log output")

    return p.parse_args(argv)
