#!/usr/bin/env python3
"""Fail-closed integrity checks for the frozen study artifacts."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

from collect_pairs import derive_starter


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "analysis/qhw_reference_study"
RAW = ROOT / "runs/qhw_reference_study_20260801/raw"


def main() -> int:
    for script in STUDY.glob("*.py"):
        ast.parse(script.read_text(), filename=str(script))

    analysis = json.loads((STUDY / "results/analysis.json").read_text())
    assert analysis["alternative_attempt_count"] == 1
    assert analysis["alternative_weights"] == {"performance": 0.60, "area": 0.40}
    assert analysis["summary"]["collected_task_count"] == 36
    assert analysis["summary"]["scorable_task_count"] == 24
    assert analysis["summary"]["api_request_count"] == 0
    assert all(task["upstream_hash_verified"] for task in analysis["tasks"])
    assert len({task["task_id"] for task in analysis["tasks"]}) == 36
    assert len({task["source_sha256"] for task in analysis["tasks"]}) == 36

    for task in analysis["tasks"]:
        evidence_path = RAW / task["task_id"] / "evidence.json"
        evidence = json.loads(evidence_path.read_text())
        assert evidence["api"]["request_count"] == 0
        kernel = evidence["pair"]["kernel_name"]
        task_dir = Path(evidence["task_dir"])
        reference_text = (task_dir / kernel).read_text()
        starter_text, _removed = derive_starter(reference_text)
        for side in ("starter", "reference"):
            source = RAW / task["task_id"] / f"{side}_synth" / kernel
            assert source.is_file(), source
            original_text = starter_text if side == "starter" else reference_text
            digest = hashlib.sha256(original_text.encode()).hexdigest()
            assert digest == evidence["pair"][f"{side}_sha256"]
            # The runner's only source preparation is removal of deprecated
            # C++ ``register`` keywords for clang-16 compatibility.
            prepared_text = re.sub(r"\bregister\s+", "", original_text)
            assert source.read_text() == prepared_text

    print(
        "verified: 36 source pairs, 24 scored tasks, "
        "one alternative coefficient pair, API requests=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
