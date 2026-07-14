from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.core.candidate import Candidate, sha256_json, sha256_text
from agent.core.task_context import TaskContext


@dataclass(frozen=True)
class RunLayout:
    task_id: str
    run_id: str
    run_dir: Path
    task_context_path: Path
    run_manifest_path: Path
    transcript_dir: Path
    transcript_path: Path
    candidates_dir: Path
    baseline_dir: Path
    baseline_kernel_path: Path
    baseline_manifest_path: Path
    baseline_stage_results_path: Path
    final_dir: Path
    final_kernel_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "task_context_path": str(self.task_context_path),
            "run_manifest_path": str(self.run_manifest_path),
            "transcript_dir": str(self.transcript_dir),
            "transcript_path": str(self.transcript_path),
            "candidates_dir": str(self.candidates_dir),
            "baseline_dir": str(self.baseline_dir),
            "baseline_kernel_path": str(self.baseline_kernel_path),
            "baseline_manifest_path": str(self.baseline_manifest_path),
            "baseline_stage_results_path": str(self.baseline_stage_results_path),
            "final_dir": str(self.final_dir),
            "final_kernel_path": str(self.final_kernel_path),
        }


class CandidateStore:
    def __init__(self, output_root: str | Path) -> None:
        self.output_root = Path(output_root)

    def create_run_layout(self, task_id: str) -> RunLayout:
        task_root = self.output_root / task_id
        task_root.mkdir(parents=True, exist_ok=True)
        for index in range(100000):
            run_id = f"run_{index:03d}"
            run_dir = task_root / run_id
            try:
                run_dir.mkdir(parents=False, exist_ok=False)
            except FileExistsError:
                continue
            return _layout(task_id, run_id, run_dir)
        raise FileExistsError(f"could not allocate a unique run directory under {task_root}")

    def baseline_candidate(self, task_context: TaskContext, kernel_code: str) -> Candidate:
        return Candidate(
            candidate_id="c000_baseline",
            label="baseline",
            kernel_sha256=sha256_text(kernel_code),
            task_context_sha256=sha256_json(task_context.to_dict()),
            parent_candidate_id=None,
            action=None,
            lineage=[],
        )


def _layout(task_id: str, run_id: str, run_dir: Path) -> RunLayout:
    candidates_dir = run_dir / "candidates"
    baseline_dir = candidates_dir / "c000_baseline"
    transcript_dir = run_dir / "transcript"
    final_dir = run_dir / "final"
    for directory in (candidates_dir, baseline_dir, transcript_dir, final_dir):
        directory.mkdir(parents=True, exist_ok=False)
    return RunLayout(
        task_id=task_id,
        run_id=run_id,
        run_dir=run_dir,
        task_context_path=run_dir / "task_context.json",
        run_manifest_path=run_dir / "run_manifest.json",
        transcript_dir=transcript_dir,
        transcript_path=transcript_dir / "toolserver_transcript.json",
        candidates_dir=candidates_dir,
        baseline_dir=baseline_dir,
        baseline_kernel_path=baseline_dir / "kernel.cpp",
        baseline_manifest_path=baseline_dir / "manifest.json",
        baseline_stage_results_path=baseline_dir / "stage_results.json",
        final_dir=final_dir,
        final_kernel_path=final_dir / "kernel.cpp",
    )


def write_json_once(path: Path, data: dict[str, Any] | list[Any]) -> None:
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    write_text_once(path, text)


def write_text_once(path: Path, text: str) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {path}")
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as file_obj:
            file_obj.write(text)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
