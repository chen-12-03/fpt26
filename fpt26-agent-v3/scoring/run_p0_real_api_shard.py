"""Run one fresh P0 shard with isolated submission and evaluator roles.

Every task uses a new attempt directory. A resumed shard skips only records
already committed to ``shard_summary.json``; an interrupted task receives a
new attempt directory, so stale kernels, XML reports, or tool workspaces are
never reused.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from llm4hls.llm import _default_thinking_mode, chat_completions_url

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


TERMINAL_STATUSES = {
    "completed",
    "failed",
    "budget_exceeded",
    "infrastructure_error",
}

EXPECTED_GENERATED_TASK_COUNT = 197
EXPECTED_OFFICIAL_TASK_COUNT = 3
EXPECTED_TASK_COUNT = EXPECTED_GENERATED_TASK_COUNT + EXPECTED_OFFICIAL_TASK_COUNT

TRACK_A_150_ROOT_NAMES = {"track_a_150", "track_a_150_v2"}
TRACK_A_150_RELEASE_ROOT_NAMES = {"public_agent", "evaluator_private"}

REAL_API_CLIENTS = {
    "custom": "OpenAICompatClient",
    "openrouter": "OpenRouterClient",
}

TRACK_A_150_TOOL_TIMEOUT_DEFAULTS_S = {
    "csim": 30.0,
    "synth": 180.0,
    "cosim": 240.0,
}

TOOL_TIMEOUT_ENV = {
    "csim": "LLM4HLS_CSIM_TIMEOUT_S",
    "synth": "LLM4HLS_SYNTH_TIMEOUT_S",
    "cosim": "LLM4HLS_COSIM_TIMEOUT_S",
}


def _is_track_a_150_root(task_root: Path) -> bool:
    if task_root.name in TRACK_A_150_ROOT_NAMES:
        return True
    return (
        task_root.name in TRACK_A_150_RELEASE_ROOT_NAMES
        and task_root.parent.name.startswith("track_a_150")
    )


def resolve_tool_timeout_policy(task_root: Path) -> dict[str, Any] | None:
    """Resolve the corpus-scoped tool timeout policy for one shard.

    The tighter defaults are intentionally limited to the frozen Track-A 150
    corpus. Explicit environment values remain an escape hatch for controlled
    experiments, and the resolved values are recorded in the shard summary.
    """

    if not _is_track_a_150_root(task_root):
        return None

    values_s: dict[str, float] = {}
    env_overrides: dict[str, str] = {}
    explicit_overrides: list[str] = []
    for tool, default_s in TRACK_A_150_TOOL_TIMEOUT_DEFAULTS_S.items():
        env_name = TOOL_TIMEOUT_ENV[tool]
        raw_value = os.environ.get(env_name)
        try:
            value_s = default_s if raw_value is None else float(raw_value)
        except ValueError as exc:
            raise RuntimeError(
                f"{env_name} must be a positive number, got {raw_value!r}"
            ) from exc
        if not math.isfinite(value_s) or value_s <= 0:
            raise RuntimeError(
                f"{env_name} must be positive, got {value_s!r}"
            )
        values_s[tool] = value_s
        env_overrides[env_name] = str(value_s)
        if raw_value is not None:
            explicit_overrides.append(env_name)

    return {
        "scope": "track_a_150",
        "task_root_kind": task_root.name,
        "source": (
            "environment_override"
            if explicit_overrides
            else "track_a_150_runner_defaults"
        ),
        "values_s": values_s,
        "env_overrides": env_overrides,
        "explicit_override_names": sorted(explicit_overrides),
    }


def resolve_llm_run_contract(
    backend: str,
    model: str | None,
) -> dict[str, Any]:
    """Resolve the immutable, non-secret LLM contract for one shard."""

    if backend not in REAL_API_CLIENTS:
        raise RuntimeError(f"unsupported real API backend: {backend!r}")
    model_env = "LLM4HLS_MODEL" if backend == "openrouter" else "FPT26_LLM_MODEL"
    resolved_model = (model or os.environ.get(model_env, "")).strip()
    if not resolved_model:
        raise RuntimeError(
            f"{backend} model missing; pass --model or set {model_env}"
        )

    contract: dict[str, Any] = {
        "backend": backend,
        "expected_client": REAL_API_CLIENTS[backend],
        "model": resolved_model,
        "temperature": float(
            os.environ.get("FPT26_LLM_TEMPERATURE") or "0.7"
        ),
        "max_tokens": int(
            os.environ.get("FPT26_LLM_MAX_TOKENS") or "4096"
        ),
        "timeout_s": float(
            os.environ.get("FPT26_LLM_TIMEOUT_SECONDS") or "180"
        ),
        "max_retries": int(
            os.environ.get("FPT26_LLM_MAX_RETRIES") or "2"
        ),
    }
    if backend == "custom":
        base_url = os.environ.get("FPT26_LLM_BASE_URL", "").strip()
        thinking = _default_thinking_mode(
            chat_completions_url(base_url), resolved_model
        )
        contract["thinking"] = thinking
    if backend == "openrouter":
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise RuntimeError(
                "OpenRouter credential missing; set OPENROUTER_API_KEY"
            )
        base_url = os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).strip()
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or parsed.hostname != "openrouter.ai":
            raise RuntimeError(
                "OPENROUTER_BASE_URL must use https://openrouter.ai"
            )
        contract["provider"] = "openrouter"
        contract["api_origin"] = "https://openrouter.ai"
    return contract


def discover_tasks(
    task_root: Path,
    *,
    excluded_task_ids: set[str] | None = None,
) -> list[Path]:
    direct_manifests = sorted(task_root.glob("*/task.toml"))
    if direct_manifests:
        manifests = direct_manifests
        expected_count = 150 if _is_track_a_150_root(task_root) else len(manifests)
    else:
        manifests = sorted((task_root / "generated").glob("*/task.toml"))
        manifests += sorted((task_root / "official").glob("*/task.toml"))
        expected_count = EXPECTED_TASK_COUNT
    tasks = [manifest.parent.resolve() for manifest in manifests]
    if (
        len(tasks) != expected_count
        or len({task.name for task in tasks}) != expected_count
    ):
        raise RuntimeError(
            f"expected {expected_count} unique tasks, found {len(tasks)}"
        )
    if excluded_task_ids:
        available = {task.name for task in tasks}
        unknown = sorted(excluded_task_ids - available)
        if unknown:
            raise RuntimeError(
                f"excluded tasks are outside the corpus: {unknown}"
            )
        tasks = [task for task in tasks if task.name not in excluded_task_ids]
    return tasks


def _public_task_identity(task_dir: Path) -> dict[str, Any]:
    """Return the public contract and file hashes used to pair split roots."""

    spec = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    task_id = str(spec.get("task_id") or "")
    if not task_id or task_id != task_dir.name:
        raise RuntimeError(
            f"{task_dir}: task_id {task_id!r} does not match directory name"
        )
    declared_public_files = [
        str(spec["kernel_file"]),
        str(spec["public_tb"]),
        *[str(name) for name in spec.get("header_files", [])],
    ]
    public_files = sorted(
        set(declared_public_files)
        | {
            path.name
            for path in task_dir.iterdir()
            if path.is_file() and path.name not in {"task.toml", "description.md"}
        }
    )
    missing = [name for name in public_files if not (task_dir / name).is_file()]
    if missing:
        raise RuntimeError(f"{task_dir}: missing public files: {missing}")
    return {
        "task_id": task_id,
        "task_type": spec.get("task_type"),
        "difficulty": spec.get("difficulty"),
        "top": spec.get("top"),
        "kernel_file": spec.get("kernel_file"),
        "header_files": spec.get("header_files", []),
        "public_tb": spec.get("public_tb"),
        "budget": spec.get("budget"),
        "requires_cosim": spec.get("requires_cosim"),
        "initial_condition": spec.get("initial_condition"),
        "target": spec.get("target"),
        "file_sha256": {
            name: _sha256(task_dir / name) for name in sorted(set(public_files))
        },
    }


def pair_task_roots(
    submission_task_root: Path,
    evaluator_task_root: Path,
    *,
    excluded_task_ids: set[str] | None = None,
) -> list[tuple[Path, Path]]:
    """Pair physically separated public and private tasks, failing closed."""

    submission_tasks = discover_tasks(
        submission_task_root, excluded_task_ids=excluded_task_ids
    )
    evaluator_tasks = discover_tasks(
        evaluator_task_root, excluded_task_ids=excluded_task_ids
    )
    submission_by_id = {task.name: task for task in submission_tasks}
    evaluator_by_id = {task.name: task for task in evaluator_tasks}
    if submission_by_id.keys() != evaluator_by_id.keys():
        missing_submission = sorted(evaluator_by_id.keys() - submission_by_id.keys())
        missing_evaluator = sorted(submission_by_id.keys() - evaluator_by_id.keys())
        raise RuntimeError(
            "split task roots have different task IDs: "
            f"missing_submission={missing_submission}, "
            f"missing_evaluator={missing_evaluator}"
        )
    pairs = []
    for task_id in sorted(evaluator_by_id):
        submission_task = submission_by_id[task_id]
        evaluator_task = evaluator_by_id[task_id]
        if submission_task.resolve() != evaluator_task.resolve():
            forbidden_public = [
                name
                for name in ("hidden", "reference")
                if (submission_task / name).exists()
            ]
            if forbidden_public:
                raise RuntimeError(
                    f"{task_id}: submission root contains evaluator-only paths: "
                    f"{forbidden_public}"
                )
            missing_private = [
                name
                for name in ("hidden", "reference")
                if not (evaluator_task / name).is_dir()
            ]
            if missing_private:
                raise RuntimeError(
                    f"{task_id}: evaluator root is missing private paths: "
                    f"{missing_private}"
                )
            submission_identity = _public_task_identity(submission_task)
            evaluator_identity = _public_task_identity(evaluator_task)
            if submission_identity != evaluator_identity:
                raise RuntimeError(
                    f"{task_id}: public task contract differs between "
                    "submission and evaluator roots"
                )
        pairs.append((submission_task, evaluator_task))
    return pairs


def load_excluded_task_ids(path: Path) -> set[str]:
    """Load an explicit quarantine/exclusion task-id set from JSON."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    values: Any
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, dict):
        values = (
            raw.get("exclude_task_ids")
            or raw.get("metric_incomplete_task_ids")
            or ((raw.get("scoreable_gate") or {}).get(
                "metric_incomplete_task_ids"
            ))
            or (
                (
                    (raw.get("full199_failures") or {}).get(
                        "public_hls_metric_completeness"
                    )
                    or {}
                ).get("metric_incomplete_task_ids")
            )
        )
    else:
        values = None
    if not isinstance(values, list) or not all(
        isinstance(item, str) for item in values
    ):
        raise RuntimeError(
            f"{path}: expected a JSON list or an object containing task IDs"
        )
    task_ids = {item.strip() for item in values if item.strip()}
    if len(task_ids) != len([item for item in values if item.strip()]):
        raise RuntimeError(f"{path}: duplicate excluded task IDs")
    return task_ids


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execution_source_snapshot(root: Path | None = None) -> dict[str, Any]:
    """Hash the execution/scoring sources used by one long-running shard."""

    project_root = (
        root.resolve()
        if root is not None
        else Path(__file__).resolve().parents[1]
    )
    paths = sorted((project_root / "agent").rglob("*.py"))
    paths.extend(
        sorted((project_root / "agent" / "knowledge_assets").rglob("*.json"))
    )
    paths.extend(
        project_root / relative
        for relative in (
            "Dockerfile",
            "test_all.sh",
            "run-p0-official-fresh.sh",
            "scoring/scoring_v3.py",
            "scoring/profiles.py",
            "scoring/run_p0_real_api_shard.py",
            "scoring/snapshot_execution_source.py",
            "scoring/reconcile_p0_evaluators.py",
            "scoring/audit_p0_acceptance.py",
            "scoring/audit_p0_official.py",
        )
    )
    entries = {
        str(path.relative_to(project_root)): _sha256(path)
        for path in sorted(set(paths))
        if path.is_file()
    }
    payload = "\n".join(
        f"{relative}:{digest}"
        for relative, digest in sorted(entries.items())
    )
    return {
        "root": str(project_root),
        "file_count": len(entries),
        "tree_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "files": entries,
    }


def _load_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"missing run report: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") not in TERMINAL_STATUSES:
        raise RuntimeError(f"non-canonical status: {report.get('status')!r}")
    return report


def _ok_gate(report: dict[str, Any], name: str) -> bool:
    gate = (report.get("gates") or {}).get(name)
    return isinstance(gate, dict) and gate.get("ok") is True


def _toolchain_gate_errors(toolchain: dict[str, Any]) -> list[str]:
    """Part/version gate violations for one report.

    The pinned part is proven by the ``set_part`` line the Vitis driver echoes
    into its log.  That line is absent when no tool call reached the driver —
    an absence of evidence, not evidence of the wrong part, and the same rule
    ``version_gate_ok`` already follows.  A part that *was* observed and
    differs is a real violation.
    """
    errors: list[str] = []
    if toolchain.get("version_gate_ok") is not True:
        errors.append("vitis_2025_2_gate_failed")
    observed = {
        str(part) for part in (toolchain.get("observed_parts") or []) if part
    }
    if observed and observed != {str(toolchain.get("required_part"))}:
        errors.append("u55c_part_gate_failed")
    return errors


def _api_accounting_errors(report: dict[str, Any]) -> list[str]:
    """Separate "the API failed" from "the usage numbers do not add up"."""
    errors: list[str] = []
    llm = report.get("llm") or {}
    usage = llm.get("token_usage") or {}
    failed = usage.get("failed_request_count")
    if isinstance(failed, int) and failed > 0:
        # An infrastructure fault, reported on its own so the retry reasons in
        # ``llm.failures`` can be read next to it.
        errors.append("api_requests_failed")

    request_count = usage.get("request_count")
    response_count = usage.get("response_count")
    consistent = (
        all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (request_count, response_count, failed)
        )
        and failed == request_count - response_count
    )
    if (
        usage.get("complete") is not True
        or not consistent
        or usage.get("unreported_response_count") != 0
        or usage.get("total_tokens")
        != usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
    ):
        errors.append("real_api_usage_incomplete")
    elif (
        report.get("status") == "completed"
        and isinstance(request_count, int)
        and request_count < 1
    ):
        errors.append("completed_auto_run_without_api_request")
    return errors


def validate_submission(
    report: dict[str, Any],
    task_id: str,
    *,
    expected_client: str = "OpenAICompatClient",
    expected_model: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if report.get("task_id") != task_id:
        errors.append("task_id_mismatch")
    if report.get("run_role") != "submission":
        errors.append("submission_role_missing")
    if report.get("mode") != "auto":
        errors.append("auto_mode_missing")

    preflight = report.get("task_preflight") or {}
    public_files = preflight.get("public_files_read") or []
    forbidden_names = {"hidden", "reference"}
    if preflight.get("forbidden_artifact_accesses") != 0:
        errors.append("forbidden_artifact_access_recorded")
    for value in public_files:
        parts = {part.lower() for part in PurePosixPath(str(value)).parts}
        if parts & forbidden_names:
            errors.append("hidden_or_reference_in_public_files")
            break

    grading_results = (
        (report.get("execution_trace") or {}).get("grading_results") or []
    )
    if grading_results:
        errors.append("submission_contains_evaluator_results")
    if (report.get("grading") or {}).get("source") is not None:
        errors.append("submission_claims_grading_source")

    compliance = report.get("model_compliance") or {}
    if compliance.get("compliance_proven") is not True:
        errors.append("model_compliance_unproven")
    llm = report.get("llm") or {}
    usage = llm.get("token_usage") or {}
    if llm.get("client") != expected_client:
        errors.append(
            "real_openrouter_api_client_missing"
            if expected_client == "OpenRouterClient"
            else "real_custom_api_client_missing"
        )
    if expected_model is not None and llm.get("model") != expected_model:
        errors.append("llm_model_mismatch")
    errors.extend(_api_accounting_errors(report))
    errors.extend(_toolchain_gate_errors(report.get("toolchain") or {}))

    if report.get("status") == "completed":
        if not _ok_gate(report, "interface"):
            errors.append("interface_gate_failed")
        if not _ok_gate(report, "frequency_100mhz"):
            errors.append("frequency_gate_failed")
        if not _ok_gate(report, "resource_capacity"):
            errors.append("resource_gate_failed")
        if (report.get("gates") or {}).get("public_acceptance", {}).get(
            "ok"
        ) is not True:
            errors.append("public_acceptance_failed")
        if report.get("cosim_ok") is not None and not _ok_gate(
            report, "required_cosim"
        ):
            errors.append("required_cosim_gate_failed")
        if (report.get("final_artifact") or {}).get(
            "fully_verified"
        ) is not True:
            errors.append("final_artifact_not_fully_verified")
    return errors


def validate_evaluator(
    report: dict[str, Any],
    task_id: str,
    *,
    official_task: bool,
    expected_grading_source: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if report.get("task_id") != task_id:
        errors.append("task_id_mismatch")
    if report.get("run_role") != "evaluator":
        errors.append("evaluator_role_missing")
    if report.get("llm") is not None:
        errors.append("evaluator_unexpected_llm")

    grading = report.get("grading") or {}
    expected_source = (
        expected_grading_source
        if expected_grading_source is not None
        else "public_fallback"
        if official_task
        else "hidden"
    )
    if grading.get("source") != expected_source:
        errors.append(
            f"grading_source_{grading.get('source')}_expected_{expected_source}"
        )
    if expected_source == "public_fallback":
        if grading.get("is_fallback") is not True:
            errors.append("public_fallback_not_labelled")
    elif grading.get("is_fallback") is True:
        errors.append("generated_hidden_grading_mislabelled_fallback")

    # A stage that ran and failed is the evaluated candidate's outcome, not an
    # audit fault; a stage that is *absent* while its prerequisites passed is a
    # missing record.  Only the latter is an error here.
    trace = (report.get("execution_trace") or {}).get(
        "grading_results"
    ) or []
    stages = {item.get("stage"): item for item in trace}
    # hidden_csim always runs first when the evaluator grades; if it is
    # absent the grading record itself is incomplete.
    if "hidden_csim" not in stages:
        errors.append("hidden_csim_missing")
    # candidate_synth runs only after hidden_csim passed: a candidate whose
    # hidden tests fail is never synthesized, and that is the candidate's
    # outcome, not a missing record.
    csim_passed = stages.get("hidden_csim", {}).get("ok") is True
    if csim_passed and "candidate_synth" not in stages:
        errors.append("candidate_synth_missing")
    if report.get("cosim_ok") is not None:
        prerequisites_passed = (
            csim_passed
            and stages.get("candidate_synth", {}).get("ok") is True
        )
        if prerequisites_passed and "hidden_cosim" not in stages:
            errors.append("hidden_cosim_missing")

    errors.extend(_toolchain_gate_errors(report.get("toolchain") or {}))
    if report.get("status") == "completed":
        if not _ok_gate(report, "interface"):
            errors.append("interface_gate_failed")
        if not _ok_gate(report, "frequency_100mhz"):
            errors.append("frequency_gate_failed")
        if not _ok_gate(report, "resource_capacity"):
            errors.append("resource_gate_failed")
        if (report.get("gates") or {}).get("evaluator_acceptance", {}).get(
            "ok"
        ) is not True:
            errors.append("evaluator_acceptance_failed")
    return errors


def classify_outcome(
    submission: dict[str, Any] | None,
    evaluator: dict[str, Any] | None,
    launcher_error: str,
) -> str:
    if launcher_error:
        return "infrastructure_error"
    if submission is None:
        return "infrastructure_error"
    submission_status = submission.get("status")
    if submission_status != "completed":
        return str(submission_status)
    if evaluator is None:
        return "infrastructure_error"
    evaluator_status = evaluator.get("status")
    if evaluator_status == "completed":
        return "completed"
    reason = evaluator.get("stop_reason")
    if reason == "no_valid_anchor":
        return "no_valid_anchor"
    return str(evaluator_status)


def _run(
    command: list[str],
    log_path: Path,
    timeout_s: float,
    env_overrides: dict[str, str] | None = None,
) -> tuple[int | None, str, float]:
    started = time.monotonic()
    process_env = os.environ.copy()
    if env_overrides:
        process_env.update(env_overrides)
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_s,
            check=False,
            env=process_env,
        )
        log_path.write_text(completed.stdout, encoding="utf-8")
        return completed.returncode, "", time.monotonic() - started
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        log_path.write_text(
            output + f"\nLAUNCHER TIMEOUT AFTER {timeout_s}s\n",
            encoding="utf-8",
        )
        return None, f"launcher_timeout_after_{timeout_s}s", (
            time.monotonic() - started
        )


def _next_attempt(task_root: Path) -> Path:
    existing = sorted(task_root.glob("attempt_*"))
    attempt = len(existing) + 1
    path = task_root / f"attempt_{attempt:03d}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def build_evaluator_command(
    *,
    task_dir: Path,
    final_kernel: Path,
    submission_evidence: Path,
    output_root: Path,
) -> list[str]:
    """Build the formal evaluator command with its mandatory evidence link."""
    return [
        sys.executable,
        "-m",
        "agent.main",
        "--task",
        str(task_dir),
        "--run-role",
        "evaluator",
        "--final-kernel",
        str(final_kernel),
        "--submission-evidence",
        str(submission_evidence),
        "--output-root",
        str(output_root),
        "--quiet",
    ]


def build_submission_command(
    *,
    task_dir: Path,
    backend: str,
    output_root: Path,
    competition: bool,
) -> list[str]:
    """Build the submission command and preserve the requested search mode."""

    command = [
        sys.executable,
        "-m",
        "agent.main",
        "--task",
        str(task_dir),
        "--mode",
        "auto",
        "--run-role",
        "submission",
        "--backend",
        backend,
        "--output-root",
        str(output_root),
        "--quiet",
    ]
    if competition:
        command.append("--competition")
    return command


def submission_requires_evaluator(
    submission: dict[str, Any] | None,
    final_kernel: Path | None,
) -> bool:
    """Only a completed submission can become formal evaluator input."""

    return bool(
        submission is not None
        and submission.get("status") == "completed"
        and final_kernel is not None
        and final_kernel.is_file()
    )


def _summary(
    *,
    shard_index: int,
    shard_count: int,
    selected_count: int,
    started: float,
    records: list[dict[str, Any]],
    source_start: dict[str, Any],
    source_current: dict[str, Any],
    quarantine: dict[str, Any] | None = None,
    llm_run_contract: dict[str, Any] | None = None,
    tool_timeout_policy: dict[str, Any] | None = None,
    submission_task_root: Path | None = None,
    evaluator_task_root: Path | None = None,
) -> dict[str, Any]:
    outcomes: dict[str, int] = {}
    for record in records:
        outcome = record["outcome"]
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    summary = {
        "schema_version": 2,
        "purpose": "p0_split_role_real_api_vitis_acceptance",
        "freshness_policy": (
            "new attempt directory per task; resume never reuses an "
            "interrupted attempt"
        ),
        "shard_index": shard_index,
        "shard_count": shard_count,
        "selected_task_count": selected_count,
        "completed_record_count": len(records),
        "outcome_counts": dict(sorted(outcomes.items())),
        "audit_error_record_count": sum(
            bool(record.get("audit_errors")) for record in records
        ),
        "execution_source": {
            "start": source_start,
            "current": source_current,
            "stable": (
                source_start.get("tree_sha256")
                == source_current.get("tree_sha256")
            ),
        },
        "elapsed_s": time.monotonic() - started,
        "records": records,
    }
    if llm_run_contract is not None:
        summary["llm_run_contract"] = llm_run_contract
    if tool_timeout_policy is not None:
        summary["tool_timeout_policy"] = tool_timeout_policy
    if submission_task_root is not None and evaluator_task_root is not None:
        summary["task_roots"] = {
            "submission": str(submission_task_root),
            "evaluator": str(evaluator_task_root),
            "physically_separated": (
                submission_task_root.resolve() != evaluator_task_root.resolve()
            ),
        }
    if quarantine is not None:
        summary["task_quarantine"] = quarantine
    return summary


def _write_summary(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run_shard(
    *,
    task_root: Path,
    submission_task_root: Path | None = None,
    output_root: Path,
    shard_index: int,
    shard_count: int,
    timeout_s: float,
    resume: bool,
    requested_task_ids: set[str] | None = None,
    excluded_task_ids: set[str] | None = None,
    excluded_task_source: str | None = None,
    backend: str = "custom",
    model: str | None = None,
    competition: bool = False,
) -> dict[str, Any]:
    llm_run_contract = {
        **resolve_llm_run_contract(backend, model),
        "competition": bool(competition),
    }
    model_env = "LLM4HLS_MODEL" if backend == "openrouter" else "FPT26_LLM_MODEL"
    submission_env = {model_env: llm_run_contract["model"]}
    evaluator_task_root = task_root
    submission_task_root = submission_task_root or evaluator_task_root
    tool_timeout_policy = resolve_tool_timeout_policy(evaluator_task_root)
    tool_timeout_env = (
        dict(tool_timeout_policy["env_overrides"])
        if tool_timeout_policy is not None
        else {}
    )
    submission_env.update(tool_timeout_env)
    task_pairs = pair_task_roots(
        submission_task_root,
        evaluator_task_root,
        excluded_task_ids=excluded_task_ids,
    )
    quarantine = None
    if excluded_task_ids:
        quarantine = {
            "enabled": True,
            "source": excluded_task_source or "explicit",
            "excluded_task_count": len(excluded_task_ids),
            "excluded_task_ids": sorted(excluded_task_ids),
            "effective_task_count": len(task_pairs),
            "original_expected_task_count": (
                len(task_pairs) + len(excluded_task_ids)
            ),
        }
    if requested_task_ids is not None:
        available = {evaluator_task.name for _, evaluator_task in task_pairs}
        unknown = sorted(requested_task_ids - available)
        if unknown:
            raise RuntimeError(
                f"requested tasks are outside the corpus: {unknown}"
            )
        task_pairs = [
            pair for pair in task_pairs if pair[1].name in requested_task_ids
        ]
    selected = [
        pair
        for index, pair in enumerate(task_pairs)
        if index % shard_count == shard_index
    ]
    summary_path = output_root / "shard_summary.json"
    source_start = execution_source_snapshot()
    records: list[dict[str, Any]] = []
    shard_started = time.monotonic()
    if output_root.exists():
        if not resume or not summary_path.is_file():
            raise RuntimeError(f"refusing to reuse output root: {output_root}")
        previous = json.loads(summary_path.read_text(encoding="utf-8"))
        if previous.get("llm_run_contract") != llm_run_contract:
            raise RuntimeError(
                "refusing to resume shard after LLM run contract drift"
            )
        if previous.get("tool_timeout_policy") != tool_timeout_policy:
            raise RuntimeError(
                "refusing to resume shard after tool timeout policy drift"
            )
        previous_roots = previous.get("task_roots") or {}
        expected_roots = {
            "submission": str(submission_task_root),
            "evaluator": str(evaluator_task_root),
            "physically_separated": (
                submission_task_root.resolve() != evaluator_task_root.resolve()
            ),
        }
        if previous_roots != expected_roots:
            raise RuntimeError(
                "refusing to resume shard after submission/evaluator task-root drift"
            )
        previous_source = (
            (previous.get("execution_source") or {}).get("start") or {}
        )
        if (
            previous_source.get("tree_sha256")
            != source_start.get("tree_sha256")
        ):
            raise RuntimeError(
                "refusing to resume shard after execution source drift"
            )
        records = list(previous.get("records") or [])
    else:
        output_root.mkdir(parents=True)
        _write_summary(
            summary_path,
            _summary(
                shard_index=shard_index,
                shard_count=shard_count,
                selected_count=len(selected),
                started=shard_started,
                records=[],
                source_start=source_start,
                source_current=source_start,
                quarantine=quarantine,
                llm_run_contract=llm_run_contract,
                tool_timeout_policy=tool_timeout_policy,
                submission_task_root=submission_task_root,
                evaluator_task_root=evaluator_task_root,
            ),
        )
    selected_ids = {evaluator_task.name for _, evaluator_task in selected}
    committed = {record["task_id"] for record in records}
    for checkpoint in sorted(
        (output_root / "tasks").glob("*/checkpoint.json")
    ):
        record = json.loads(checkpoint.read_text(encoding="utf-8"))
        task_id = str(record.get("task_id") or "")
        if task_id in selected_ids and task_id not in committed:
            records.append(record)
            committed.add(task_id)
    done = {record["task_id"] for record in records}
    _write_summary(
        summary_path,
        _summary(
            shard_index=shard_index,
            shard_count=shard_count,
            selected_count=len(selected),
            started=shard_started,
            records=records,
            source_start=source_start,
            source_current=source_start,
            quarantine=quarantine,
            llm_run_contract=llm_run_contract,
            tool_timeout_policy=tool_timeout_policy,
            submission_task_root=submission_task_root,
            evaluator_task_root=evaluator_task_root,
        ),
    )

    for ordinal, (submission_task_dir, evaluator_task_dir) in enumerate(
        selected, start=1
    ):
        if (
            execution_source_snapshot().get("tree_sha256")
            != source_start.get("tree_sha256")
        ):
            raise RuntimeError(
                "execution source changed during shard; refusing mixed evidence"
            )
        task_id = evaluator_task_dir.name
        if task_id in done:
            continue
        official = evaluator_task_dir.parent.name == "official"
        expected_grading_source = (
            "hidden"
            if (evaluator_task_dir / "hidden").is_dir()
            else "public_fallback"
        )
        attempt_root = _next_attempt(output_root / "tasks" / task_id)
        submission_root = attempt_root / "submission"
        evaluator_root = attempt_root / "evaluator"
        submission_log = attempt_root / "submission.log"
        evaluator_log = attempt_root / "evaluator.log"

        submission_command = build_submission_command(
            task_dir=submission_task_dir,
            backend=backend,
            output_root=submission_root,
            competition=competition,
        )
        submission_rc, launcher_error, submission_elapsed = _run(
            submission_command,
            submission_log,
            timeout_s,
            env_overrides=submission_env,
        )
        submission_path = submission_root / task_id / "run_report.json"
        submission: dict[str, Any] | None = None
        submission_errors: list[str] = []
        try:
            submission = _load_report(submission_path)
            submission_errors = validate_submission(
                submission,
                task_id,
                expected_client=llm_run_contract["expected_client"],
                expected_model=llm_run_contract["model"],
            )
        except Exception as exc:
            submission_errors = [str(exc)]

        evaluator: dict[str, Any] | None = None
        evaluator_errors: list[str] = []
        evaluator_rc: int | None = None
        evaluator_elapsed = 0.0
        evaluator_path = evaluator_root / task_id / "run_report.json"
        evaluator_command: list[str] | None = None
        submission_evidence_path = (
            submission_root / task_id / "submission_evidence.json"
        )
        final_path_text = (
            (submission or {}).get("final_artifact") or {}
        ).get("path")
        final_path = Path(final_path_text) if final_path_text else None
        if (
            not launcher_error
            and submission_requires_evaluator(submission, final_path)
            and submission_evidence_path.is_file()
        ):
            evaluator_command = build_evaluator_command(
                task_dir=evaluator_task_dir,
                final_kernel=final_path,
                submission_evidence=submission_evidence_path,
                output_root=evaluator_root,
            )
            evaluator_rc, evaluator_launcher_error, evaluator_elapsed = _run(
                evaluator_command,
                evaluator_log,
                timeout_s,
                env_overrides=tool_timeout_env,
            )
            if evaluator_launcher_error:
                launcher_error = evaluator_launcher_error
            try:
                evaluator = _load_report(evaluator_path)
                evaluator_errors = validate_evaluator(
                    evaluator,
                    task_id,
                    official_task=official,
                    expected_grading_source=expected_grading_source,
                )
            except Exception as exc:
                evaluator_errors = [str(exc)]
        else:
            evaluator_log.write_text(
                "Evaluator not launched because submission did not complete "
                "with a readable, evidence-linked final kernel.\n",
                encoding="utf-8",
            )

        audit_errors = submission_errors + evaluator_errors
        outcome = classify_outcome(submission, evaluator, launcher_error)
        usage = ((submission or {}).get("llm") or {}).get(
            "token_usage"
        ) or {}
        llm_record = (submission or {}).get("llm") or {}
        budget = (submission or {}).get("budget") or {}
        submission_trace = (submission or {}).get("execution_trace") or {}
        transcript = submission_trace.get("transcript") or []
        calls_by_tool = Counter(
            str(item.get("kind") or "unknown") for item in transcript
        )
        failed_calls_by_tool = Counter(
            str(item.get("kind") or "unknown")
            for item in (submission_trace.get("metered_results") or [])
            if item.get("ok") is not True
        )
        evaluator_grading = (
            ((evaluator or {}).get("execution_trace") or {}).get(
                "grading_results"
            )
            or []
        )
        frequency = (
            ((submission or {}).get("gates") or {}).get(
                "frequency_100mhz"
            )
            or {}
        )
        record = {
            "ordinal": ordinal,
            "task_id": task_id,
            "task_dir": str(evaluator_task_dir),
            "submission_task_dir": str(submission_task_dir),
            "evaluator_task_dir": str(evaluator_task_dir),
            "official_task": official,
            "attempt_root": str(attempt_root),
            "outcome": outcome,
            "launcher_error": launcher_error,
            "audit_errors": audit_errors,
            "submission": {
                "backend": backend,
                "command": submission_command,
                "return_code": submission_rc,
                "elapsed_s": submission_elapsed,
                "log": str(submission_log),
                "report": str(submission_path),
                "report_sha256": (
                    _sha256(submission_path)
                    if submission_path.is_file()
                    else None
                ),
                "status": (submission or {}).get("status"),
                "stop_reason": (submission or {}).get("stop_reason"),
                "final_kernel": final_path_text,
                "submission_evidence": str(submission_evidence_path),
                "final_kernel_sha256": (
                    _sha256(final_path)
                    if final_path is not None and final_path.is_file()
                    else None
                ),
                "api": usage,
                "llm_client": llm_record.get("client"),
                "model": llm_record.get("model"),
                "model_compliance": (submission or {}).get(
                    "model_compliance"
                ),
                "budget": budget,
                "frequency_mhz": frequency.get("frequency_mhz"),
                "credits_spent": budget.get("spent"),
                "tool_calls": (submission or {}).get("tool_call_count"),
                "calls_by_tool": dict(sorted(calls_by_tool.items())),
                "failed_calls_by_tool": dict(
                    sorted(failed_calls_by_tool.items())
                ),
            },
            "evaluator": {
                "command": evaluator_command,
                "return_code": evaluator_rc,
                "elapsed_s": evaluator_elapsed,
                "log": str(evaluator_log),
                "report": str(evaluator_path),
                "report_sha256": (
                    _sha256(evaluator_path)
                    if evaluator_path.is_file()
                    else None
                ),
                "status": (evaluator or {}).get("status"),
                "stop_reason": (evaluator or {}).get("stop_reason"),
                "grading_source": (
                    (evaluator or {}).get("grading") or {}
                ).get("source"),
                "score": (
                    (evaluator or {}).get("scoring") or {}
                ).get("score"),
                "grading_tool_call_count": len(evaluator_grading),
                "grading_calls_by_stage": dict(
                    sorted(
                        Counter(
                            str(item.get("stage") or "unknown")
                            for item in evaluator_grading
                        ).items()
                    )
                ),
            },
        }
        _write_summary(
            output_root / "tasks" / task_id / "checkpoint.json",
            record,
        )
        records.append(record)
        source_current = execution_source_snapshot()
        _write_summary(
            summary_path,
            _summary(
                shard_index=shard_index,
                shard_count=shard_count,
                selected_count=len(selected),
                started=shard_started,
                records=records,
                source_start=source_start,
                source_current=source_current,
                quarantine=quarantine,
                llm_run_contract=llm_run_contract,
                tool_timeout_policy=tool_timeout_policy,
                submission_task_root=submission_task_root,
                evaluator_task_root=evaluator_task_root,
            ),
        )
        if source_current.get("tree_sha256") != source_start.get(
            "tree_sha256"
        ):
            raise RuntimeError(
                "execution source changed during task; shard evidence is mixed"
            )
        print(
            f"shard={shard_index}/{shard_count} "
            f"task={ordinal}/{len(selected)} id={task_id} "
            f"outcome={outcome} sub_rc={submission_rc} "
            f"eval_rc={evaluator_rc} requests={usage.get('request_count')} "
            f"elapsed={submission_elapsed + evaluator_elapsed:.1f}s",
            flush=True,
        )

    result = json.loads(summary_path.read_text(encoding="utf-8"))
    if not (result.get("execution_source") or {}).get("stable"):
        raise RuntimeError("execution source stability gate failed")
    return result


def resolve_cli_task_roots(
    task_root: Path | None,
    submission_task_root: Path | None,
    evaluator_task_root: Path | None,
) -> tuple[Path, Path]:
    """Resolve either the legacy combined root or the mandatory split pair."""

    if task_root is not None:
        if submission_task_root is not None or evaluator_task_root is not None:
            raise RuntimeError(
                "--task-root cannot be combined with split task-root options"
            )
        resolved = task_root.resolve()
        return resolved, resolved
    if submission_task_root is None or evaluator_task_root is None:
        raise RuntimeError(
            "provide --task-root, or provide both --submission-task-root "
            "and --evaluator-task-root"
        )
    return submission_task_root.resolve(), evaluator_task_root.resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task-root",
        type=Path,
        help="Legacy combined task root used by both submission and evaluator",
    )
    parser.add_argument(
        "--submission-task-root",
        type=Path,
        help="Physically public-only task root visible to the submission role",
    )
    parser.add_argument(
        "--evaluator-task-root",
        type=Path,
        help="Private task root containing hidden tests and references",
    )
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--shard-index", required=True, type=int)
    parser.add_argument("--shard-count", type=int, default=3)
    parser.add_argument("--task-timeout-s", type=float, default=7200.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--backend",
        choices=sorted(REAL_API_CLIENTS),
        default="custom",
        help="Real API provider used by every task in this shard",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Exact provider model ID. Required unless the backend-specific "
            "model environment variable is set."
        ),
    )
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument(
        "--competition",
        action="store_true",
        help="Use independent measured optimization strategy lanes",
    )
    parser.add_argument(
        "--exclude-task-ids",
        type=Path,
        default=None,
        help=(
            "Optional JSON list/report of task IDs to quarantine from this "
            "run. Default preserves the full expected corpus."
        ),
    )
    parser.add_argument(
        "--retry-from-audit",
        type=Path,
        default=None,
        help="Run only task IDs listed in retry_task_ids of a P0 audit",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        raise RuntimeError("shard index is outside shard count")
    requested = set(args.task_id)
    excluded = (
        load_excluded_task_ids(args.exclude_task_ids)
        if args.exclude_task_ids is not None
        else None
    )
    if args.retry_from_audit is not None:
        audit = json.loads(
            args.retry_from_audit.read_text(encoding="utf-8")
        )
        requested.update(audit.get("retry_task_ids") or [])
    submission_task_root, evaluator_task_root = resolve_cli_task_roots(
        args.task_root,
        args.submission_task_root,
        args.evaluator_task_root,
    )
    result = run_shard(
        task_root=evaluator_task_root,
        submission_task_root=submission_task_root,
        output_root=args.output_root.resolve(),
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        timeout_s=args.task_timeout_s,
        resume=args.resume,
        requested_task_ids=requested or None,
        excluded_task_ids=excluded,
        excluded_task_source=(
            str(args.exclude_task_ids) if args.exclude_task_ids is not None else None
        ),
        backend=args.backend,
        model=args.model,
        competition=args.competition,
    )
    return 0 if result["completed_record_count"] == result[
        "selected_task_count"
    ] else 4


if __name__ == "__main__":
    raise SystemExit(main())
