from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_committed_paper_macros_match_canonical_evidence() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "technical-paper/scripts/update_results.py"),
            "--check",
        ],
        cwd=repo_root,
        check=True,
    )
