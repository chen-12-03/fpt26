#!/usr/bin/env python3
"""Prepare public-HLS tripcount patch smoke samples without editing corpus tasks."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from tools.import_public_hls_tasks import _add_tripcount_pragmas


DEFAULT_TASKS = [
    "amd_accel__host_xrt_host_memory_copy_buffer_xrt_src_krnl_vadd",
    "amd_accel__host_xrt_host_memory_copy_kernel_xrt_src_copy_kernel",
    "amd_accel__host_xrt_host_memory_copy_kernel_xrt_src_krnl_vadd",
]


def prepare_samples(
    task_root: Path,
    out_root: Path,
    task_ids: list[str],
    *,
    max_tripcount: int = 4096,
) -> dict[str, Any]:
    imported: list[dict[str, Any]] = []
    out_root.mkdir(parents=True, exist_ok=True)
    for task_id in task_ids:
        source_dir = _resolve_task_dir(task_root, task_id)
        spec = _read_spec(source_dir)
        kernel_name = _public_filename(spec, "kernel_file")
        dest_dir = out_root / task_id
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        shutil.copytree(
            source_dir,
            dest_dir,
            ignore=shutil.ignore_patterns("hidden", "reference"),
        )
        kernel_path = dest_dir / kernel_name
        original_text = kernel_path.read_text(encoding="utf-8")
        patched_text, inserted = _add_tripcount_pragmas(
            original_text, max_tripcount=max_tripcount
        )
        kernel_path.write_text(patched_text, encoding="utf-8")
        provenance = spec.get("provenance", {})
        if not isinstance(provenance, dict):
            provenance = {}
        imported.append(
            {
                "task_id": task_id,
                "source": provenance.get("source", task_id.split("__", 1)[0]),
                "source_path": provenance.get("source_path", ""),
                "top_function": spec.get("top"),
                "source_sha256": provenance.get("source_sha256", ""),
                "tripcount_pragmas_inserted": inserted,
                "tripcount_max": max_tripcount,
                "original_kernel_sha256": _sha256_text(original_text),
                "patched_kernel_sha256": _sha256_text(patched_text),
            }
        )
    return {
        "schema_version": 1,
        "purpose": "public_hls_tripcount_patch_sample",
        "task_root": str(task_root),
        "out_root": str(out_root),
        "imported_count": len(imported),
        "imported": imported,
    }


def _resolve_task_dir(task_root: Path, task_id: str) -> Path:
    candidates = [task_root / task_id, task_root / "generated" / task_id]
    for candidate in candidates:
        if (candidate / "task.toml").is_file():
            return candidate
    raise FileNotFoundError(f"task directory not found for {task_id}")


def _read_spec(task_dir: Path) -> dict[str, Any]:
    spec = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError(f"invalid task.toml: {task_dir}")
    return spec


def _public_filename(spec: dict[str, Any], key: str) -> str:
    value = spec.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty public filename")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe public filename for {key}: {value}")
    forbidden = {"hidden", "reference", "evaluator"} & {
        part.lower() for part in path.parts
    }
    if forbidden:
        raise ValueError(f"forbidden public filename component for {key}: {value}")
    return value


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, default=Path("tasks"))
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--task-id", action="append", dest="task_ids")
    parser.add_argument("--max-tripcount", type=int, default=4096)
    args = parser.parse_args()

    manifest = prepare_samples(
        args.task_root,
        args.out_root,
        args.task_ids or DEFAULT_TASKS,
        max_tripcount=args.max_tripcount,
    )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "manifest": str(args.manifest),
                "out_root": str(args.out_root),
                "imported_count": manifest["imported_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
