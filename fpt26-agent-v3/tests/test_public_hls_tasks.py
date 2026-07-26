from __future__ import annotations

import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO_ROOT / "tasks/generated/public_hls_validated_tasks_manifest.json"


def test_public_hls_manifest_matches_validated_task_dirs() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validated = manifest["validated"]

    assert manifest["validated_count"] >= 100
    assert manifest["failed_count"] == 28
    assert manifest["validated_by_source"] == {
        "amd_accel": 29,
        "amd_intro": 73,
    }
    scoreable_gate = manifest["scoreable_gate"]
    metric_incomplete = set(scoreable_gate["metric_incomplete_task_ids"])
    assert scoreable_gate["allow_missing_score_metrics"] is True
    assert scoreable_gate["metric_incomplete_count"] == len(metric_incomplete)
    assert scoreable_gate["metric_incomplete_count"] == 27
    assert metric_incomplete <= {record["task_id"] for record in validated}

    for record in validated:
        task_dir = _REPO_ROOT / "tasks/generated" / record["task_id"]
        assert task_dir.is_dir()
        spec = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
        provenance = spec["provenance"]
        assert provenance["public_only"] is True
        assert provenance["hidden_imported"] is False
        assert provenance["reference_imported"] is False
        assert provenance["source_url"] == record["source_url"]
        assert provenance["license"] in {"Apache-2.0", "MIT"}
        assert provenance["top_function"] == spec["top"]
        assert provenance["source_sha256"] == record["source_sha256"]
        assert record["csim_ok"] is True
        assert record["synth_ok"] is True
