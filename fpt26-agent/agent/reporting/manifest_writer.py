from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.core.candidate import Candidate, sha256_json
from agent.core.candidate_store import CandidateStore, RunLayout, write_json_once, write_text_once


class ManifestWriter:
    def __init__(self, output_root: str | Path) -> None:
        self.store = CandidateStore(output_root)

    def persist(self, result: Any) -> RunLayout:
        layout = self.store.create_run_layout(result.task_id)
        candidate = self.store.baseline_candidate(result.task_context, result.final_kernel)
        task_context_dict = result.task_context.to_dict()
        stage_results = [stage.to_dict() for stage in result.stage_results]
        transcript = result.budget.get("transcript", []) if isinstance(result.budget, dict) else []

        write_json_once(layout.task_context_path, task_context_dict)
        write_text_once(layout.baseline_kernel_path, result.final_kernel)
        write_json_once(layout.baseline_stage_results_path, stage_results)
        write_json_once(layout.transcript_path, transcript)
        write_json_once(layout.baseline_manifest_path, _candidate_manifest(candidate, layout, result, stage_results))
        write_text_once(layout.final_kernel_path, result.final_kernel)
        write_json_once(layout.run_manifest_path, _run_manifest(layout, candidate, result, stage_results))
        return layout


def _candidate_manifest(
    candidate: Candidate,
    layout: RunLayout,
    result: Any,
    stage_results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "candidate-manifest-v1",
        **candidate.to_dict(),
        "paths": {
            "candidate_dir": str(layout.baseline_dir),
            "kernel": str(layout.baseline_kernel_path),
            "stage_results": str(layout.baseline_stage_results_path),
        },
        "initial_condition": result.initial_condition.to_dict(),
        "stage_results": stage_results,
        "status": result.status,
    }


def _run_manifest(
    layout: RunLayout,
    candidate: Candidate,
    result: Any,
    stage_results: list[dict[str, Any]],
) -> dict[str, Any]:
    result_dict = result.to_dict()
    result_dict["run_directory"] = str(layout.run_dir)
    result_dict["run_manifest_path"] = str(layout.run_manifest_path)
    task_context_dict = result.task_context.to_dict()
    return {
        "schema_version": "agent-run-manifest-v1",
        "task_id": result.task_id,
        "run_id": layout.run_id,
        "status": result.status,
        "task_context_sha256": sha256_json(task_context_dict),
        "final_kernel_sha256": result.final_kernel_sha256,
        "baseline_candidate_id": candidate.candidate_id,
        "initial_condition": result.initial_condition.to_dict(),
        "stage_results": stage_results,
        "budget": result.budget,
        "agent_run_result": result_dict,
        "paths": {
            **layout.to_dict(),
            "transcript": str(layout.transcript_path),
        },
        "candidates": [
            {
                **candidate.to_dict(),
                "manifest_path": str(layout.baseline_manifest_path),
                "kernel_path": str(layout.baseline_kernel_path),
                "stage_results_path": str(layout.baseline_stage_results_path),
            }
        ],
        "transcript_paths": [str(layout.transcript_path)],
    }
