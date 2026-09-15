"""Fail-closed entry points for physically isolated Track-A roles.

The submission role is intended to run in a container that mounts only the
public corpus.  The evaluator role runs in a second, network-disabled
container that mounts the evaluator bundle and the completed submission as
read-only inputs.  This module verifies those contracts before delegating to
``agent.main``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

from agent.main import main as agent_main
from agent.models import SubmissionEvidence
from scoring.run_p0_real_api_shard import (
    _load_report,
    _public_task_identity,
    execution_source_snapshot,
    resolve_llm_run_contract,
    validate_evaluator,
    validate_submission,
)


PRIVATE_PATH_NAMES = frozenset({"hidden", "reference"})
FORBIDDEN_SUBMISSION_MOUNT_TARGETS = (
    "/workspace",
    "/repo",
    "/private",
    "/fpt26-evaluator-tasks",
)
SECRET_ENV_NAMES = (
    "FPT26_LLM_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "DASHSCOPE_API_KEY",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unescape_mount_field(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def mounted_paths(mountinfo: Path = Path("/proc/self/mountinfo")) -> list[dict[str, str]]:
    """Return mount targets and sources visible to the current container."""

    records: list[dict[str, str]] = []
    for line in mountinfo.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        separator = fields.index("-")
        records.append(
            {
                "target": _unescape_mount_field(fields[4]),
                "source": _unescape_mount_field(fields[separator + 2]),
                "filesystem": fields[separator + 1],
            }
        )
    return records


def _path_has_private_component(value: str) -> bool:
    parts = {part.lower() for part in PurePosixPath(value).parts}
    return bool(parts & PRIVATE_PATH_NAMES) or "evaluator_private" in value.lower()


def assert_submission_isolation(task_dir: Path) -> dict[str, Any]:
    """Prove that the submission container has no private task mount."""

    task_dir = task_dir.resolve()
    if not task_dir.is_dir():
        raise RuntimeError(f"submission task not found: {task_dir}")
    if _path_has_private_component(str(task_dir)):
        raise RuntimeError("submission task path is evaluator-owned")

    private_entries = sorted(
        str(path.relative_to(task_dir))
        for path in task_dir.rglob("*")
        if path.name.lower() in PRIVATE_PATH_NAMES
    )
    if private_entries:
        raise RuntimeError(
            f"submission task tree contains private paths: {private_entries}"
        )

    mounts = mounted_paths()
    forbidden_mounts = [
        record
        for record in mounts
        if _path_has_private_component(record["target"])
        or _path_has_private_component(record["source"])
        or any(
            record["target"] == target
            or record["target"].startswith(target + "/")
            for target in FORBIDDEN_SUBMISSION_MOUNT_TARGETS
        )
    ]
    if forbidden_mounts:
        raise RuntimeError(
            "submission container exposes evaluator-private mounts: "
            f"{forbidden_mounts}"
        )

    return {
        "schema_version": 1,
        "role": "submission",
        "physical_isolation_proven": True,
        "task_dir": str(task_dir),
        "private_task_paths_visible": False,
        "private_mounts_visible": False,
        "public_task_identity": _public_task_identity(task_dir),
        "execution_source": execution_source_snapshot(),
        "mount_targets": sorted(record["target"] for record in mounts),
    }


def assert_evaluator_isolation(
    task_dir: Path,
    network_root: Path = Path("/sys/class/net"),
) -> dict[str, Any]:
    """Prove that private inputs exist and no API credential was inherited."""

    task_dir = task_dir.resolve()
    missing = [
        name for name in sorted(PRIVATE_PATH_NAMES) if not (task_dir / name).is_dir()
    ]
    if missing:
        raise RuntimeError(f"evaluator task is missing private paths: {missing}")
    inherited = sorted(name for name in SECRET_ENV_NAMES if os.environ.get(name))
    if inherited:
        raise RuntimeError(
            "evaluator container inherited API credentials: " + ", ".join(inherited)
        )
    interfaces = sorted(path.name for path in network_root.iterdir())
    if interfaces != ["lo"]:
        raise RuntimeError(
            "evaluator container is not network-isolated; interfaces="
            f"{interfaces}"
        )
    return {
        "schema_version": 1,
        "role": "evaluator",
        "physical_isolation_proven": True,
        "task_dir": str(task_dir),
        "private_task_paths_visible": True,
        "api_credentials_visible": False,
        "network_isolated": True,
        "network_interfaces": interfaces,
        "execution_source": execution_source_snapshot(),
    }


def resolve_submission_artifacts(
    submission_root: Path,
    task_id: str,
) -> tuple[Path, Path, dict[str, Any]]:
    """Resolve and authenticate the two files crossing the role boundary."""

    task_output = (submission_root / task_id).resolve()
    root = submission_root.resolve()
    try:
        task_output.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("submission task output escapes its mounted root") from exc

    report = _load_report(task_output / "run_report.json")
    if report.get("task_id") != task_id or report.get("run_role") != "submission":
        raise RuntimeError("submission report identity or role mismatch")
    if report.get("status") != "completed":
        raise RuntimeError(
            f"submission is not evaluator-ready: {report.get('status')!r}"
        )

    evidence_path = task_output / "submission_evidence.json"
    evidence = SubmissionEvidence.from_dict(
        json.loads(evidence_path.read_text(encoding="utf-8"))
    )
    if evidence.task_id != task_id or evidence.status != "completed":
        raise RuntimeError("submission evidence identity or status mismatch")

    reported_path = str((report.get("final_artifact") or {}).get("path") or "")
    basename = PurePosixPath(reported_path).name
    if not basename or basename in {".", ".."}:
        raise RuntimeError("submission report has no safe final-kernel filename")
    final_kernel = (task_output / basename).resolve()
    try:
        final_kernel.relative_to(task_output)
    except ValueError as exc:
        raise RuntimeError("final kernel escapes submission output") from exc
    if not final_kernel.is_file():
        raise RuntimeError(f"final kernel not found: {final_kernel}")

    digest = _sha256(final_kernel)
    report_digest = (report.get("final_artifact") or {}).get("sha256")
    if digest != report_digest or digest != evidence.kernel_sha256:
        raise RuntimeError("final-kernel hash disagrees with submission evidence")
    return final_kernel, evidence_path, report


def _write_attestation(output_root: Path, task_id: str, value: dict[str, Any]) -> Path:
    path = output_root / task_id / "container_isolation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def run_submission(args: argparse.Namespace) -> int:
    attestation = assert_submission_isolation(args.task)
    contract = resolve_llm_run_contract(args.backend, args.model)
    attestation["llm_contract"] = contract
    attestation_path = _write_attestation(
        args.output_root, args.task.name, attestation
    )

    model_env = "LLM4HLS_MODEL" if args.backend == "openrouter" else "FPT26_LLM_MODEL"
    os.environ[model_env] = contract["model"]
    command = [
        "--task", str(args.task),
        "--mode", "auto",
        "--run-role", "submission",
        "--backend", args.backend,
        "--output-root", str(args.output_root),
        "--quiet",
    ]
    if args.competition:
        command.append("--competition")
    rc = agent_main(command)

    report_path = args.output_root / args.task.name / "run_report.json"
    if report_path.is_file():
        report = _load_report(report_path)
        errors = validate_submission(
            report,
            args.task.name,
            expected_client=contract["expected_client"],
            expected_model=contract["model"],
        )
        attestation["submission_audit_errors"] = errors
        attestation_path.write_text(
            json.dumps(attestation, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return rc


def run_evaluator(args: argparse.Namespace) -> int:
    attestation = assert_evaluator_isolation(args.task)
    final_kernel, evidence_path, _ = resolve_submission_artifacts(
        args.submission_root,
        args.task.name,
    )
    submission_attestation_path = (
        args.submission_root / args.task.name / "container_isolation.json"
    )
    submission_attestation = json.loads(
        submission_attestation_path.read_text(encoding="utf-8")
    )
    if submission_attestation.get("physical_isolation_proven") is not True:
        raise RuntimeError("submission physical-isolation evidence is missing")
    if submission_attestation.get("public_task_identity") != _public_task_identity(
        args.task
    ):
        raise RuntimeError(
            "public task contract differs between submission and evaluator bundles"
        )
    attestation.update(
        {
            "submission_report_sha256": _sha256(
                args.submission_root / args.task.name / "run_report.json"
            ),
            "submission_evidence_sha256": _sha256(evidence_path),
            "submission_isolation_sha256": _sha256(submission_attestation_path),
            "final_kernel_sha256": _sha256(final_kernel),
        }
    )
    attestation_path = _write_attestation(
        args.output_root, args.task.name, attestation
    )

    rc = agent_main(
        [
            "--task", str(args.task),
            "--run-role", "evaluator",
            "--final-kernel", str(final_kernel),
            "--submission-evidence", str(evidence_path),
            "--output-root", str(args.output_root),
            "--quiet",
        ]
    )
    report_path = args.output_root / args.task.name / "run_report.json"
    if report_path.is_file():
        report = _load_report(report_path)
        grading_source = (
            "hidden" if (args.task / "hidden").is_dir() else "public_fallback"
        )
        errors = validate_evaluator(
            report,
            args.task.name,
            official_task=False,
            expected_grading_source=grading_source,
        )
        attestation["evaluator_audit_errors"] = errors
        attestation_path.write_text(
            json.dumps(attestation, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return rc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="role", required=True)

    submission = subparsers.add_parser("submission")
    submission.add_argument("--task", required=True, type=Path)
    submission.add_argument("--output-root", required=True, type=Path)
    submission.add_argument("--backend", choices=("custom", "openrouter"), default="custom")
    submission.add_argument("--model", required=True)
    submission.add_argument("--competition", action="store_true")

    evaluator = subparsers.add_parser("evaluator")
    evaluator.add_argument("--task", required=True, type=Path)
    evaluator.add_argument("--submission-root", required=True, type=Path)
    evaluator.add_argument("--output-root", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.role == "submission":
        return run_submission(args)
    return run_evaluator(args)


if __name__ == "__main__":
    raise SystemExit(main())
