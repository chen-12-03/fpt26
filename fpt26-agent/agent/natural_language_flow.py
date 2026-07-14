#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from agent.ir import HLSIR
from agent.run_existing_code import DEFAULT_RUNNER, discover_run_dir_from_stdout, run_existing_code
from agent.spec_extractor import SpecExtractionError, extract_spec_to_ir
from agent.template_generator import TemplateGenerationError, generate_vector_add_template


AGENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENT_WORK_ROOT = AGENT_ROOT / "agent_runs" / "natural_language"
SPEC_FILENAME = "spec.txt"
DERIVED_IR_FILENAME = "existing_code_ir.json"
AGENT_MANIFEST_FILENAME = "agent_manifest.json"
HLS_STDOUT_FILENAME = "hls.stdout.log"
HLS_STDERR_FILENAME = "hls.stderr.log"


@dataclass(frozen=True)
class NaturalLanguageRunResult:
    exit_code: int
    work_dir: Path | None
    final_run_dir: Path | None


def run_natural_language_baseline(
    spec_path: Path,
    *,
    runner_path: Path = DEFAULT_RUNNER,
    agent_root: Path = AGENT_ROOT,
    work_root: Path | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> NaturalLanguageRunResult:
    if not spec_path.is_file():
        print(f"error: natural-language spec file does not exist: {spec_path}", file=stderr)
        return NaturalLanguageRunResult(exit_code=2, work_dir=None, final_run_dir=None)

    work_dir = _allocate_work_dir(work_root or DEFAULT_AGENT_WORK_ROOT, "baseline")
    spec_text = spec_path.read_text(encoding="utf-8")
    spec_copy_path = work_dir / SPEC_FILENAME
    spec_copy_path.write_text(spec_text, encoding="utf-8")

    manifest: dict[str, Any] = {
        "mode": "baseline",
        "input_type": "natural-language",
        "original_spec": str(spec_path.resolve()),
        "spec_text": str(spec_copy_path),
        "work_dir": str(work_dir),
        "stages": {
            "spec_extraction": "not_run",
            "template_generation": "not_run",
            "derived_ir": "not_run",
            "hls": "not_run",
        },
        "artifacts": {},
        "final_run_dir": None,
        "final_exit_code": None,
    }
    _write_agent_manifest(work_dir, manifest)

    try:
        extraction = extract_spec_to_ir(spec_text, work_dir)
    except SpecExtractionError as exc:
        manifest["stages"]["spec_extraction"] = "fail"
        manifest["final_exit_code"] = 2
        _write_agent_manifest(work_dir, manifest)
        print(f"error: spec extraction failed: {exc}", file=stderr)
        return NaturalLanguageRunResult(exit_code=2, work_dir=work_dir, final_run_dir=None)

    manifest["stages"]["spec_extraction"] = "pass"
    manifest["artifacts"]["natural_language_ir"] = str(extraction.ir_path)
    manifest["artifacts"]["llm_call"] = str(extraction.metadata_path)
    _write_agent_manifest(work_dir, manifest)

    generated_dir = work_dir / "generated"
    try:
        generated = generate_vector_add_template(extraction.ir_path, generated_dir)
    except TemplateGenerationError as exc:
        manifest["stages"]["template_generation"] = "fail"
        manifest["final_exit_code"] = 2
        _write_agent_manifest(work_dir, manifest)
        print(f"error: template generation failed: {exc}", file=stderr)
        return NaturalLanguageRunResult(exit_code=2, work_dir=work_dir, final_run_dir=None)

    manifest["stages"]["template_generation"] = "pass"
    manifest["artifacts"]["kernel_cpp"] = str(generated.kernel_path)
    manifest["artifacts"]["host_cpp"] = str(generated.host_path)
    manifest["function_signature"] = generated.function_signature
    _write_agent_manifest(work_dir, manifest)

    try:
        derived_ir_path = _write_derived_existing_code_ir(
            extraction.ir,
            source_path=generated.kernel_path,
            testbench_path=generated.host_path,
            output_path=work_dir / DERIVED_IR_FILENAME,
            agent_root=agent_root,
        )
    except Exception as exc:
        manifest["stages"]["derived_ir"] = "fail"
        manifest["final_exit_code"] = 2
        _write_agent_manifest(work_dir, manifest)
        print(f"error: derived existing-code IR generation failed: {exc}", file=stderr)
        return NaturalLanguageRunResult(exit_code=2, work_dir=work_dir, final_run_dir=None)

    manifest["stages"]["derived_ir"] = "pass"
    manifest["artifacts"]["derived_existing_code_ir"] = str(derived_ir_path)
    _write_agent_manifest(work_dir, manifest)

    hls_stdout = io.StringIO()
    hls_stderr = io.StringIO()
    exit_code = run_existing_code(
        derived_ir_path,
        runner_path=runner_path,
        candidate_prefix="baseline",
        agent_root=agent_root,
        manifest_metadata={
            "mode": "baseline",
            "input_type": "natural-language",
            "llm_called": True,
            "agent_work_dir": str(work_dir),
            "original_spec": str(spec_path.resolve()),
            "spec_text": str(spec_copy_path),
            "natural_language_ir": str(extraction.ir_path),
            "llm_call": str(extraction.metadata_path),
            "generated_kernel": str(generated.kernel_path),
            "generated_host": str(generated.host_path),
            "derived_existing_code_ir": str(derived_ir_path),
        },
        stdout=hls_stdout,
        stderr=hls_stderr,
    )

    hls_stdout_text = hls_stdout.getvalue()
    hls_stderr_text = hls_stderr.getvalue()
    stdout.write(hls_stdout_text)
    stderr.write(hls_stderr_text)
    (work_dir / HLS_STDOUT_FILENAME).write_text(hls_stdout_text, encoding="utf-8")
    (work_dir / HLS_STDERR_FILENAME).write_text(hls_stderr_text, encoding="utf-8")

    final_run_dir = discover_run_dir_from_stdout(hls_stdout_text)
    manifest["stages"]["hls"] = "pass" if exit_code == 0 else "fail"
    manifest["artifacts"]["hls_stdout"] = str(work_dir / HLS_STDOUT_FILENAME)
    manifest["artifacts"]["hls_stderr"] = str(work_dir / HLS_STDERR_FILENAME)
    manifest["final_run_dir"] = str(final_run_dir) if final_run_dir else None
    manifest["final_exit_code"] = exit_code
    _write_agent_manifest(work_dir, manifest)

    return NaturalLanguageRunResult(exit_code=exit_code, work_dir=work_dir, final_run_dir=final_run_dir)


def _allocate_work_dir(work_root: Path, prefix: str) -> Path:
    work_root.mkdir(parents=True, exist_ok=True)
    for index in range(1000):
        candidate = work_root / f"{prefix}_{index:03d}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError(f"no free Agent work directory under {work_root}")


def _write_derived_existing_code_ir(
    natural_ir: HLSIR,
    *,
    source_path: Path,
    testbench_path: Path,
    output_path: Path,
    agent_root: Path,
) -> Path:
    data = natural_ir.to_dict()
    data["input_mode"] = "existing_code"
    data["source_file"] = _path_for_ir(source_path, agent_root)
    data["testbench_file"] = _path_for_ir(testbench_path, agent_root)
    inferred_fields = dict(data["inferred_fields"])
    inferred_fields["source_file"] = {
        "value": data["source_file"],
        "source": "deterministic_vector_add_template",
    }
    inferred_fields["testbench_file"] = {
        "value": data["testbench_file"],
        "source": "deterministic_vector_add_template",
    }
    inferred_fields["derived_from"] = {
        "input_mode": "natural_language",
        "generator": "deterministic_vector_add_template",
    }
    data["inferred_fields"] = inferred_fields
    HLSIR.from_dict(data).save(output_path)
    return output_path


def _path_for_ir(path: Path, agent_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(agent_root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _write_agent_manifest(work_dir: Path, manifest: dict[str, Any]) -> None:
    (work_dir / AGENT_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
