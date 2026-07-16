"""FPT26 Agent V3 — LLM4HLS Scoring Engine implementing V3 Spec.

This package provides a standalone, Vitis-independent scoring engine that
evaluates HLS agent submissions according to the FPT26 LLM4HLS Scoring
Specification V3.0 (docs/FPT26_LLM4HLS_Scoring_Spec_V3.md).

Architecture:
    scoring_v3.py       — Pure mathematical kernel (Phase 1): ratio_utility,
                          workload_time, augmented_resource_growth, hardware_qor,
                          efficiency_factor, combine_score, grade(), ScorecardV3.
    test_scoring_v3.py  — Comprehensive tests with 3 real FPT26 tasks.

Note: This directory uses a hyphenated name (fpt26-agent-v3). Python cannot
use it as a package name. Import modules directly by adding this directory
to sys.path, or set PYTHONPATH.
"""

__version__ = "5.0.0"
