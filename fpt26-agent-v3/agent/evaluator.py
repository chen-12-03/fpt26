"""Evaluator — backward-compatibility façade.

The full evaluator implementation is in ``agent.pipeline.evaluator``.
Formal mode requires SubmissionEvidence; use legacy mode otherwise.
"""

from __future__ import annotations

from pathlib import Path

from agent.models import SubmissionEvidence

# Re-export symbols that tests import directly
from agent.pipeline.evaluator import _hidden_source  # noqa: F401


def evaluate_final_kernel(
    *,
    task_dir: Path,
    kernel_path: Path,
    output_root: str,
    scoring_profile: str,
    verbose: bool,
    submission_evidence: SubmissionEvidence | None = None,
):
    """Run evaluator grading (delegates to pipeline.evaluator).

    When *submission_evidence* is provided, the formal evaluator is used.
    Otherwise, the legacy evaluator is used (marked as non-formal).
    """
    if submission_evidence is not None:
        from agent.pipeline.evaluator import run_evaluator
        return run_evaluator(
            task_dir=task_dir, kernel_path=kernel_path, output_root=output_root,
            scoring_profile=scoring_profile, verbose=verbose,
            submission_evidence=submission_evidence,
        )
    else:
        from agent.pipeline.evaluator import run_evaluator_legacy
        return run_evaluator_legacy(
            task_dir=task_dir, kernel_path=kernel_path, output_root=output_root,
            scoring_profile=scoring_profile, verbose=verbose,
        )
