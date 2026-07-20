"""Report schema constants and field definitions.

Single source of truth for report structure, versioning, and vocabulary.
"""

from __future__ import annotations

# Current report schema version written by ``write_run_report``.
REPORT_SCHEMA_VERSION = 1

# Canonical status vocabulary — shared across reports and evidence.
STATUS_VOCABULARY: tuple[str, ...] = (
    "running",
    "completed",
    "failed",
    "budget_exceeded",
    "infrastructure_error",
)

# Resource keys for synthesis reports and capacity gates.
RESOURCE_KEYS: tuple[str, ...] = ("LUT", "FF", "DSP", "BRAM_18K", "URAM")

# Gate sections in the run report.
GATE_SECTIONS: tuple[str, ...] = (
    "interface",
    "frequency_100mhz",
    "resource_capacity",
    "required_cosim",
    "public_acceptance",
    "evaluator_acceptance",
)

# Scoring fields that appear in the report.
SCORING_FIELDS_V3: tuple[str, ...] = (
    "schema_version", "scoring_profile",
    "performance_weight", "area_weight", "area_reward_capped",
    "score", "score_max", "score_pct",
    "valid", "gate_reason",
    "csim_pass", "synth_pass", "cosim_pass", "resource_capacity_pass",
    "anchor_source",
    "latency_ratio", "acceleration_source", "cosim_latency_used",
    "performance_ratio", "area_growth", "area_ratio", "effective_area_ratio",
    "bottleneck_resource",
    "q_perf", "q_area", "hardware_ratio", "q_hw", "efficiency",
    "growth_by_resource", "baseline_resources", "candidate_resources",
    "available_resources",
    "cost_spent", "cost_limit", "wall_time_s", "time_limit_s",
)
