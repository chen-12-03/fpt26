"""Enforce the post-calibration schema-10 scoring freeze manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scoring import __version__
from scoring.scoring_v3 import SCHEMA_VERSION, W_AREA, W_PERFORMANCE


_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _WORKSPACE_ROOT / "fpt26-agent-v3/scoring/scoring-freeze.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text())


def test_frozen_scoring_identity_and_formula() -> None:
    manifest = _manifest()
    assert manifest["scoring_version"] == __version__ == "10.0.0"
    assert manifest["scoring_schema"] == SCHEMA_VERSION == 10
    assert manifest["formula"]["performance_weight"] == W_PERFORMANCE == 0.55
    assert manifest["formula"]["area_weight"] == W_AREA == 0.45
    assert W_PERFORMANCE + W_AREA == manifest["formula"]["weight_sum"] == 1.0
    assert manifest["formula"]["standardized_efficiency"] == "explicit_override_1"
    assert manifest["formula"]["production_efficiency"] == "measured_cost_time"


def test_frozen_scoring_files_match_manifest() -> None:
    for relative, expected in _manifest()["files"].items():
        path = _WORKSPACE_ROOT / relative
        assert path.is_file(), f"frozen scoring file missing: {relative}"
        assert _sha256(path) == expected, f"frozen scoring file changed: {relative}"


def test_archived_evidence_matches_when_present() -> None:
    """Tracked evidence is mandatory; ignored bulky raw-run evidence is optional.

    The external run directories are intentionally not required in a clean Git
    checkout.  When retained in the validation workspace, however, any drift is
    a hard failure.
    """
    manifest = _manifest()
    records = [
        manifest["evidence"]["reference_calibration_report"],
        manifest["evidence"]["official_acceptance_report"],
        *manifest["evidence"]["official_run_reports"].values(),
    ]
    checked = 0
    for record in records:
        path = _WORKSPACE_ROOT / record["path"]
        if path.exists():
            assert _sha256(path) == record["sha256"], f"frozen evidence changed: {record['path']}"
            checked += 1
    assert checked >= 1, "tracked official acceptance evidence is missing"
