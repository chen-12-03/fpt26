# =============================================================================
# FPT26 Track-A Agent v3 — 评分策略配置 (Scoring Profiles)
# =============================================================================
# 【功能概述】
#   本文件定义了三种硬件取舍策略（Hardware Trade-off Profiles）。
#   每种策略通过不同的性能权重（performance_weight）和面积权重（area_weight）
#   来影响最终的 Q_HW（硬件质量）得分。
#
# 【这是你应该看的第 13 个文件】
#
# 【评分公式】
#   硬件比值 = performance_ratio^W_P × area_ratio^W_A
#   其中 W_P + W_A = 1.0（权重必须归一化）
#
#   最终得分 = Q_HW(硬件比值) × Efficiency(效率因子)
#   Efficiency = f(credits消耗, 时间消耗, 预算上限, 时间上限)
#
# 【三种策略对比】
#   ┌──────────────────────┬────────┬────────┬────────────────────┐
#   │ 策略                 │ 性能权重│ 面积权重│ 面积奖励上限      │
#   ├──────────────────────┼────────┼────────┼────────────────────┤
#   │ balanced             │ 0.55   │ 0.45   │ 无上限             │
#   │ extreme_speed        │ 0.70   │ 0.30   │ 无上限             │
#   │ extreme_speed_capped │ 0.70   │ 0.30   │ 1.0 (不奖励面积增长)│
#   └──────────────────────┴────────┴────────┴────────────────────┘
#
#   balanced (默认):
#     适合通用场景。性能和面积同等重要。
#     面积增长和面积减少被平等对待。
#
#   extreme_speed:
#     适合极限性能场景。性能权重 70%，面积仅占 30%。
#     即使用面积换性能也是值得的。
#
#   extreme_speed_capped:
#     适合对面积有硬性限制的场景。与 extreme_speed 相同权重，
#     但当面积比 > 1.0（面积增长）时，会被限制为 1.0（不奖励）。
#     也就是说：可以减少面积获得奖励，但面积增长不受惩罚。
# =============================================================================

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from scoring.scoring_v3 import (
    Anchor,
    QoREvidence,
    TaskScoringConfig,
    ValidityGates,
    calculate_qor_components,
    combine_score,
    efficiency_factor,
    grade as grade_balanced,       # schema-10 的原始评分函数
    hardware_ratio,
    ratio_quality,
)

# 评分配置文件的 schema 版本号
PROFILE_SCHEMA_VERSION = 11

# 默认评分策略
DEFAULT_SCORING_PROFILE = "balanced"


@dataclass(frozen=True)
class ScoringProfile:
    """
    声明的、运行全局的硬件取舍策略。

    字段:
        name:                 策略名称（balanced/extreme_speed/extreme_speed_capped）
        performance_weight:   性能权重（0~1）
        area_weight:          面积权重（0~1）
        cap_area_reward:      是否限制面积奖励（True 时 area_ratio 上限为 1.0）

    约束:
        performance_weight + area_weight = 1.0
    """
    name: str
    performance_weight: float
    area_weight: float
    cap_area_reward: bool = False

    def __post_init__(self) -> None:
        """验证权重之和 = 1.0（使用严格浮点比较）。"""
        if not math.isclose(
            self.performance_weight + self.area_weight, 1.0,
            rel_tol=0.0, abs_tol=1e-12,
        ):
            raise ValueError("scoring profile weights must sum to one")


# 已注册的评分策略字典
SCORING_PROFILES: dict[str, ScoringProfile] = {
    "balanced": ScoringProfile(
        name="balanced",
        performance_weight=0.55,
        area_weight=0.45,
        cap_area_reward=False,
    ),
    "extreme_speed": ScoringProfile(
        name="extreme_speed",
        performance_weight=0.70,
        area_weight=0.30,
        cap_area_reward=False,
    ),
    "extreme_speed_capped": ScoringProfile(
        name="extreme_speed_capped",
        performance_weight=0.70,
        area_weight=0.30,
        cap_area_reward=True,
    ),
}

# 所有可选策略名称的元组（供 CLI 使用）
SCORING_PROFILE_CHOICES = tuple(SCORING_PROFILES)


def resolve_scoring_profile(name: str) -> ScoringProfile:
    """
    根据名称解析评分策略。失败时抛出 ValueError。

    参数:
        name: 策略名称

    返回:
        ScoringProfile 对象

    异常:
        ValueError: 未知的策略名称
    """
    try:
        return SCORING_PROFILES[name]
    except KeyError as exc:
        choices = ", ".join(SCORING_PROFILE_CHOICES)
        raise ValueError(
            f"unknown scoring profile {name!r}; expected one of: {choices}"
        ) from exc


def grade_with_profile(
    task_cfg: TaskScoringConfig,
    anchor: Anchor,
    evidence: QoREvidence,
    *,
    scoring_profile: str = DEFAULT_SCORING_PROFILE,
    cost_spent: int = 0,
    wall_time_s: float = 0.0,
    gates: ValidityGates | None = None,
    ii_applicable: bool = False,
    accounting: Any = None,  # EvaluationAccounting | None
) -> Any:
    """
    使用指定的评分策略对候选设计进行评分。

    流程:
    1. 通过 schema-10 的原始评分函数计算基础 Scorecard
       （这个函数负责所有门控和效率检查）
    2. 如果是 balanced 策略 → 直接返回 schema-10 结果（性能最优）
    3. 如果是 extreme_speed 策略 → 重新计算硬件比值
       使用自定义的性能/面积权重

    参数:
        task_cfg:        任务评分配置
        anchor:           评分锚点（starter 或 reference）
        evidence:         候选设计的 QoR 证据
        scoring_profile:  策略名称
        cost_spent:       已消耗的 credits（向后兼容）
        wall_time_s:      已消耗的时间（向后兼容）
        gates:            有效性门控
        ii_applicable:    是否适用 II 评分
        accounting:       EvaluationAccounting 对象（正式评估时提供）

    返回:
        Scorecard 对象（包含 valid, score, q_hw, efficiency 等字段）
    """
    from agent.models import EvaluationAccounting

    # 如果提供了 accounting 对象，从中提取成本和时间
    # （这是正式评估的首选路径）
    if accounting is not None:
        if not isinstance(accounting, EvaluationAccounting):
            raise TypeError(
                f"accounting must be EvaluationAccounting, got {type(accounting).__name__}"
            )
        cost_spent = accounting.total_credits
        wall_time_s = accounting.total_wall_seconds

    profile = resolve_scoring_profile(scoring_profile)

    # ---- 步骤 1: 通过 schema-10 原始评分函数 ----
    # 这个函数处理所有门控检查、效率计算等
    card = grade_balanced(
        task_cfg=task_cfg, anchor=anchor, evidence=evidence,
        cost_spent=cost_spent, wall_time_s=wall_time_s,
        gates=gates, ii_applicable=ii_applicable,
    )

    # 将策略信息写入 Scorecard（使策略可审计）
    card.schema_version = PROFILE_SCHEMA_VERSION
    card.scoring_profile = profile.name
    card.performance_weight = profile.performance_weight
    card.area_weight = profile.area_weight
    card.area_reward_capped = profile.cap_area_reward
    card.effective_area_ratio = card.area_ratio

    # 如果 Scorecard 无效，直接返回（不重新计算）
    if not card.valid:
        return card

    # 如果是 balanced 策略，保留 schema-10 的精确结果
    if profile.name == DEFAULT_SCORING_PROFILE:
        return card

    # ---- 步骤 2: 重新计算硬件比值（使用自定义权重）----
    components = calculate_qor_components(
        task_cfg, anchor, evidence, ii_applicable=ii_applicable,
    )

    # 面积比值处理
    effective_area_ratio = components.area_ratio
    if profile.cap_area_reward:
        # 限制面积奖励：面积增长不奖励，面积减少仍奖励
        effective_area_ratio = min(effective_area_ratio, 1.0)

    # 计算硬件比值: performance_ratio^W_P × area_ratio^W_A
    composite = hardware_ratio(
        components.performance_ratio,
        effective_area_ratio,
        performance_weight=profile.performance_weight,
    )

    # 通过质量映射函数将硬件比值转换为 Q_HW
    q_hw = ratio_quality(composite)

    # 更新 Scorecard 字段
    card.effective_area_ratio = round(effective_area_ratio, 4)
    card.hardware_ratio = round(composite, 4)
    card.q_hw = round(q_hw, 4)

    # 计算效率因子（cost 和时间的影响）
    exact_efficiency = efficiency_factor(
        cost_spent, task_cfg.budget_limit,
        wall_time_s, task_cfg.time_limit_s,
    )

    # 最终得分 = Q_HW × Efficiency
    card.score = round(combine_score(True, q_hw, exact_efficiency), 2)
    return card
