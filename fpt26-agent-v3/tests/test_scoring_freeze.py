"""Enforce the schema-11 production scoring freeze manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scoring import __version__
from scoring.scoring_v3 import (
    MAX_ZERO_RESOURCE_REWARD,
    SCHEMA_VERSION,
    SOURCE_CHANGE_RATIO,
    VALIDITY_RESCUE_RATIO,
    W_AREA,
    W_PERFORMANCE,
)


_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _WORKSPACE_ROOT / "fpt26-agent-v3/scoring/scoring-freeze-v11.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text())


def test_frozen_scoring_identity_and_formula() -> None:
    manifest = _manifest()
    assert manifest["scoring_version"] == __version__ == "11.0.0"
    assert manifest["scoring_schema"] == SCHEMA_VERSION == 11
    assert manifest["formula"]["performance_weight"] == W_PERFORMANCE == 0.55
    assert manifest["formula"]["area_weight"] == W_AREA == 0.45
    assert W_PERFORMANCE + W_AREA == manifest["formula"]["weight_sum"] == 1.0
    assert manifest["formula"]["source_change_ratio"] == SOURCE_CHANGE_RATIO == 1.01
    assert manifest["formula"]["validity_rescue_ratio"] == VALIDITY_RESCUE_RATIO == 2.0
    assert (
        manifest["formula"]["zero_candidate_resource_reward"]
        == MAX_ZERO_RESOURCE_REWARD
        == 4.0
    )
    assert manifest["formula"]["candidate_self_anchor_allowed"] is False
    assert manifest["formula"]["production_regressions"] == "signed"
    assert manifest["formula"]["production_efficiency"] == "measured_cost_time"


def test_frozen_scoring_files_match_manifest() -> None:
    for relative, expected in _manifest()["files"].items():
        path = _WORKSPACE_ROOT / relative
        assert path.is_file(), f"frozen scoring file missing: {relative}"
        assert _sha256(path) == expected, f"frozen scoring file changed: {relative}"


def test_frozen_schema11_evidence_and_real_run() -> None:
    """Require tracked evidence and audit retained real-run evidence when present."""
    manifest = _manifest()
    for name, record in manifest["evidence"].items():
        path = _WORKSPACE_ROOT / record["path"]
        if name == "real_api_summary" and not path.exists():
            continue
        assert path.is_file(), f"frozen evidence missing: {record['path']}"
        assert _sha256(path) == record["sha256"], f"frozen evidence changed: {record['path']}"

    summary_path = _WORKSPACE_ROOT / manifest["evidence"]["real_api_summary"]["path"]
    if not summary_path.exists():
        return
    summary = json.loads(summary_path.read_text())
    validation = manifest["validation"]
    assert summary["selected_task_count"] == validation["real_api_task_count"] == 10
    assert summary["completed_record_count"] == validation["real_api_completed_count"] == 10
    assert summary["audit_error_record_count"] == validation["real_api_audit_errors"] == 0
    assert summary["execution_source"]["stable"] is validation["execution_source_stable"] is True
    assert (
        summary["execution_source"]["current"]["tree_sha256"]
        == validation["execution_source_tree_sha256"]
    )
    assert all(record["outcome"] == "completed" for record in summary["records"])
    assert all(record["submission"]["model"] == "qwen3-coder-plus" for record in summary["records"])
    assert all(
        record["submission"]["model_compliance"]["compliance_proven"] is True
        for record in summary["records"]
    )
    assert sum(record["submission"]["api"]["request_count"] for record in summary["records"]) == 23
    assert sum(record["submission"]["api"]["total_tokens"] for record in summary["records"]) == 158073
