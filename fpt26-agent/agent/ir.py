#!/usr/bin/env python3
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "hls-ir-v1"
ALLOWED_INPUT_MODES = {"existing_code", "natural_language"}
REQUIRED_FIELDS = {
    "schema_version",
    "task_id",
    "input_mode",
    "top_function",
    "source_file",
    "testbench_file",
    "inputs",
    "outputs",
    "clock_period_ns",
    "hls_part",
    "verification",
    "inferred_fields",
}


class HLSIRValidationError(ValueError):
    """Raised when an IR document cannot be used safely."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class HLSIR:
    schema_version: str
    task_id: str
    input_mode: str
    top_function: str
    source_file: str | None
    testbench_file: str | None
    inputs: list[dict[str, Any]]
    outputs: list[dict[str, Any]]
    clock_period_ns: float
    hls_part: str
    verification: dict[str, Any]
    inferred_fields: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HLSIR":
        normalized = validate_ir_dict(data)
        return cls(
            schema_version=normalized["schema_version"],
            task_id=normalized["task_id"],
            input_mode=normalized["input_mode"],
            top_function=normalized["top_function"],
            source_file=normalized["source_file"],
            testbench_file=normalized["testbench_file"],
            inputs=deepcopy(normalized["inputs"]),
            outputs=deepcopy(normalized["outputs"]),
            clock_period_ns=normalized["clock_period_ns"],
            hls_part=normalized["hls_part"],
            verification=deepcopy(normalized["verification"]),
            inferred_fields=deepcopy(normalized["inferred_fields"]),
        )

    @classmethod
    def load(cls, path: str | Path) -> "HLSIR":
        return load_ir(path)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy({
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "input_mode": self.input_mode,
            "top_function": self.top_function,
            "source_file": self.source_file,
            "testbench_file": self.testbench_file,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "clock_period_ns": self.clock_period_ns,
            "hls_part": self.hls_part,
            "verification": self.verification,
            "inferred_fields": self.inferred_fields,
        })

    def save(self, path: str | Path) -> None:
        save_ir(self, path)


def load_ir(path: str | Path) -> HLSIR:
    ir_path = Path(path)
    try:
        data = json.loads(ir_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HLSIRValidationError([f"invalid JSON in {ir_path}: {exc.msg}"]) from exc
    except OSError as exc:
        raise HLSIRValidationError([f"cannot read IR JSON {ir_path}: {exc}"]) from exc

    if not isinstance(data, dict):
        raise HLSIRValidationError(["IR root must be a JSON object"])
    return HLSIR.from_dict(data)


def save_ir(ir: HLSIR, path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = validate_ir_dict(ir.to_dict())
    output_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def validate_ir_dict(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(data, dict):
        raise HLSIRValidationError(["IR root must be a JSON object"])

    missing = sorted(REQUIRED_FIELDS - data.keys())
    if missing:
        errors.append(f"missing required field(s): {', '.join(missing)}")

    unexpected = sorted(data.keys() - REQUIRED_FIELDS)
    if unexpected:
        errors.append(f"unexpected field(s): {', '.join(unexpected)}")

    schema_version = _require_non_empty_string(data, "schema_version", errors)
    if schema_version and schema_version != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}, got {schema_version!r}")

    task_id = _require_non_empty_string(data, "task_id", errors)
    input_mode = _require_non_empty_string(data, "input_mode", errors)
    if input_mode and input_mode not in ALLOWED_INPUT_MODES:
        modes = ", ".join(sorted(ALLOWED_INPUT_MODES))
        errors.append(f"input_mode must be one of: {modes}")

    top_function = _require_non_empty_string(data, "top_function", errors)
    source_file = _optional_path_string(data, "source_file", errors)
    testbench_file = _optional_path_string(data, "testbench_file", errors)

    if input_mode == "existing_code":
        if not source_file:
            errors.append("source_file is required when input_mode is 'existing_code'")
        if not testbench_file:
            errors.append("testbench_file is required when input_mode is 'existing_code'")

    inputs = _validate_ports(data.get("inputs"), "inputs", errors)
    outputs = _validate_ports(data.get("outputs"), "outputs", errors)
    clock_period_ns = _require_positive_number(data, "clock_period_ns", errors)
    hls_part = _require_non_empty_string(data, "hls_part", errors)
    verification = _require_object(data, "verification", errors)
    inferred_fields = _require_object(data, "inferred_fields", errors)

    if errors:
        raise HLSIRValidationError(errors)

    return {
        "schema_version": schema_version,
        "task_id": task_id,
        "input_mode": input_mode,
        "top_function": top_function,
        "source_file": source_file,
        "testbench_file": testbench_file,
        "inputs": inputs,
        "outputs": outputs,
        "clock_period_ns": clock_period_ns,
        "hls_part": hls_part,
        "verification": verification,
        "inferred_fields": inferred_fields,
    }


def _require_non_empty_string(data: dict[str, Any], field: str, errors: list[str]) -> str | None:
    if field not in data:
        return None
    value = data[field]
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be a non-empty string")
        return None
    return value


def _optional_path_string(data: dict[str, Any], field: str, errors: list[str]) -> str | None:
    if field not in data:
        return None
    value = data[field]
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be null or a non-empty string")
        return None
    return value


def _require_positive_number(data: dict[str, Any], field: str, errors: list[str]) -> float | None:
    if field not in data:
        return None
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{field} must be a positive number")
        return None
    normalized = float(value)
    if normalized <= 0:
        errors.append(f"{field} must be a positive number")
        return None
    return normalized


def _require_object(data: dict[str, Any], field: str, errors: list[str]) -> dict[str, Any] | None:
    if field not in data:
        return None
    value = data[field]
    if not isinstance(value, dict):
        errors.append(f"{field} must be a JSON object")
        return None
    return value


def _validate_ports(value: Any, field: str, errors: list[str]) -> list[dict[str, Any]] | None:
    if value is None:
        if field not in REQUIRED_FIELDS:
            return None
        errors.append(f"{field} must be a list")
        return None
    if not isinstance(value, list):
        errors.append(f"{field} must be a list")
        return None

    ports: list[dict[str, Any]] = []
    for index, port in enumerate(value):
        path = f"{field}[{index}]"
        if not isinstance(port, dict):
            errors.append(f"{path} must be a JSON object")
            continue

        name = port.get("name")
        data_type = port.get("data_type")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{path}.name must be a non-empty string")
        if not isinstance(data_type, str) or not data_type.strip():
            errors.append(f"{path}.data_type must be a non-empty string")

        if "shape" in port:
            _validate_shape(port["shape"], f"{path}.shape", errors)
        if "bounds" in port and not isinstance(port["bounds"], dict):
            errors.append(f"{path}.bounds must be a JSON object")

        ports.append(port)
    return ports


def _validate_shape(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{path} must be a list")
        return
    for index, dimension in enumerate(value):
        if isinstance(dimension, bool):
            errors.append(f"{path}[{index}] must be a positive integer or non-empty string")
        elif isinstance(dimension, int):
            if dimension <= 0:
                errors.append(f"{path}[{index}] must be a positive integer or non-empty string")
        elif isinstance(dimension, str):
            if not dimension.strip():
                errors.append(f"{path}[{index}] must be a positive integer or non-empty string")
        else:
            errors.append(f"{path}[{index}] must be a positive integer or non-empty string")
