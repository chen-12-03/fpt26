"""FPT26 LLM4HLS Unified Scoring Engine.

All tasks follow a single objective: **valid_then_optimize**.

1. Pass validity gates (hidden functional, synthesis, required cosim, capacity).
2. Score performance and resource quality against a frozen anchor.
3. Apply bounded efficiency deduction from cost and wall time.

No task-type-specific formulas.  No preserve/improve policy switching.
``repair``, ``optimize``, ``structural`` etc. are diagnostic labels only.

Core formula (fits on one screen)::

    def ratio_quality(r):   return 1 - 1/(1+r)**2
    def latency_quality():  return ratio_quality(anchor_time / candidate_time)
    def area_quality():     return ratio_quality(1 / max(growth_by_resource))
    def q_hw():             return sqrt(q_perf * q_area)
    def efficiency():       return max(0.80, 1 - 0.10*ucost - 0.10*utime)
    def score():            return 100 * validity * q_hw * efficiency
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════════════════════════════════
# Global constants
# ═══════════════════════════════════════════════════════════════════════════════

RESOURCES = ("LUT", "FF", "DSP", "BRAM_18K", "URAM")
W_LATENCY = 0.85
W_II = 0.15
LAMBDA_COST = 0.10
LAMBDA_TIME = 0.10
E_MIN = 0.80


# ═══════════════════════════════════════════════════════════════════════════════
# Unified ratio → quality function
# ═══════════════════════════════════════════════════════════════════════════════

def ratio_quality(r: float) -> float:
    """Map a "bigger is better" ratio to [0, 1) via 1 - 1/(1+r)².

    Intuitive landmarks:
        0x   → 0.00     (zero performance)
        0.5x → 0.56     (halved)
        1x   → 0.75     (matched baseline — already decent)
        2x   → 0.89     (doubled)
        4x   → 0.96     (quadrupled)
        ∞    → 1.00     (asymptotic)

    Properties: strictly monotonic, no hard cap at any finite r,
    no per-task anchor parameters needed.
    """
    if r <= 0:
        return 0.0
    return 1.0 - 1.0 / (1.0 + r) ** 2


# ═══════════════════════════════════════════════════════════════════════════════
# Anchor selection (§Anchor)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Anchor:
    """Frozen baseline for QoR comparison."""

    source: str           # "starter" | "reference" | "none"
    valid: bool           # the anchor itself passes gates
    latency: int | None
    ii: int | None
    clock_ns: float | None
    resources: dict[str, int] = field(default_factory=dict)
    available: dict[str, int] = field(default_factory=dict)
    hash: str = ""        # content hash for audit


def select_anchor(
    starter_latency: int | None,
    starter_ii: int | None,
    starter_clock_ns: float | None,
    starter_resources: dict[str, int],
    starter_valid: bool,
    reference_latency: int | None = None,
    reference_ii: int | None = None,
    reference_clock_ns: float | None = None,
    reference_resources: dict[str, int] | None = None,
    reference_hash: str = "",
    available_resources: dict[str, int] | None = None,
) -> Anchor:
    """Choose the anchor for QoR comparison.

    Priority:
        1. Starter is functionally correct and synthesizable → use starter
        2. Starter is invalid → use evaluator-side frozen reference
        3. No valid anchor → reject (cannot score)
    """
    if starter_valid and starter_latency is not None:
        return Anchor(
            source="starter", valid=True,
            latency=starter_latency, ii=starter_ii,
            clock_ns=starter_clock_ns,
            resources=dict(starter_resources),
            available=dict(available_resources or {}),
            hash="starter",  # placeholder — real impl should hash starter code
        )

    if reference_latency is not None:
        return Anchor(
            source="reference", valid=True,
            latency=reference_latency, ii=reference_ii,
            clock_ns=reference_clock_ns,
            resources=dict(reference_resources or {}),
            available=dict(available_resources or {}),
            hash=reference_hash,
        )

    return Anchor(source="none", valid=False, latency=None, ii=None,
                  clock_ns=None)


# ═══════════════════════════════════════════════════════════════════════════════
# Performance quality
# ═══════════════════════════════════════════════════════════════════════════════

def performance_quality(
    latency_ratio: float,
    ii_ratio: float = 1.0,
    ii_applicable: bool = False,
) -> float:
    """Performance quality from latency and optional II ratios.

    All tasks use the same formula.  No preserve/improve distinction.
    Regression (ratio < 1) naturally lowers quality; improvement raises it.
    """
    q_lat = ratio_quality(latency_ratio)

    if ii_applicable and ii_ratio > 0:
        q_ii = ratio_quality(ii_ratio)
        return W_LATENCY * q_lat + (1.0 - W_LATENCY) * q_ii
    return q_lat


# ═══════════════════════════════════════════════════════════════════════════════
# Resource quality
# ═══════════════════════════════════════════════════════════════════════════════

def _resource_floor(available: dict[str, int]) -> dict[str, float]:
    """Tiny floor to handle zero-baseline without epsilon=1 distortion."""
    return {r: min(1.0, max(0.0001 * available.get(r, 1), 0.01))
            for r in RESOURCES}


def resource_growth_by_type(
    candidate: dict[str, int],
    anchor: dict[str, int],
    available: dict[str, int],
) -> tuple[dict[str, float], list[str]]:
    """Per-resource growth with capacity-aware floor.

    Returns (growth_by_resource, significant_resources).
    Significant = baseline or candidate exceeds floor.
    """
    floor = _resource_floor(available)
    growth = {}
    significant = []
    for r in RESOURCES:
        c = max(candidate.get(r, 0), floor[r])
        a = max(anchor.get(r, 0), floor[r])
        growth[r] = c / a
        if anchor.get(r, 0) > floor[r] or candidate.get(r, 0) > floor[r]:
            significant.append(r)
    return growth, significant


def area_quality(
    candidate_resources: dict[str, int],
    anchor_resources: dict[str, int],
    available_resources: dict[str, int],
) -> tuple[float, dict[str, float], str]:
    """Area quality from worst-resource bottleneck.

    area_growth = max(growth_r) among significant resources
    area_ratio  = 1 / area_growth
    q_area      = ratio_quality(area_ratio)
    """
    growth, significant = resource_growth_by_type(
        candidate_resources, anchor_resources, available_resources)
    candidates = significant if significant else list(RESOURCES)
    bottleneck = max(candidates, key=lambda r: growth[r])
    area_growth = growth[bottleneck]
    area_ratio = 1.0 / max(area_growth, 1e-9)
    q = ratio_quality(area_ratio)
    return q, growth, bottleneck


# ═══════════════════════════════════════════════════════════════════════════════
# Capacity gate
# ═══════════════════════════════════════════════════════════════════════════════

def check_capacity(
    candidate: dict[str, int],
    available: dict[str, int],
) -> bool:
    """Hard gate: any resource > available → False."""
    for r in RESOURCES:
        c = candidate.get(r, 0)
        a = available.get(r, 0)
        if a > 0 and c > a:
            return False
        if a == 0 and c > 0:
            return False
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# QoR & Efficiency
# ═══════════════════════════════════════════════════════════════════════════════

def hardware_qor(q_perf: float, q_area: float) -> float:
    """Geometric mean: sqrt(q_perf * q_area)."""
    return math.sqrt(max(q_perf, 0.0) * max(q_area, 0.0))


def efficiency_factor(
    cost_spent: float,
    cost_limit: float,
    wall_time_s: float = 0.0,
    time_limit_s: float = 3600.0,
) -> float:
    """Bounded deduction: max 20%."""
    if cost_limit <= 0:
        cost_limit = 1.0
    if time_limit_s <= 0:
        time_limit_s = 3600.0
    u_cost = max(0.0, min(1.0, cost_spent / cost_limit))
    u_time = max(0.0, min(1.0, wall_time_s / time_limit_s))
    return max(E_MIN, 1.0 - LAMBDA_COST * u_cost - LAMBDA_TIME * u_time)


def combine_score(valid: bool, q_hw: float, efficiency: float) -> float:
    """Score = 100 * validity * Q_HW * efficiency.  [0, 100]."""
    return 0.0 if not valid else 100.0 * q_hw * efficiency


# ═══════════════════════════════════════════════════════════════════════════════
# Data containers
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ValidityGates:
    """Hard validity gates.  Any required gate fail → Score = 0."""

    infrastructure_error: bool = False
    infrastructure_reason: str = ""

    hidden_csim_pass: bool = False
    hidden_cosim_pass: bool | None = None
    synth_pass: bool = False
    implementation_pass: bool | None = None
    resource_capacity_pass: bool = True
    interface_pass: bool = True
    metric_completeness_pass: bool = True
    timeout_pass: bool = True

    @property
    def all_required_pass(self) -> bool:
        if self.infrastructure_error:
            return False
        if not self.hidden_csim_pass:
            return False
        if self.hidden_cosim_pass is False:
            return False
        if not self.synth_pass:
            return False
        if self.implementation_pass is False:
            return False
        if not self.resource_capacity_pass:
            return False
        if not self.interface_pass:
            return False
        if not self.metric_completeness_pass:
            return False
        if not self.timeout_pass:
            return False
        return True

    @property
    def first_failure(self) -> str:
        checks = [
            ("infrastructure_error", "infrastructure_error"),
            ("hidden_csim_pass", "hidden_csim_fail"),
            ("hidden_cosim_pass", "hidden_cosim_fail"),
            ("synth_pass", "synth_fail"),
            ("implementation_pass", "implementation_fail"),
            ("resource_capacity_pass", "resource_capacity_exceeded"),
            ("interface_pass", "interface_violation"),
            ("metric_completeness_pass", "required_metric_missing"),
            ("timeout_pass", "timeout"),
        ]
        for attr, label in checks:
            if getattr(self, attr) is False:
                return label
        return "passed"


@dataclass
class QoREvidence:
    """Hardware QoR evidence from tool runs."""

    candidate_latency: int | None = None
    candidate_ii: int | None = None
    candidate_clock_ns: float | None = None

    cosim_latency: int | None = None

    candidate_resources: dict[str, int] = field(default_factory=dict)

    infrastructure_error: bool = False
    infrastructure_reason: str = ""

    @property
    def required_metrics_complete(self) -> bool:
        if self.candidate_latency is None:
            return False
        return "LUT" in self.candidate_resources


@dataclass
class TaskScoringConfig:
    """Minimal per-task config.  task_type is a diagnostic label only."""

    task_id: str = ""
    task_type: str = ""             # label only — no effect on scoring
    difficulty: int = 1             # leaderboard aggregation only
    requires_cosim: bool = False    # validation gate, not scoring policy
    budget_limit: int = 40
    time_limit_s: float = 3600.0
    task_clock_ns: float = 5.0


# ═══════════════════════════════════════════════════════════════════════════════
# Scorecard
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Scorecard:
    """Unified scorecard with all intermediate values for audit."""

    schema_version: int = 5
    task_id: str = ""
    task_type: str = ""             # label only
    difficulty: int = 1

    # Anchor
    anchor_source: str = "none"
    anchor_hash: str = ""
    anchor_valid: bool = False

    # Validity
    valid: bool = False
    gate_reason: str = ""
    csim_pass: bool = False
    synth_pass: bool = False
    cosim_pass: bool | None = None
    stage: str = "unknown"

    # Performance
    latency_ratio: float = 1.0
    ii_ratio: float = 1.0
    utility_name: str = "1-1/(1+r)²"
    q_perf: float = 0.0

    # Resources
    baseline_resources: dict[str, int] = field(default_factory=dict)
    candidate_resources: dict[str, int] = field(default_factory=dict)
    growth_by_resource: dict[str, float] = field(default_factory=dict)
    bottleneck_resource: str = ""
    area_growth: float = 1.0
    q_area: float = 0.0

    # Efficiency
    cost_spent: float = 0
    cost_limit: float = 0
    wall_time_s: float = 0.0
    time_limit_s: float = 0.0
    efficiency: float = 1.0

    # Final
    q_hw: float = 0.0
    score: float = 0.0
    score_max: float = 100.0
    acceleration_source: str = "synth"
    cosim_latency_used: int | None = None

    def render(self) -> str:
        v = "PASS" if self.valid else "FAIL"
        cs = "PASS" if self.csim_pass else "FAIL"
        sy = "PASS" if self.synth_pass else "FAIL"
        co = "PASS" if self.cosim_pass else ("FAIL" if self.cosim_pass is False else "N/A")

        lines = [
            f"╔══ Scorecard V5: {self.task_id} (label={self.task_type}, d={self.difficulty}) ══╗",
            f"║  VALID: {v:<8}  gate={self.gate_reason:<32}  stage={self.stage:<10} ║",
            f"║  anchor: {self.anchor_source:<10}  valid={str(self.anchor_valid):<5}  hash={self.anchor_hash:<20} ║",
            f"║  csim={cs:<5}  synth={sy:<5}  cosim={co:<5}                                  ║",
            f"╠{'─'*75}╣",
        ]
        if self.valid:
            lines += [
                f"║  latency_ratio: {self.latency_ratio:>8.2f}x   ii_ratio: {self.ii_ratio:>8.2f}x                    ║",
                f"║  q_perf:        {self.q_perf:>8.4f}   ({self.utility_name})                         ║",
                f"║  area_growth:   {self.area_growth:>8.2f}x   bottleneck: {self.bottleneck_resource:<10}  q_area: {self.q_area:.4f}   ║",
                f"║  efficiency:    {self.efficiency:>8.4f}   (cost {self.cost_spent}/{self.cost_limit}, time {self.wall_time_s:.0f}s/{self.time_limit_s:.0f}s)   ║",
                f"╠{'─'*75}╣",
                f"║  Q_HW:          {self.q_hw:>8.4f}                                                  ║",
                f"║  SCORE:         {self.score:>8.2f} / {self.score_max:.0f}  ({self.score/self.score_max*100:.1f}%)                               ║",
            ]
            for r in RESOURCES:
                g = self.growth_by_resource.get(r, 0)
                mark = " ← BOTTLENECK" if r == self.bottleneck_resource else ""
                lines.append(
                    f"║    {r:<12}: {self.baseline_resources.get(r, 0):>6} → {self.candidate_resources.get(r, 0):>6}  ({g:>5.2f}x){mark:<20}║"
                )
        else:
            lines.append(f"║  SCORE: {self.score:.2f} / {self.score_max:.0f}  (validity gate failed)                     ║")
        lines.append(f"╚{'═'*75}╝")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Main grading function
# ═══════════════════════════════════════════════════════════════════════════════

def grade(
    task_cfg: TaskScoringConfig,
    anchor: Anchor,
    evidence: QoREvidence,
    *,
    cost_spent: int = 0,
    wall_time_s: float = 0.0,
    gates: ValidityGates | None = None,
    ii_applicable: bool = False,
) -> Scorecard:
    """Grade a candidate submission — single unified code path for all tasks.

    All task types share the same formula.  task_type is recorded as a
    label only and does not change any weight, policy, or formula path.
    """
    if gates is None:
        gates = ValidityGates()

    # Infrastructure error → evaluation invalid
    if evidence.infrastructure_error or gates.infrastructure_error:
        return Scorecard(
            schema_version=5, task_id=task_cfg.task_id,
            task_type=task_cfg.task_type, difficulty=task_cfg.difficulty,
            anchor_source=anchor.source, anchor_hash=anchor.hash,
            anchor_valid=anchor.valid,
            valid=False,
            gate_reason="evaluation_invalid: " + (
                evidence.infrastructure_reason or gates.infrastructure_reason),
            stage="infrastructure_error",
        )

    # No valid anchor → cannot score
    if not anchor.valid or anchor.latency is None:
        return Scorecard(
            schema_version=5, task_id=task_cfg.task_id,
            task_type=task_cfg.task_type, difficulty=task_cfg.difficulty,
            anchor_source=anchor.source, anchor_hash=anchor.hash,
            anchor_valid=False,
            valid=False, gate_reason="no_valid_anchor",
        )

    # Capacity check
    if evidence.candidate_resources and anchor.available:
        if not check_capacity(evidence.candidate_resources, anchor.available):
            gates.resource_capacity_pass = False

    # Progress stage
    stage = "unknown"
    if gates.hidden_csim_pass:  stage = "csim_passed"
    if gates.synth_pass:        stage = "synthesized"
    if gates.hidden_cosim_pass: stage = "cosim_passed"
    if gates.implementation_pass: stage = "implemented"

    # Hard gate
    if not gates.all_required_pass:
        return Scorecard(
            schema_version=5, task_id=task_cfg.task_id,
            task_type=task_cfg.task_type, difficulty=task_cfg.difficulty,
            anchor_source=anchor.source, anchor_hash=anchor.hash,
            anchor_valid=anchor.valid,
            valid=False, gate_reason=gates.first_failure,
            csim_pass=gates.hidden_csim_pass,
            synth_pass=gates.synth_pass,
            cosim_pass=gates.hidden_cosim_pass,
            stage=stage,
        )

    if not evidence.required_metrics_complete:
        return Scorecard(
            schema_version=5, task_id=task_cfg.task_id,
            task_type=task_cfg.task_type, difficulty=task_cfg.difficulty,
            anchor_source=anchor.source, anchor_hash=anchor.hash,
            anchor_valid=anchor.valid,
            valid=False, gate_reason="required_metric_missing",
            csim_pass=gates.hidden_csim_pass,
            synth_pass=gates.synth_pass,
            cosim_pass=gates.hidden_cosim_pass,
            stage=stage,
        )

    # ── Effective latency (cosim overrides synth for requires_cosim) ─────
    accel_source = "synth"
    cand_lat = evidence.candidate_latency
    cosim_used = None
    if task_cfg.requires_cosim and evidence.cosim_latency is not None:
        cand_lat = evidence.cosim_latency
        accel_source = "cosim"
        cosim_used = evidence.cosim_latency

    # ── Performance ──────────────────────────────────────────────────────
    anchor_period = max(task_cfg.task_clock_ns, anchor.clock_ns or task_cfg.task_clock_ns)
    cand_period = max(task_cfg.task_clock_ns, evidence.candidate_clock_ns or task_cfg.task_clock_ns)

    anchor_time = anchor_period * (anchor.latency or 1)
    cand_time = cand_period * (cand_lat or 1)

    latency_ratio = anchor_time / max(cand_time, 1e-9)
    ii_ratio = 1.0
    has_ii = ii_applicable and (anchor.ii or 0) > 0 and (evidence.candidate_ii or 0) > 0
    if has_ii:
        ii_ratio = (anchor.ii or 1) / max(evidence.candidate_ii or 1, 1)

    q_perf = performance_quality(latency_ratio, ii_ratio, has_ii)

    # ── Resources ────────────────────────────────────────────────────────
    q_area, growth, bottleneck = area_quality(
        evidence.candidate_resources, anchor.resources, anchor.available)
    area_growth = growth.get(bottleneck, 1.0)

    # ── QoR, efficiency, score ───────────────────────────────────────────
    q_hw = hardware_qor(q_perf, q_area)
    eff = efficiency_factor(cost_spent, task_cfg.budget_limit,
                            wall_time_s, task_cfg.time_limit_s)
    score = combine_score(valid=True, q_hw=q_hw, efficiency=eff)

    return Scorecard(
        schema_version=5,
        task_id=task_cfg.task_id,
        task_type=task_cfg.task_type,
        difficulty=task_cfg.difficulty,
        anchor_source=anchor.source,
        anchor_hash=anchor.hash,
        anchor_valid=anchor.valid,
        valid=True,
        gate_reason="passed",
        csim_pass=gates.hidden_csim_pass,
        synth_pass=gates.synth_pass,
        cosim_pass=gates.hidden_cosim_pass,
        stage=stage,
        latency_ratio=round(latency_ratio, 2),
        ii_ratio=round(ii_ratio, 2),
        q_perf=round(q_perf, 4),
        baseline_resources=dict(anchor.resources),
        candidate_resources=dict(evidence.candidate_resources),
        growth_by_resource={r: round(v, 2) for r, v in growth.items()},
        bottleneck_resource=bottleneck,
        area_growth=round(area_growth, 2),
        q_area=round(q_area, 4),
        cost_spent=cost_spent,
        cost_limit=task_cfg.budget_limit,
        wall_time_s=wall_time_s,
        time_limit_s=task_cfg.time_limit_s,
        efficiency=round(eff, 4),
        q_hw=round(q_hw, 4),
        score=round(score, 2),
        acceleration_source=accel_source,
        cosim_latency_used=cosim_used,
    )
