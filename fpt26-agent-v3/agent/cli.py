"""CLI argument parsing and command dispatch for fpt26-agent-v3."""

from __future__ import annotations

import argparse
from pathlib import Path

from scoring.profiles import DEFAULT_SCORING_PROFILE, SCORING_PROFILE_CHOICES


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.  Stable public API — do not rename flags."""
    p = argparse.ArgumentParser(
        description="FPT26 Track-A agent v3 — pipeline-based LLM4HLS agent with V3 scoring"
    )
    p.add_argument("--task", required=True, type=Path, help="Path to official task directory")
    p.add_argument("--mode", choices=["auto", "baseline", "repair", "optimize", "structural", "full"],
                   default="auto", help="Agent operating mode")
    p.add_argument("--run-role", choices=["submission", "evaluator"], default="submission",
                   help="Submission or evaluator role")
    p.add_argument("--final-kernel", type=Path, default=None,
                   help="Final kernel artifact to grade (required for evaluator)")
    p.add_argument("--output-root", type=Path, default=None, help="Run artifact output root")
    p.add_argument("--budget", type=int, default=None, help="Override task credit budget")
    p.add_argument("--backend", choices=["auto", "openrouter", "custom", "scripted"],
                   default="auto", help="LLM backend selection")
    p.add_argument("--competition", action="store_true",
                   help="Evaluate independent optimization strategy lanes")
    p.add_argument("--max-repair-attempts", type=int, default=None)
    p.add_argument("--max-optimization-rounds", type=int, default=None)
    p.add_argument("--max-structural-attempts", type=int, default=None)
    p.add_argument("--no-score", action="store_true", help="Skip hidden-testbench scoring")
    p.add_argument("--submission-evidence", type=Path, default=None,
                   help="Path to submission_evidence.json for evaluator verification")
    p.add_argument("--scoring-profile", choices=SCORING_PROFILE_CHOICES,
                   default=DEFAULT_SCORING_PROFILE,
                   help="Hardware trade-off profile: balanced, extreme_speed, extreme_speed_capped")
    p.add_argument("--quiet", action="store_true", help="Suppress step-by-step log output")
    p.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="ANSI color policy; use 'always' when piping a live demo through tee",
    )
    return p.parse_args(argv)
