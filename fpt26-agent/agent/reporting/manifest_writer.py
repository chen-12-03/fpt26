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
        baseline_kernel = getattr(result, "baseline_kernel", result.final_kernel)
        candidate = self.store.baseline_candidate(result.task_context, baseline_kernel)
        task_context_dict = result.task_context.to_dict()
        stage_results = [stage.to_dict() for stage in result.stage_results]
        baseline_stage_results = _baseline_stage_results(result, stage_results)
        transcript = result.budget.get("transcript", []) if isinstance(result.budget, dict) else []
        repair_attempts = [_attempt_dict(attempt) for attempt in getattr(result, "repair_attempts", [])]
        structural_attempts = [
            _attempt_dict(attempt) for attempt in getattr(result, "structural_repair_attempts", [])
        ]
        optimization_candidates = [_candidate_record_dict(candidate) for candidate in getattr(result, "optimization_candidates", [])]
        candidates = [candidate]

        write_json_once(layout.task_context_path, task_context_dict)
        write_text_once(layout.baseline_kernel_path, baseline_kernel)
        write_json_once(layout.baseline_stage_results_path, baseline_stage_results)
        write_json_once(layout.transcript_path, transcript)
        write_json_once(layout.baseline_cosim_diagnosis_path, _cosim_diagnosis_dict(result))
        write_json_once(layout.baseline_manifest_path, _candidate_manifest(candidate, layout, result, baseline_stage_results))
        for attempt in repair_attempts:
            repair_candidate = attempt.get("candidate")
            replacement_kernel = attempt.get("replacement_kernel")
            if not isinstance(repair_candidate, dict) or not isinstance(replacement_kernel, str):
                continue
            candidates.append(_candidate_from_dict(repair_candidate))
            _write_repair_candidate(layout, attempt, replacement_kernel)
        for attempt in structural_attempts:
            structural_candidate = attempt.get("candidate")
            replacement_kernel = attempt.get("replacement_kernel")
            if not isinstance(structural_candidate, dict) or not isinstance(replacement_kernel, str):
                continue
            candidates.append(_candidate_from_dict(structural_candidate))
            _write_structural_candidate(layout, attempt, replacement_kernel)
        for record in optimization_candidates:
            optimization_candidate = record.get("candidate")
            kernel_code = record.get("kernel_code")
            if not isinstance(optimization_candidate, dict) or not isinstance(kernel_code, str):
                continue
            candidates.append(_candidate_from_dict(optimization_candidate))
            _write_optimization_candidate(layout, record, kernel_code)
        _write_llm_audit(layout, getattr(result, "llm_usage", {}))
        _write_optimization_audit(layout, result, optimization_candidates)
        _write_cosim_audit(layout, result)
        _write_structural_repair_audit(layout, result, structural_attempts)
        write_text_once(layout.final_kernel_path, result.final_kernel)
        write_json_once(
            layout.run_manifest_path,
            _run_manifest(
                layout,
                candidates,
                result,
                stage_results,
                repair_attempts,
                structural_attempts,
                optimization_candidates,
            ),
        )
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
        "cosim_decision": _cosim_decision_dict(result),
        "cosim_diagnosis": _cosim_diagnosis_dict(result),
        "baseline_cosim_diagnosis": _baseline_cosim_diagnosis_dict(result),
        "final_cosim_diagnosis": _final_cosim_diagnosis_dict(result),
        "requires_structural_repair": getattr(result, "requires_structural_repair", False),
        "structural_repair_status": getattr(result, "structural_repair_status", None),
        "status": result.status,
    }


def _baseline_stage_results(result: Any, stage_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if getattr(result, "repair_attempts", []):
        return stage_results[:1]
    if getattr(result, "structural_repair_attempts", []):
        baseline: list[dict[str, Any]] = []
        for stage in stage_results:
            baseline.append(stage)
            if stage.get("stage") == "cosim":
                break
        return baseline
    if getattr(result, "optimization_candidates", []):
        baseline: list[dict[str, Any]] = []
        for stage in stage_results:
            baseline.append(stage)
            if stage.get("stage") == "synth":
                break
        return baseline
    return stage_results


def _run_manifest(
    layout: RunLayout,
    candidates: list[Candidate],
    result: Any,
    stage_results: list[dict[str, Any]],
    repair_attempts: list[dict[str, Any]],
    structural_attempts: list[dict[str, Any]],
    optimization_candidates: list[dict[str, Any]],
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
        "baseline_candidate_id": "c000_baseline",
        "selected_candidate_id": getattr(result, "selected_candidate_id", None),
        "repair_status": getattr(result, "repair_status", None),
        "repair_attempts": repair_attempts,
        "structural_repair_status": getattr(result, "structural_repair_status", None),
        "structural_repair_attempts": structural_attempts,
        "optimization_status": getattr(result, "optimization_status", None),
        "optimization_candidates": optimization_candidates,
        "baseline_metrics": getattr(result, "baseline_metrics", {}),
        "final_metrics": getattr(result, "final_metrics", {}),
        "selection_reason": getattr(result, "selection_reason", None),
        "cosim_decision": _cosim_decision_dict(result),
        "cosim_diagnosis": _cosim_diagnosis_dict(result),
        "baseline_cosim_diagnosis": _baseline_cosim_diagnosis_dict(result),
        "final_cosim_diagnosis": _final_cosim_diagnosis_dict(result),
        "requires_structural_repair": getattr(result, "requires_structural_repair", False),
        "llm_usage": getattr(result, "llm_usage", {}),
        "stop_reason": getattr(result, "stop_reason", None),
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
                **_candidate_paths(layout, candidate.candidate_id),
            }
            for candidate in candidates
        ],
        "transcript_paths": [str(layout.transcript_path)],
        "llm_paths": {
            "calls_jsonl": str(layout.llm_calls_path),
            "token_summary": str(layout.llm_summary_path),
        },
        "optimization_paths": {
            "search_summary": str(layout.optimization_summary_path),
            "pareto_candidates": str(layout.pareto_candidates_path),
        },
        "cosim_paths": {
            "decision": str(layout.cosim_decision_path),
            "diagnosis": str(layout.cosim_diagnosis_path),
            "artifact_index": str(layout.cosim_artifact_index_path),
            "baseline_candidate_diagnosis": str(layout.baseline_cosim_diagnosis_path),
        },
        "structural_repair_paths": {
            "summary": str(layout.structural_repair_summary_path),
            "attempts": str(layout.structural_repair_attempts_path),
        },
    }


def _candidate_from_dict(data: dict[str, Any]) -> Candidate:
    return Candidate(
        candidate_id=data["candidate_id"],
        label=data["label"],
        kernel_sha256=data["kernel_sha256"],
        task_context_sha256=data["task_context_sha256"],
        parent_candidate_id=data.get("parent_candidate_id"),
        action=data.get("action"),
        lineage=list(data.get("lineage", [])),
    )


def _candidate_paths(layout: RunLayout, candidate_id: str) -> dict[str, str]:
    if candidate_id == "c000_baseline":
        return {
            "manifest_path": str(layout.baseline_manifest_path),
            "kernel_path": str(layout.baseline_kernel_path),
            "stage_results_path": str(layout.baseline_stage_results_path),
            "cosim_diagnosis_path": str(layout.baseline_cosim_diagnosis_path),
        }
    candidate_dir = layout.candidates_dir / candidate_id
    return {
        "manifest_path": str(candidate_dir / "manifest.json"),
        "kernel_path": str(candidate_dir / "kernel.cpp"),
        "stage_results_path": str(candidate_dir / "stage_results.json"),
        "validation_path": str(candidate_dir / "validation.json"),
        "stream_analysis_path": str(candidate_dir / "stream_analysis.json"),
        "cosim_diagnosis_path": str(candidate_dir / "cosim_diagnosis.json"),
        "actions_path": str(candidate_dir / "actions.json"),
        "comparison_path": str(candidate_dir / "comparison.json"),
        "diff_path": str(candidate_dir / "diff.patch"),
    }


def _write_repair_candidate(layout: RunLayout, attempt: dict[str, Any], replacement_kernel: str) -> None:
    candidate = attempt["candidate"]
    candidate_id = candidate["candidate_id"]
    candidate_dir = layout.candidates_dir / candidate_id
    candidate_dir.mkdir(parents=False, exist_ok=False)
    write_text_once(candidate_dir / "kernel.cpp", replacement_kernel)
    write_json_once(candidate_dir / "validation.json", attempt.get("validation_result", {}))
    write_json_once(candidate_dir / "stage_results.json", attempt.get("stage_results", []))
    write_json_once(
        candidate_dir / "manifest.json",
        {
            "schema_version": "candidate-manifest-v1",
            **candidate,
            "diagnosis": attempt.get("diagnosis"),
            "changes": attempt.get("changes"),
            "confidence": attempt.get("confidence"),
            "prompt_sha256": attempt.get("prompt_sha256"),
            "llm_call_record": attempt.get("llm_call_record"),
            "validation_result": attempt.get("validation_result"),
            "stage_results": attempt.get("stage_results", []),
            "status": attempt.get("status"),
            "paths": _candidate_paths(layout, candidate_id),
        },
    )


def _write_structural_candidate(layout: RunLayout, attempt: dict[str, Any], replacement_kernel: str) -> None:
    candidate = attempt["candidate"]
    candidate_id = candidate["candidate_id"]
    candidate_dir = layout.candidates_dir / candidate_id
    candidate_dir.mkdir(parents=False, exist_ok=False)
    write_text_once(candidate_dir / "kernel.cpp", replacement_kernel)
    write_json_once(candidate_dir / "validation.json", attempt.get("validation_result", {}))
    write_json_once(candidate_dir / "stream_analysis.json", attempt.get("stream_analysis", {}))
    write_json_once(candidate_dir / "stage_results.json", attempt.get("stage_results", []))
    write_json_once(candidate_dir / "cosim_diagnosis.json", attempt.get("cosim_diagnosis"))
    write_text_once(candidate_dir / "diff.patch", attempt.get("diff_patch", ""))
    write_json_once(
        candidate_dir / "manifest.json",
        {
            "schema_version": "candidate-manifest-v1",
            **candidate,
            "diagnosis": attempt.get("diagnosis"),
            "repair_strategy": attempt.get("repair_strategy"),
            "affected_streams": attempt.get("affected_streams", []),
            "changes": attempt.get("changes", []),
            "confidence": attempt.get("confidence"),
            "prompt_sha256": attempt.get("prompt_sha256"),
            "llm_call_record": attempt.get("llm_call_record"),
            "validation_result": attempt.get("validation_result"),
            "stream_analysis": attempt.get("stream_analysis"),
            "stage_results": attempt.get("stage_results", []),
            "cosim_diagnosis": attempt.get("cosim_diagnosis"),
            "selection_status": attempt.get("selection_status"),
            "status": attempt.get("status"),
            "stop_reason": attempt.get("stop_reason"),
            "budget_before": attempt.get("budget_before"),
            "budget_after": attempt.get("budget_after"),
            "paths": _candidate_paths(layout, candidate_id),
        },
    )


def _write_optimization_candidate(layout: RunLayout, record: dict[str, Any], kernel_code: str) -> None:
    candidate = record["candidate"]
    candidate_id = candidate["candidate_id"]
    candidate_dir = layout.candidates_dir / candidate_id
    candidate_dir.mkdir(parents=False, exist_ok=False)
    write_text_once(candidate_dir / "kernel.cpp", kernel_code)
    write_json_once(candidate_dir / "validation.json", record.get("validation_result", {}))
    write_json_once(candidate_dir / "actions.json", record.get("actions", []))
    write_json_once(candidate_dir / "stage_results.json", record.get("stage_results", []))
    write_json_once(candidate_dir / "comparison.json", record.get("comparison_to_baseline", {}))
    write_text_once(candidate_dir / "diff.patch", record.get("diff_patch", ""))
    write_json_once(
        candidate_dir / "manifest.json",
        {
            "schema_version": "candidate-manifest-v1",
            **candidate,
            "actions": record.get("actions", []),
            "validation_result": record.get("validation_result"),
            "stage_results": record.get("stage_results", []),
            "metrics": record.get("metrics", {}),
            "constraint_checks": record.get("constraint_checks", {}),
            "comparison_to_baseline": record.get("comparison_to_baseline", {}),
            "selection_status": record.get("selection_status"),
            "status": record.get("status"),
            "stop_reason": record.get("stop_reason"),
            "paths": _candidate_paths(layout, candidate_id),
        },
    )


def _write_llm_audit(layout: RunLayout, llm_usage: dict[str, Any]) -> None:
    records = llm_usage.get("records", []) if isinstance(llm_usage, dict) else []
    summary = {key: value for key, value in llm_usage.items() if key != "records"} if isinstance(llm_usage, dict) else {}
    lines = [json_dumps(record) for record in records]
    write_text_once(layout.llm_calls_path, "\n".join(lines) + ("\n" if lines else ""))
    write_text_once(layout.llm_summary_path, json_dumps(summary, pretty=True))


def _write_optimization_audit(layout: RunLayout, result: Any, records: list[dict[str, Any]]) -> None:
    search_summary = {
        "schema_version": "optimization-search-v1",
        "optimization_status": getattr(result, "optimization_status", None),
        "selected_candidate_id": getattr(result, "selected_candidate_id", None),
        "selection_reason": getattr(result, "selection_reason", None),
        "baseline_metrics": getattr(result, "baseline_metrics", {}),
        "final_metrics": getattr(result, "final_metrics", {}),
        "candidate_count": len(records),
        "candidates": [
            {
                "candidate_id": (record.get("candidate") or {}).get("candidate_id"),
                "status": record.get("status"),
                "selection_status": record.get("selection_status"),
                "actions": record.get("actions", []),
            }
            for record in records
        ],
    }
    pareto = [
        {
            "candidate_id": (record.get("candidate") or {}).get("candidate_id"),
            "metrics": record.get("metrics", {}),
            "constraint_checks": record.get("constraint_checks", {}),
            "selection_status": record.get("selection_status"),
        }
        for record in records
        if record.get("status") == "synth_pass"
    ]
    write_json_once(layout.optimization_summary_path, search_summary)
    write_json_once(layout.pareto_candidates_path, pareto)


def _write_cosim_audit(layout: RunLayout, result: Any) -> None:
    decision = _cosim_decision_dict(result)
    diagnosis = _cosim_diagnosis_dict(result)
    artifacts = diagnosis.get("artifacts", {}) if isinstance(diagnosis, dict) else {}
    write_json_once(layout.cosim_decision_path, decision)
    write_json_once(layout.cosim_diagnosis_path, diagnosis)
    write_json_once(layout.cosim_artifact_index_path, artifacts)


def _write_structural_repair_audit(layout: RunLayout, result: Any, attempts: list[dict[str, Any]]) -> None:
    summary = {
        "schema_version": "structural-repair-summary-v1",
        "status": getattr(result, "structural_repair_status", None),
        "selected_candidate_id": getattr(result, "selected_candidate_id", None),
        "stop_reason": getattr(result, "stop_reason", None),
        "attempt_count": len(attempts),
        "baseline_cosim_diagnosis": _baseline_cosim_diagnosis_dict(result),
        "final_cosim_diagnosis": _final_cosim_diagnosis_dict(result),
        "attempts": [
            {
                "attempt_index": attempt.get("attempt_index"),
                "candidate_id": (attempt.get("candidate") or {}).get("candidate_id"),
                "status": attempt.get("status"),
                "selection_status": attempt.get("selection_status"),
                "stop_reason": attempt.get("stop_reason"),
            }
            for attempt in attempts
        ],
    }
    write_json_once(layout.structural_repair_summary_path, summary)
    write_json_once(layout.structural_repair_attempts_path, attempts)


def _cosim_decision_dict(result: Any) -> dict[str, Any] | None:
    decision = getattr(result, "cosim_decision", None)
    if decision is None:
        return None
    if hasattr(decision, "to_dict"):
        return decision.to_dict()
    if isinstance(decision, dict):
        return decision
    return None


def _cosim_diagnosis_dict(result: Any) -> dict[str, Any] | None:
    diagnosis = getattr(result, "cosim_diagnosis", None)
    if diagnosis is None:
        return None
    if hasattr(diagnosis, "to_dict"):
        return diagnosis.to_dict()
    if isinstance(diagnosis, dict):
        return diagnosis
    return None


def _baseline_cosim_diagnosis_dict(result: Any) -> dict[str, Any] | None:
    diagnosis = getattr(result, "baseline_cosim_diagnosis", None)
    if diagnosis is None:
        return None
    if hasattr(diagnosis, "to_dict"):
        return diagnosis.to_dict()
    if isinstance(diagnosis, dict):
        return diagnosis
    return None


def _final_cosim_diagnosis_dict(result: Any) -> dict[str, Any] | None:
    diagnosis = getattr(result, "final_cosim_diagnosis", None)
    if diagnosis is None:
        return None
    if hasattr(diagnosis, "to_dict"):
        return diagnosis.to_dict()
    if isinstance(diagnosis, dict):
        return diagnosis
    return None


def _attempt_dict(attempt: Any) -> dict[str, Any]:
    if hasattr(attempt, "to_dict"):
        return attempt.to_dict()
    if isinstance(attempt, dict):
        return attempt
    return {}


def _candidate_record_dict(candidate: Any) -> dict[str, Any]:
    if hasattr(candidate, "to_dict"):
        return candidate.to_dict()
    if isinstance(candidate, dict):
        return candidate
    return {}


def json_dumps(data: Any, *, pretty: bool = False) -> str:
    if pretty:
        return __import__("json").dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    return __import__("json").dumps(data, sort_keys=True, ensure_ascii=False)
