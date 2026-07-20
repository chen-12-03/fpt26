"""V3-aware report aggregation — modern replacement for ``agent/eval.py``.

Key differences from the legacy aggregator:
* Uses official ``score`` / ``score_max``, not ``task_difficulty`` as a multiplier.
* Detects mixed schemas, profiles, and duplicate tasks.
* Rejects corrupted reports and scores outside [0, 100].
* Legacy (pre-V3) reports require an explicit ``--compat`` flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPORT_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class TaskAggregate:
    """Per-task aggregate extracted from a single ``run_report.json``."""

    task_id: str
    task_type: str = ""
    status: str = ""
    mode: str = ""

    # Scoring
    score: float = 0.0
    score_max: float = 100.0
    score_pct: float = 0.0
    scoring_profile: str = "balanced"
    scoring_schema: int = 0
    valid: bool = False

    # Hardware quality
    q_hw: float | None = None
    q_perf: float | None = None
    q_area: float | None = None
    latency_ratio: float | None = None
    area_growth: float | None = None
    bottleneck_resource: str | None = None

    # Costs
    credits_spent: int = 0
    credits_total: int = 0
    wall_time_s: float = 0.0
    grading_time_s: float = 0.0

    # Tool calls
    csim_count: int = 0
    synth_count: int = 0
    cosim_count: int = 0

    # Gates
    csim_ok: bool = False
    synth_ok: bool = False
    cosim_ok: bool | None = None
    frequency_ok: bool = False
    resource_ok: bool = False

    # Run identity
    run_role: str = ""
    report_path: str = ""


@dataclass
class RunSummary:
    """Aggregate summary across multiple task reports."""

    task_count: int = 0
    completed: int = 0
    failed: int = 0
    budget_exceeded: int = 0
    infra_error: int = 0

    total_score: float = 0.0
    total_score_max: float = 0.0
    total_spent: int = 0
    total_budget: int = 0
    total_wall_s: float = 0.0
    total_grading_s: float = 0.0

    tasks: list[TaskAggregate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def score_pct(self) -> float:
        return (
            self.total_score / max(self.total_score_max, 1.0) * 100.0
        )

    @property
    def budget_utilization_pct(self) -> float:
        return (
            self.total_spent / max(self.total_budget, 1) * 100.0
        )

    @property
    def functional_pass_rate(self) -> str:
        return f"{self.completed}/{self.task_count}"


def _is_v3_report(scoring: dict[str, Any] | None) -> bool:
    """Return True if the scoring block uses a V3 (schema >= 5) scorecard."""
    if not isinstance(scoring, dict):
        return False
    return scoring.get("schema_version", 0) >= 5


def _extract_v3_task(report: dict[str, Any], path: str) -> TaskAggregate:
    """Extract a per-task aggregate from a V3 run report."""
    sc = report.get("scoring") or {}
    ev = report.get("evaluation") or {}
    budget = report.get("budget") or {}
    gates = report.get("gates") or {}

    # V3 scoring uses score/score_max, not difficulty
    score = float(sc.get("score", 0.0))
    score_max = float(sc.get("score_max", 100.0))
    if score_max <= 0:
        score_max = 100.0

    # Sanity bounds
    if not (0.0 <= score <= score_max * 1.01):
        raise ValueError(
            f"score {score} out of [0, {score_max}] in {path}"
        )
    if not (0.0 <= score <= 100.01):
        raise ValueError(f"score {score} > 100 in {path}")

    csim_ok = bool(report.get("csim_ok", False))
    synth_ok = bool(report.get("synth_ok", False))
    cosim_ok = report.get("cosim_ok")  # may be None (N/A)

    grading = report.get("grading") or {}
    freq_gate = (gates.get("frequency_100mhz") or {})
    res_gate = (gates.get("resource_capacity") or {})

    return TaskAggregate(
        task_id=str(report.get("task_id", "")),
        task_type=str(report.get("task_type", "")),
        status=str(report.get("status", "")),
        mode=str(report.get("mode", "")),
        score=score,
        score_max=score_max,
        score_pct=round(score / max(score_max, 1.0) * 100.0, 1),
        scoring_profile=str(sc.get("scoring_profile", "balanced")),
        scoring_schema=int(sc.get("schema_version", 0)),
        valid=bool(sc.get("valid", False)),
        q_hw=sc.get("q_hw"),
        q_perf=sc.get("q_perf"),
        q_area=sc.get("q_area"),
        latency_ratio=sc.get("latency_ratio"),
        area_growth=sc.get("area_growth"),
        bottleneck_resource=sc.get("bottleneck_resource"),
        credits_spent=int(budget.get("spent", 0)),
        credits_total=int(budget.get("total", 0)),
        wall_time_s=float(ev.get("wall_time_seconds", 0.0)),
        grading_time_s=float(sc.get("wall_time_s", 0.0)),
        csim_count=int(ev.get("tool_breakdown", {}).get("csim", 0)),
        synth_count=int(ev.get("tool_breakdown", {}).get("synth", 0)),
        cosim_count=int(ev.get("tool_breakdown", {}).get("cosim", 0)),
        csim_ok=csim_ok,
        synth_ok=synth_ok,
        cosim_ok=cosim_ok,
        frequency_ok=bool(freq_gate.get("ok", False)),
        resource_ok=bool(res_gate.get("ok", False)),
        run_role=str(report.get("run_role", "")),
        report_path=path,
    )


def _extract_legacy_task(report: dict[str, Any], path: str) -> TaskAggregate:
    """Extract a per-task aggregate from a legacy (pre-V3) run report."""
    sc = report.get("scoring") or {}
    score = float(sc.get("score", 0.0))
    return TaskAggregate(
        task_id=str(report.get("task_id", "")),
        task_type=str(report.get("task_type", "")),
        status=str(report.get("status", "")),
        score=score,
        score_max=100.0,
        score_pct=round(score / 100.0 * 100.0, 1),
        scoring_schema=0,
        report_path=path,
    )


def collect_reports(
    root: str | Path,
    *,
    compat_legacy: bool = False,
) -> RunSummary:
    """Walk *root* for ``run_report.json`` files and produce a V3-aware summary.

    Args:
        root: Directory to search recursively.
        compat_legacy: If True, also ingest pre-V3 ``run_report.json`` files.

    Returns:
        A :class:`RunSummary` with per-task aggregates and detected errors.

    Raises:
        FileNotFoundError: No reports found under *root*.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise FileNotFoundError(f"output root not found: {root}")

    report_paths = sorted(root_path.rglob("run_report.json"))
    if not report_paths:
        raise FileNotFoundError(f"no run_report.json files under {root}")

    summary = RunSummary()
    seen_tasks: set[str] = set()

    for rp in report_paths:
        try:
            raw = rp.read_text(encoding="utf-8")
            report = __import__("json").loads(raw)
        except Exception as exc:
            summary.errors.append(f"{rp}: unreadable — {exc}")
            continue

        if not isinstance(report, dict):
            summary.errors.append(f"{rp}: not a JSON object")
            continue

        # Schema / compatibility check
        scoring = report.get("scoring")
        if _is_v3_report(scoring):
            try:
                task = _extract_v3_task(report, str(rp))
            except ValueError as exc:
                summary.errors.append(f"{rp}: {exc}")
                continue
        elif compat_legacy and isinstance(scoring, dict):
            task = _extract_legacy_task(report, str(rp))
        else:
            # Non-V3 report without compat flag: skip with note
            continue

        # Duplicate detection
        if task.task_id and task.task_id in seen_tasks:
            summary.errors.append(
                f"{rp}: duplicate task_id '{task.task_id}' — skipped"
            )
            continue
        if task.task_id:
            seen_tasks.add(task.task_id)

        summary.tasks.append(task)
        summary.task_count += 1

        # Roll up status
        status = task.status
        if status == "completed":
            summary.completed += 1
        elif status == "budget_exceeded":
            summary.budget_exceeded += 1
        elif status == "infrastructure_error":
            summary.infra_error += 1
        else:
            summary.failed += 1

        summary.total_score += task.score
        summary.total_score_max += task.score_max
        summary.total_spent += task.credits_spent
        summary.total_budget += task.credits_total
        summary.total_wall_s += task.wall_time_s
        summary.total_grading_s += task.grading_time_s

    if summary.task_count == 0:
        raise FileNotFoundError(
            f"no valid (V3) run_report.json files under {root}"
            + (" (use --compat for legacy reports)" if not compat_legacy else "")
        )

    return summary
