"""Integrity checks for the pre-weight-search reference classification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = Path(__file__).with_name("reference_classification.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256sum_tree(root: Path) -> tuple[str, int]:
    """Match ``find | sort | xargs sha256sum | sha256sum`` from repo root."""
    files = sorted(path for path in root.rglob("*") if path.is_file())
    listing = "".join(
        f"{_sha256(path)}  {path.relative_to(_REPO_ROOT).as_posix()}\n"
        for path in files
    ).encode()
    return hashlib.sha256(listing).hexdigest(), len(files)


def _sha256sum_legacy_generated_reference_tree(root: Path) -> tuple[str, int]:
    files = []
    for task_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        if not (task_dir / "reference").is_dir():
            continue
        files.extend(path for path in task_dir.rglob("*") if path.is_file())
    files = sorted(files)
    listing = "".join(
        f"{_sha256(path)}  {path.relative_to(_REPO_ROOT).as_posix()}\n"
        for path in files
    ).encode()
    return hashlib.sha256(listing).hexdigest(), len(files)


def test_frozen_classification_sources_match_manifest() -> None:
    manifest = json.loads(_MANIFEST.read_text())

    assert manifest["status"] == "frozen_before_weight_search"
    for name, spec in manifest["source_digest"].items():
        if not isinstance(spec, dict) or "root" not in spec:
            continue
        if name == "generated_tree":
            digest, count = _sha256sum_legacy_generated_reference_tree(
                _REPO_ROOT / spec["root"]
            )
        else:
            digest, count = _sha256sum_tree(_REPO_ROOT / spec["root"])
        assert count == spec["file_count"]
        assert digest == spec["sha256"]


def test_generated_references_are_neutral_identity_ppa_baselines() -> None:
    manifest = json.loads(_MANIFEST.read_text())
    generated = manifest["calibration_classes"]["ppa_reference"][0]
    task_dirs = sorted(
        path for path in (_REPO_ROOT / "tasks/generated").iterdir()
        if path.is_dir() and (path / "reference").is_dir()
    )

    assert generated["selector"] == "tasks/generated/*"
    assert generated["subtype"] == "baseline_identity"
    assert len(task_dirs) == generated["task_count"] == 94
    assert generated["starter_reference_identical_count"] == 94
    for task_dir in task_dirs:
        task_spec = (task_dir / "task.toml").read_text()
        kernel_line = next(
            line for line in task_spec.splitlines()
            if line.startswith("kernel_file = ")
        )
        kernel_name = kernel_line.split('"')[1]
        assert (task_dir / kernel_name).read_bytes() == (
            task_dir / "reference" / kernel_name
        ).read_bytes()


def test_classification_counts_and_official_hashes_are_frozen() -> None:
    manifest = json.loads(_MANIFEST.read_text())
    classes = manifest["calibration_classes"]
    summary = manifest["summary"]

    assert summary == {
        "total_tasks": 97,
        "ppa_reference_tasks": 95,
        "correctness_only_tasks": 2,
        "unknown_tasks": 0,
        "non_trivial_ppa_constraints_before_vitis": 1,
    }
    assert classes["unknown"] == []

    official = classes["ppa_reference"][1:] + classes["correctness_only"]
    assert {entry["task_id"] for entry in official} == {
        "dotProduct_optimize",
        "projection_bugfix",
        "residual_stream_deadlock",
    }
    for entry in official:
        task_dir = _REPO_ROOT / "tasks/official" / entry["task_id"]
        task_spec = (task_dir / "task.toml").read_text()
        kernel_line = next(
            line for line in task_spec.splitlines()
            if line.startswith("kernel_file = ")
        )
        kernel_name = kernel_line.split('"')[1]
        assert _sha256(task_dir / kernel_name) == entry["starter_sha256"]
        assert _sha256(task_dir / "reference" / kernel_name) == entry["reference_sha256"]
