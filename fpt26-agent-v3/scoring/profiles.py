"""Explicit scoring profiles layered on the frozen schema-10 kernel.

The balanced profile is numerically identical to schema 10.  Experimental
speed profiles change only the performance/area aggregation; validity gates,
raw PPA evidence, efficiency, and the ratio-quality mapping remain shared.
"""

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
    grade as grade_balanced,
    hardware_ratio,
    ratio_quality,
)


PROFILE_SCHEMA_VERSION = 11
DEFAULT_SCORING_PROFILE = "balanced"


@dataclass(frozen=True)
class ScoringProfile:
    """A declared, run-wide hardware trade-off policy."""

    name: str
    performance_weight: float
    area_weight: float
    cap_area_reward: bool = False

    def __post_init__(self) -> None:
        if not math.isclose(
            self.performance_weight + self.area_weight,
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("scoring profile weights must sum to one")


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
SCORING_PROFILE_CHOICES = tuple(SCORING_PROFILES)


def resolve_scoring_profile(name: str) -> ScoringProfile:
    """Resolve a public profile name or fail closed."""
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
) -> Any:
    """Grade through schema 10, then apply the declared profile aggregation.

    The authoritative schema-10 grader owns all gates and efficiency.  Only a
    valid card reaches the profile calculation, preventing a profile from
    bypassing correctness, synthesis, cosim, metric, or capacity failures.
    """
    profile = resolve_scoring_profile(scoring_profile)
    card = grade_balanced(
        task_cfg=task_cfg,
        anchor=anchor,
        evidence=evidence,
        cost_spent=cost_spent,
        wall_time_s=wall_time_s,
        gates=gates,
        ii_applicable=ii_applicable,
    )

    # These fields make the selected policy auditable even on an invalid run.
    card.schema_version = PROFILE_SCHEMA_VERSION
    card.scoring_profile = profile.name
    card.performance_weight = profile.performance_weight
    card.area_weight = profile.area_weight
    card.area_reward_capped = profile.cap_area_reward
    card.effective_area_ratio = card.area_ratio

    if not card.valid:
        return card
    if profile.name == DEFAULT_SCORING_PROFILE:
        # Preserve schema-10 production arithmetic exactly, including its use
        # of unrounded efficiency when producing the final score.
        return card

    components = calculate_qor_components(
        task_cfg,
        anchor,
        evidence,
        ii_applicable=ii_applicable,
    )
    effective_area_ratio = components.area_ratio
    if profile.cap_area_reward:
        effective_area_ratio = min(effective_area_ratio, 1.0)

    composite = hardware_ratio(
        components.performance_ratio,
        effective_area_ratio,
        performance_weight=profile.performance_weight,
    )
    q_hw = ratio_quality(composite)

    card.effective_area_ratio = round(effective_area_ratio, 4)
    card.hardware_ratio = round(composite, 4)
    card.q_hw = round(q_hw, 4)
    exact_efficiency = efficiency_factor(
        cost_spent,
        task_cfg.budget_limit,
        wall_time_s,
        task_cfg.time_limit_s,
    )
    card.score = round(combine_score(True, q_hw, exact_efficiency), 2)
    return card
