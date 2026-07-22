"""Scoring utilities extracted from OptimizeAgent — pure functions."""

from __future__ import annotations

from typing import Any

from scoring.scoring_v3 import (
    Anchor, QoREvidence, TaskScoringConfig, ValidityGates, verified_available_resources,
)
from scoring.profiles import DEFAULT_SCORING_PROFILE, grade_with_profile
from agent.agents.optimization.diagnostics import _report_latency


def score_candidate(
    task: Any, anchor_report: Any, candidate_report: Any,
    scoring_profile: str = DEFAULT_SCORING_PROFILE,
    *, cosim_latency: int | None = None,
) -> Any:
    """Evaluate visible synth QoR through the current authoritative scorer."""
    cfg = TaskScoringConfig(
        task_id=task.id, task_type=task.type, difficulty=task.difficulty,
        requires_cosim=task.requires_cosim, budget_limit=task.budget,
        task_clock_ns=task.clock_ns,
    )
    anchor = Anchor(
        source="starter", valid=True,
        latency=_report_latency(anchor_report),
        ii=anchor_report.interval_max,
        clock_ns=anchor_report.clock_period_ns or task.clock_ns,
        resources=dict(anchor_report.resources),
        available=verified_available_resources(getattr(anchor_report, "available", None)),
    )
    evidence = QoREvidence(
        candidate_latency=_report_latency(candidate_report),
        candidate_ii=candidate_report.interval_max,
        candidate_clock_ns=candidate_report.clock_period_ns or task.clock_ns,
        cosim_latency=cosim_latency,
        candidate_resources=dict(candidate_report.resources),
    )
    gates = ValidityGates(
        hidden_csim_pass=True,
        hidden_cosim_pass=True if task.requires_cosim else None,
        synth_pass=True, resource_capacity_pass=True,
    )
    return grade_with_profile(
        task_cfg=cfg, anchor=anchor, evidence=evidence,
        scoring_profile=scoring_profile, cost_spent=0, wall_time_s=0.0,
        gates=gates,
    )


def latest_successful_cosim_latency(results: list[Any]) -> int | None:
    """Find the newest successful CoSim latency from results."""
    for result in reversed(results):
        payload = getattr(result, "cosim", None)
        if (getattr(result, "kind", None) == "cosim"
                and getattr(result, "ok", False)
                and payload is not None
                and getattr(payload, "passed", False)
                and getattr(payload, "latency_max", None) is not None):
            return int(payload.latency_max)
    return None


def latest_successful_synth(results: list[Any]) -> Any | None:
    """Return the newest reusable synthesis result from the transcript."""
    for result in reversed(results):
        if (getattr(result, "kind", None) == "synth"
                and getattr(result, "ok", False)
                and getattr(result, "report", None) is not None):
            return result
    return None
