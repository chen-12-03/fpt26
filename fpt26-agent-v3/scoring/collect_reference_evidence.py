"""Collect fresh, exact starter/reference Vitis evidence for calibration.

This command intentionally does not calculate weight candidates or scores.  It
only records raw tool results after the semantic classification has been frozen.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from agent.runner import CSimTool, SynthTool
from agent.testbench import normalize_task_testbench_data
from llm4hls.task import load_task


_CLASSIFICATION = Path(__file__).with_name("reference_classification.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _classification_for(task_id: str, generated: bool) -> dict[str, str]:
    manifest = json.loads(_CLASSIFICATION.read_text())
    classes = manifest["calibration_classes"]
    if generated:
        entry = classes["ppa_reference"][0]
        return {
            "class": "ppa_reference",
            "subtype": entry["subtype"],
        }
    for class_name in ("ppa_reference", "correctness_only", "unknown"):
        for entry in classes[class_name]:
            if entry.get("task_id") == task_id:
                return {
                    "class": class_name,
                    "subtype": entry["subtype"],
                }
    raise RuntimeError(f"task is absent from frozen classification: {task_id}")


def _tool_record(result: Any, artifact_dir: Path) -> dict[str, Any]:
    report = result.report.to_dict() if result.report is not None else None
    xml_path = artifact_dir / "synth_proj/sol/syn/report/csynth.xml"
    return {
        "kind": result.kind,
        "ok": result.ok,
        "phase": result.phase,
        "return_code": result.return_code,
        "elapsed_s": result.elapsed_s,
        "report": report,
        "artifact_dir": str(artifact_dir),
        "csynth_xml": str(xml_path) if xml_path.is_file() else None,
        "csynth_xml_sha256": _sha256(xml_path) if xml_path.is_file() else None,
        "log": result.log,
    }


def collect(task_dir: Path, output_root: Path, repeat_index: int) -> Path:
    task_dir = task_dir.resolve()
    output_root = output_root.resolve()
    task = load_task(task_dir)
    normalize_task_testbench_data(task)
    if task.reference_code is None:
        raise RuntimeError(f"task has no reference kernel: {task.id}")

    repeat_dir = output_root / task.id / f"repeat_{repeat_index:02d}"
    evidence_path = repeat_dir / "evidence.json"
    if evidence_path.exists():
        raise RuntimeError(f"refusing to overwrite existing evidence: {evidence_path}")
    repeat_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    hidden_files = task.assemble(
        task.reference_code, task.hidden_tb_code, task.hidden_tb_name
    )
    hidden_csim_dir = repeat_dir / "reference_hidden_csim"
    hidden_csim = CSimTool().run(
        hidden_csim_dir,
        hidden_files,
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
        data_files=getattr(task, "hidden_data_files", None) or None,
    )

    synth = SynthTool()
    starter_files = dict(task.headers)
    starter_files[task.kernel_name] = task.kernel_code
    starter_dir = repeat_dir / "starter_synth"
    starter = synth.run(
        starter_dir,
        starter_files,
        synth_sources=[task.kernel_name],
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
    )

    reference_files = dict(task.headers)
    reference_files[task.kernel_name] = task.reference_code
    reference_dir = repeat_dir / "reference_synth"
    reference = synth.run(
        reference_dir,
        reference_files,
        synth_sources=[task.kernel_name],
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
    )

    record = {
        "schema_version": 1,
        "purpose": "fresh_reference_calibration_evidence",
        "task_id": task.id,
        "task_dir": str(task_dir),
        "repeat_index": repeat_index,
        "classification": _classification_for(
            task.id, task_dir.parent.name == "generated"
        ),
        "target": {
            "top": task.top,
            "part": task.part,
            "clock_ns": task.clock_ns,
            "requires_cosim": task.requires_cosim,
        },
        "sources": {
            "kernel_name": task.kernel_name,
            "starter_sha256": hashlib.sha256(task.kernel_code.encode()).hexdigest(),
            "reference_sha256": hashlib.sha256(task.reference_code.encode()).hexdigest(),
            "starter_reference_identical": task.kernel_code == task.reference_code,
        },
        "reference_hidden_csim": _tool_record(hidden_csim, hidden_csim_dir),
        "starter_synth": _tool_record(starter, starter_dir),
        "reference_synth": _tool_record(reference, reference_dir),
        "wall_time_s": time.monotonic() - started,
        "llm": {
            "invoked": False,
            "input_tokens": "unavailable",
            "output_tokens": "unavailable",
            "total_tokens": "unavailable",
            "cached_tokens": "unavailable",
            "reasoning_tokens": "unavailable",
        },
    }
    evidence_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return evidence_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--repeat-index", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence = collect(args.task, args.output_root, args.repeat_index)
    record = json.loads(evidence.read_text())
    stages = (
        record["reference_hidden_csim"],
        record["starter_synth"],
        record["reference_synth"],
    )
    print(
        f"{record['task_id']} evidence={evidence} "
        + " ".join(f"{stage['kind']}:{stage['phase']}" for stage in stages)
    )
    return 0 if all(stage["ok"] for stage in stages) else 4


if __name__ == "__main__":
    raise SystemExit(main())
