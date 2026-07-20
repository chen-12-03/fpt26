"""Evaluator pipeline orchestration.

Delegates to the existing ``agent.evaluator`` for now; this module provides
the typed entry point for ``main.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.agents.base import RunState
from agent.models import SubmissionEvidence


def run_evaluator(
    *,
    task_dir: Path,
    kernel_path: Path,
    output_root: str,
    scoring_profile: str,
    verbose: bool,
    submission_evidence: SubmissionEvidence | None = None,
) -> RunState:
    """Run the evaluator pipeline and return the terminal RunState.

    This is a thin typed wrapper around ``agent.evaluator.evaluate_final_kernel``.
    """
    from agent.evaluator import evaluate_final_kernel

    return evaluate_final_kernel(
        task_dir=task_dir,
        kernel_path=kernel_path,
        output_root=output_root,
        scoring_profile=scoring_profile,
        verbose=verbose,
        submission_evidence=submission_evidence,
    )
