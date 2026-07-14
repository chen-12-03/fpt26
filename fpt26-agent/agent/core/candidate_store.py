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
    llm_dir: Path
    llm_calls_path: Path
    llm_summary_path: Path
    optimization_dir: Path
    optimization_summary_path: Path
    pareto_candidates_path: Path
    cosim_dir: Path
    cosim_decision_path: Path
    cosim_diagnosis_path: Path
    cosim_artifact_index_path: Path
    candidates_dir: Path
    baseline_dir: Path
    baseline_kernel_path: Path
    baseline_manifest_path: Path
    baseline_stage_results_path: Path
    baseline_cosim_diagnosis_path: Path
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
            "llm_dir": str(self.llm_dir),
            "llm_calls_path": str(self.llm_calls_path),
            "llm_summary_path": str(self.llm_summary_path),
            "optimization_dir": str(self.optimization_dir),
            "optimization_summary_path": str(self.optimization_summary_path),
            "pareto_candidates_path": str(self.pareto_candidates_path),
            "cosim_dir": str(self.cosim_dir),
            "cosim_decision_path": str(self.cosim_decision_path),
            "cosim_diagnosis_path": str(self.cosim_diagnosis_path),
            "cosim_artifact_index_path": str(self.cosim_artifact_index_path),
            "candidates_dir": str(self.candidates_dir),
            "baseline_dir": str(self.baseline_dir),
            "baseline_kernel_path": str(self.baseline_kernel_path),
            "baseline_manifest_path": str(self.baseline_manifest_path),
            "baseline_stage_results_path": str(self.baseline_stage_results_path),
            "baseline_cosim_diagnosis_path": str(self.baseline_cosim_diagnosis_path),
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

    def repair_candidate(
        self,
        task_context: TaskContext,
        kernel_code: str,
        *,
        attempt_index: int,
        parent_candidate: Candidate,
        action: dict[str, Any],
    ) -> Candidate:
        if attempt_index <= 0:
            raise ValueError("attempt_index must be positive")
        candidate_id = f"c{attempt_index:03d}_repair_llm_{attempt_index:02d}"
        lineage = [*parent_candidate.lineage, parent_candidate.candidate_id]
        return Candidate(
            candidate_id=candidate_id,
            label=f"repair_llm_{attempt_index:02d}",
            kernel_sha256=sha256_text(kernel_code),
            task_context_sha256=sha256_json(task_context.to_dict()),
            parent_candidate_id=parent_candidate.candidate_id,
            action=action,
            lineage=lineage,
        )

    def optimization_candidate(
        self,
        task_context: TaskContext,
        kernel_code: str,
        *,
        attempt_index: int,
        parent_candidate: Candidate,
        action: dict[str, Any],
    ) -> Candidate:
        if attempt_index <= 0:
            raise ValueError("attempt_index must be positive")
        action_type = action.get("action_type")
        label = {
            "pipeline_loop": "pipeline",
            "unroll_loop": "unroll",
            "array_partition": "partition",
        }.get(action_type, "opt")
        candidate_id = f"c{attempt_index:03d}_{label}_{attempt_index:02d}"
        lineage = [*parent_candidate.lineage, parent_candidate.candidate_id]
        return Candidate(
            candidate_id=candidate_id,
            label=f"{label}_{attempt_index:02d}",
            kernel_sha256=sha256_text(kernel_code),
            task_context_sha256=sha256_json(task_context.to_dict()),
            parent_candidate_id=parent_candidate.candidate_id,
            action={
                "type": "deterministic_optimization",
                "actions": [action],
            },
            lineage=lineage,
        )


def _layout(task_id: str, run_id: str, run_dir: Path) -> RunLayout:
    candidates_dir = run_dir / "candidates"
    baseline_dir = candidates_dir / "c000_baseline"
    transcript_dir = run_dir / "transcript"
    llm_dir = run_dir / "llm"
    optimization_dir = run_dir / "optimization"
    cosim_dir = run_dir / "cosim"
    final_dir = run_dir / "final"
    for directory in (candidates_dir, baseline_dir, transcript_dir, llm_dir, optimization_dir, cosim_dir, final_dir):
        directory.mkdir(parents=True, exist_ok=False)
    return RunLayout(
        task_id=task_id,
        run_id=run_id,
        run_dir=run_dir,
        task_context_path=run_dir / "task_context.json",
        run_manifest_path=run_dir / "run_manifest.json",
        transcript_dir=transcript_dir,
        transcript_path=transcript_dir / "toolserver_transcript.json",
        llm_dir=llm_dir,
        llm_calls_path=llm_dir / "calls.jsonl",
        llm_summary_path=llm_dir / "token_summary.json",
        optimization_dir=optimization_dir,
        optimization_summary_path=optimization_dir / "search_summary.json",
        pareto_candidates_path=optimization_dir / "pareto_candidates.json",
        cosim_dir=cosim_dir,
        cosim_decision_path=cosim_dir / "decision.json",
        cosim_diagnosis_path=cosim_dir / "diagnosis.json",
        cosim_artifact_index_path=cosim_dir / "artifact_index.json",
        candidates_dir=candidates_dir,
        baseline_dir=baseline_dir,
        baseline_kernel_path=baseline_dir / "kernel.cpp",
        baseline_manifest_path=baseline_dir / "manifest.json",
        baseline_stage_results_path=baseline_dir / "stage_results.json",
        baseline_cosim_diagnosis_path=baseline_dir / "cosim_diagnosis.json",
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
