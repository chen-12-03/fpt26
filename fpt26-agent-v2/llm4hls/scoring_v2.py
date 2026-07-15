"""V2 Scoring Standard for FPT26 Agent Evaluation.

Redesigned from the ground up to address defects in the original formula:

Defects fixed (D1-D11, see docs/scoring-redesign-brief.md §8.4):
  D1:  Repair tasks no longer capped at 70% — separate quality path
  D2:  Budget efficiency factor reduces score for wasteful runs
  D3:  Attempt efficiency captured in budget factor
  D4:  Area growth penalised via multiplicative area_factor
  D5:  No hard ACCEL_CAP — log-scale diminishing returns instead
  D6:  Throughput (II) improvement rewarded via ii_factor
  D7:  Area-efficiency embedded in area_factor
  D8:  Cosim failure cost visible via budget factor
  D9:  Cosim-measured latency takes priority for structural tasks
  D10: Area improvement rewarded (area_factor > 1.0 bonus, capped)
  D11: Budget overrun penalised linearly

Formula overview
================

For ALL task types, functional correctness is a hard gate: fail → score = 0.

For OPTIMIZE / STRUCTURAL / GENERATE tasks::

    latency_score = log2(accel + 1) / log2(ACCEL_REF + 1)    [0-1, diminishing]
    area_factor   = 2 / (1 + max(LUT_g, FF_g, DSP_g))        [penalty for bloat]
    ii_factor     = 1 + II_STRENGTH × max(0, 1 - II_cand/II_base)
    budget_factor = 1 - BUDGET_STRENGTH × (spent / total)

    quality  = (W_FUNC + W_SYNTH × synth_pass + W_LATENCY × latency_score)
               × clamp(area_factor, 0.05, AREA_BONUS_CAP)
               × ii_factor

    score = difficulty × quality × budget_factor

For REPAIR tasks (no acceleration expected)::

    quality  = W_FUNC + W_SYNTH × synth_pass   [capped at W_FUNC + W_SYNTH]
    score    = difficulty × quality × budget_factor

For STRUCTURAL tasks, cosim-measured latency replaces synth estimate::

    accel = baseline_synth_latency / cosim_measured_latency

All weights and parameters are overridable via environment variables.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from .report import SynthReport
from .task import Task
from .tools import CoSimTool, CSimTool, SynthTool, ToolResult


# ---------------------------------------------------------------------------
# Configurable parameters (all overridable via env vars)
# ---------------------------------------------------------------------------

# Quality weights — must sum close to 1.0 for intuitive scaling
W_FUNC = float(os.environ.get("SCORE_W_FUNC", "0.45"))       # functional correctness
W_SYNTH = float(os.environ.get("SCORE_W_SYNTH", "0.15"))     # synthesizability
W_LATENCY = float(os.environ.get("SCORE_W_LATENCY", "0.40")) # latency improvement

# Diminishing returns: log2(accel+1) / log2(ACCEL_REF+1)
# ACCEL_REF=32 → 5 doublings to saturate.  At accel=1x:0.20, 8x:0.63, 27x:0.96, 31x:1.0
ACCEL_REF = float(os.environ.get("SCORE_ACCEL_REF", "31.0"))

# Area penalty: area_factor = 2 / (1 + max_growth)
# Growth=1x:1.00, 2x:0.67, 5x:0.33, 10x:0.18, 84x:0.024
# For area IMPROVEMENT (growth < 1): bonus capped at AREA_BONUS_CAP
AREA_BONUS_CAP = float(os.environ.get("SCORE_AREA_BONUS_CAP", "1.30"))
AREA_FLOOR = float(os.environ.get("SCORE_AREA_FLOOR", "0.05"))  # minimum area_factor

# Throughput (II) bonus
II_STRENGTH = float(os.environ.get("SCORE_II_STRENGTH", "0.15"))

# Budget penalty: budget_factor = 1 - BUDGET_STRENGTH × (spent / total)
BUDGET_STRENGTH = float(os.environ.get("SCORE_BUDGET_STRENGTH", "0.25"))

# For repair tasks: quality = W_FUNC + W_SYNTH (no latency component)
# This gives repair tasks a max quality of 0.60 with default weights,
# which when multiplied by budget_factor (up to 1.0) = 0.60 × difficulty
# But if budget is efficient, budget_factor can reach 1.0.
# REPAIR_QUALITY_CAP allows repair tasks to reach higher scores for perfect runs.
REPAIR_QUALITY_CAP = float(os.environ.get("SCORE_REPAIR_QUALITY_CAP", "0.95"))


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------


@dataclass
class ScorecardV2:
    task_id: str
    difficulty: int
    task_type: str
    functional_pass: bool
    synth_pass: bool
    cosim_pass: bool | None
    baseline_latency: int | None        # synth latency of original code
    candidate_latency: int | None        # synth latency of candidate
    cosim_latency: int | None            # RTL-measured latency (structural only)
    acceleration: float | None           # baseline / candidate (or cosim if structural)
    acceleration_source: str             # "synth" | "cosim"
    is_opt: bool
    candidate_report: SynthReport | None
    baseline_report: SynthReport | None

    # Dimension scores (all 0-1 range for transparency)
    latency_score: float
    area_factor: float
    ii_factor: float
    budget_factor: float
    quality: float

    # Final
    score: float
    score_max: float                     # theoretical maximum for this task

    def render(self) -> str:
        lines = [
            f"╔══ Scorecard V2: {self.task_id} (type={self.task_type}, difficulty={self.difficulty}) ══╗",
            f"║  functional (hidden TB): {'PASS' if self.functional_pass else 'FAIL':<45}║",
            f"║  synthesizable         : {'PASS' if self.synth_pass else 'FAIL':<45}║",
        ]
        if self.cosim_pass is not None:
            lines.append(
                f"║  cosim (C/RTL verify)  : {'PASS' if self.cosim_pass else 'FAIL':<45}║"
            )
        lines += [
            f"╠{'─'*62}╣",
            f"║  baseline latency      : {str(self.baseline_latency) + ' cyc':<45}║",
            f"║  candidate latency     : {str(self.candidate_latency) + ' cyc':<45}║",
        ]
        if self.cosim_latency is not None:
            lines.append(
                f"║  cosim measured latency: {str(self.cosim_latency) + ' cyc':<45}║"
            )
        if self.acceleration is not None:
            lines.append(
                f"║  acceleration          : {self.acceleration:.2f}x  (source={self.acceleration_source}){'':<20}║"
            )
        lines += [
            f"╠{'─'*62}╣",
            f"║  latency_score : {self.latency_score:.4f}   area_factor: {self.area_factor:.4f}       ║",
            f"║  ii_factor     : {self.ii_factor:.4f}   budget_factor: {self.budget_factor:.4f}    ║",
            f"║  quality       : {self.quality:.4f}                                   ║",
            f"╠{'─'*62}╣",
            f"║  SCORE         : {self.score:.4f} / {self.score_max:.4f}  ({self.score/self.score_max*100:.1f}%){'':<17}║",
            f"╚{'═'*62}╝",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _latency(r: ToolResult | None) -> int | None:
    if r is None or r.report is None:
        return None
    return r.report.latency_worst or r.report.latency_avg


def _ii(r: ToolResult | None) -> int | None:
    if r is None or r.report is None:
        return None
    return r.report.interval_max or r.report.interval_min


def _resources(r: SynthReport | None) -> dict[str, int]:
    if r is None:
        return {}
    return r.resources if hasattr(r, "resources") else {}


def _log_scale(value: float, ref: float) -> float:
    """Log-scale diminishing returns: log2(v+1) / log2(ref+1), clamped to [0, 1]."""
    if value <= 0:
        return 0.0
    if ref <= 0:
        ref = 31.0
    return min(math.log2(value + 1) / math.log2(ref + 1), 1.0)


# ---------------------------------------------------------------------------
# Main grading function
# ---------------------------------------------------------------------------


def grade(
    task: Task,
    candidate_kernel: str,
    work_root: Path,
    *,
    budget_spent: int = 0,
    cosim_attempts: int = 0,
    csim_attempts: int = 0,
) -> ScorecardV2:
    """Grade a candidate kernel against hidden testbench + synthesis baseline.

    Parameters
    ----------
    task : Task
        The task definition (includes baseline kernel, hidden testbench, budget).
    candidate_kernel : str
        The agent's final kernel source code.
    work_root : Path
        Scratch directory for tool runs (grade_csim, grade_synth_cand, etc.).
    budget_spent : int
        Credits the agent consumed during the run.  Used for budget_factor.
        Pass 0 if scoring offline (budget_factor will be 1.0).
    cosim_attempts : int
        Number of cosim calls the agent made (for transcript visibility, not scoring).
    csim_attempts : int
        Number of csim calls the agent made (for transcript visibility, not scoring).
    """
    work_root = Path(work_root)
    csim_tool, synth_tool, cosim_tool = CSimTool(), SynthTool(), CoSimTool()

    # ── 1. Hidden functional test ────────────────────────────────────────
    hidden_files = task.assemble(
        candidate_kernel, task.hidden_tb_code, task.hidden_tb_name
    )
    func = csim_tool.run(
        work_root / "grade_csim",
        hidden_files,
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
    )

    cosim_pass: bool | None = None
    cosim_latency: int | None = None

    if task.requires_cosim:
        cosim = cosim_tool.run(
            work_root / "grade_cosim",
            hidden_files,
            synth_sources=[task.kernel_name],
            tb_sources=[task.hidden_tb_name],
            top=task.top,
            part=task.part,
            clock_ns=task.clock_ns,
        )
        cosim_pass = cosim.ok
        if cosim.cosim is not None:
            cosim_latency = cosim.cosim.latency_max or cosim.cosim.latency_avg

    functional_pass = func.ok and (cosim_pass is not False)

    # ── 2. Candidate synthesis ───────────────────────────────────────────
    cand_files = dict(task.headers)
    cand_files[task.kernel_name] = candidate_kernel
    cand_synth = synth_tool.run(
        work_root / "grade_synth_cand",
        cand_files,
        synth_sources=[task.kernel_name],
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
    )

    # ── 3. Baseline synthesis ────────────────────────────────────────────
    base_files = dict(task.headers)
    base_files[task.kernel_name] = task.kernel_code
    base_synth = synth_tool.run(
        work_root / "grade_synth_base",
        base_files,
        synth_sources=[task.kernel_name],
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
    )

    synth_pass = cand_synth.ok
    cand_lat = _latency(cand_synth)
    base_lat = _latency(base_synth)
    cand_ii = _ii(cand_synth)
    base_ii = _ii(base_synth)

    cand_res = _resources(cand_synth.report)
    base_res = _resources(base_synth.report)

    # ── 4. Compute acceleration ──────────────────────────────────────────
    # For structural tasks, cosim-measured latency is ground truth.
    # For everyone else, use synthesis estimates.
    acceleration: float | None = None
    acceleration_source = "synth"

    if task.requires_cosim and cosim_latency is not None and base_lat is not None and base_lat > 0:
        # Use RTL-measured latency for structural tasks (D9 fix)
        acceleration = base_lat / cosim_latency
        acceleration_source = "cosim"
    elif cand_lat is not None and base_lat is not None and base_lat > 0:
        acceleration = base_lat / cand_lat
        acceleration_source = "synth"

    is_opt = acceleration is not None and acceleration > 1.0

    # ── 5. Hard gate: functional failure → score = 0 ─────────────────────
    if not functional_pass:
        return ScorecardV2(
            task_id=task.id,
            difficulty=task.difficulty,
            task_type=task.type,
            functional_pass=False,
            synth_pass=synth_pass,
            cosim_pass=cosim_pass,
            baseline_latency=base_lat,
            candidate_latency=cand_lat,
            cosim_latency=cosim_latency,
            acceleration=None,
            acceleration_source="none",
            is_opt=False,
            candidate_report=cand_synth.report,
            baseline_report=base_synth.report,
            latency_score=0.0,
            area_factor=1.0,
            ii_factor=1.0,
            budget_factor=1.0,
            quality=0.0,
            score=0.0,
            score_max=task.difficulty,
        )

    # ── 6. Dimension: latency score (D5 fix: no hard cap) ────────────────
    if task.type == "repair":
        # Repair tasks: no acceleration expected.  Quality comes from
        # correctness + synthesizability alone (D1 fix).
        latency_score = 0.0
    elif acceleration is not None and acceleration > 1.0:
        latency_score = _log_scale(acceleration, ACCEL_REF)
    elif acceleration is not None and acceleration == 1.0:
        latency_score = 0.25  # neutral: correct but no improvement
    else:
        latency_score = 0.25  # neutral baseline

    # ── 7. Dimension: area factor (D4 fix: penalise bloat) ───────────────
    if base_res and cand_res:
        growths = []
        for key in ("LUT", "FF", "DSP"):
            base = base_res.get(key, 0)
            cand = cand_res.get(key, 0)
            if base and base > 0:
                growths.append(cand / base)
            elif cand > 0 and base == 0:
                growths.append(2.0)  # moderate penalty for adding new resource type
        max_growth = max(growths) if growths else 1.0
    else:
        max_growth = 1.0

    # area_factor = 2 / (1 + max_growth)
    # Growth=1x → 1.00, 2x → 0.67, 0.75x (improvement) → 1.14
    area_factor = 2.0 / (1.0 + max(max_growth, 0.01))
    # Clamp: floor prevents area from zeroing score; cap limits improvement bonus
    area_factor = max(min(area_factor, AREA_BONUS_CAP), AREA_FLOOR)

    # ── 8. Dimension: throughput / II factor (D6 fix) ────────────────────
    ii_factor = 1.0
    if base_ii is not None and cand_ii is not None and base_ii > 0:
        ii_ratio = cand_ii / base_ii
        improvement = max(0.0, 1.0 - ii_ratio)  # 0 = no change, 1 = II became 1
        ii_factor = 1.0 + II_STRENGTH * improvement  # e.g. 1.0 + 0.15*0.99 = 1.15

    # ── 9. Dimension: budget factor (D2, D8, D11 fix) ────────────────────
    total_budget = max(task.budget, 1)
    budget_ratio = min(budget_spent / total_budget, 1.0)
    budget_factor = 1.0 - BUDGET_STRENGTH * budget_ratio

    # ── 10. Assemble quality ─────────────────────────────────────────────
    if task.type == "repair":
        # Repair: correctness + synth only, capped at REPAIR_QUALITY_CAP (D1 fix)
        quality = (W_FUNC * 1.0 + W_SYNTH * (1.0 if synth_pass else 0.0)) * area_factor
        quality = min(quality, REPAIR_QUALITY_CAP)
    else:
        # Optimize / structural / generate: full formula
        quality = (
            W_FUNC * 1.0
            + W_SYNTH * (1.0 if synth_pass else 0.0)
            + W_LATENCY * latency_score
        )
        quality *= area_factor * ii_factor

    # Synth failure penalty: if won't synthesize, quality capped at W_FUNC (D8-like)
    if not synth_pass:
        quality = min(quality, W_FUNC * area_factor)

    # ── 11. Final score ──────────────────────────────────────────────────
    score = task.difficulty * quality * budget_factor
    score_max = task.difficulty * 1.0  # theoretical max

    return ScorecardV2(
        task_id=task.id,
        difficulty=task.difficulty,
        task_type=task.type,
        functional_pass=functional_pass,
        synth_pass=synth_pass,
        cosim_pass=cosim_pass,
        baseline_latency=base_lat,
        candidate_latency=cand_lat,
        cosim_latency=cosim_latency,
        acceleration=acceleration,
        acceleration_source=acceleration_source,
        is_opt=is_opt,
        candidate_report=cand_synth.report,
        baseline_report=base_synth.report,
        latency_score=round(latency_score, 4),
        area_factor=round(area_factor, 4),
        ii_factor=round(ii_factor, 4),
        budget_factor=round(budget_factor, 4),
        quality=round(quality, 4),
        score=round(score, 4),
        score_max=round(score_max, 4),
    )
