"""FPT26 Agent V3 — authoritative unified LLM4HLS scoring engine.

This package provides a standalone, Vitis-independent scoring engine that
evaluates HLS agent submissions according to the FPT26 LLM4HLS Scoring
Specification V3.0 (docs/FPT26_LLM4HLS_Scoring_Spec_V3.md).

Architecture:
    scoring_v3.py       — Pure scoring kernel; filename retained for harness compatibility.
    test_scoring_v3.py  — Unit, boundary, and representative-task tests.

Note: This directory uses a hyphenated name (fpt26-agent-v3). Python cannot
use it as a package name. Import modules directly by adding this directory
to sys.path, or set PYTHONPATH.
"""

__version__ = "10.0.0"
