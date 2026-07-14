from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALLOWED_TASK_TYPES = {"generate", "repair", "optimize", "mixed", "synth_fix", "structural", "unknown"}
ALLOWED_INPUT_MODES = {"official_task", "existing_code", "natural_language"}


class TaskContextError(ValueError):
    pass


@dataclass(frozen=True)
class TaskContext:
    schema_version: str
    task_id: str
    task_type: str
    description: str | None
    top_function: str
    initial_kernel: dict[str, Any]
    source_files: list[dict[str, Any]]
    editable_sources: list[dict[str, Any]]
    immutable_support_files: list[dict[str, Any]]
    public_testbench: dict[str, Any] | None
    build_files: list[dict[str, Any]]
    interface_contract: dict[str, Any] | None
    numeric_tolerance: dict[str, Any] | None
    design_constraints: dict[str, Any] | None
    target_part: str
    requested_clock_ns: float | None
    resource_limits: dict[str, Any] | None
    requires_cosim: bool
    input_mode: str
    budget: dict[str, Any]
    legacy_ir: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskContext":
        normalized = validate_task_context_dict(data)
        return cls(
            schema_version=normalized["schema_version"],
            task_id=normalized["task_id"],
            task_type=normalized["task_type"],
            description=normalized["description"],
            top_function=normalized["top_function"],
            initial_kernel=deepcopy(normalized["initial_kernel"]),
            source_files=deepcopy(normalized["source_files"]),
            editable_sources=deepcopy(normalized["editable_sources"]),
            immutable_support_files=deepcopy(normalized["immutable_support_files"]),
            public_testbench=deepcopy(normalized["public_testbench"]),
            build_files=deepcopy(normalized["build_files"]),
            interface_contract=deepcopy(normalized["interface_contract"]),
            numeric_tolerance=deepcopy(normalized["numeric_tolerance"]),
            design_constraints=deepcopy(normalized["design_constraints"]),
            target_part=normalized["target_part"],
            requested_clock_ns=normalized["requested_clock_ns"],
            resource_limits=deepcopy(normalized["resource_limits"]),
            requires_cosim=normalized["requires_cosim"],
            input_mode=normalized["input_mode"],
            budget=deepcopy(normalized["budget"]),
            legacy_ir=deepcopy(normalized.get("legacy_ir")),
        )

    def to_dict(self) -> dict[str, Any]:
        return validate_task_context_dict(
            {
                "schema_version": self.schema_version,
                "task_id": self.task_id,
                "task_type": self.task_type,
                "description": self.description,
                "top_function": self.top_function,
                "initial_kernel": deepcopy(self.initial_kernel),
                "source_files": deepcopy(self.source_files),
                "editable_sources": deepcopy(self.editable_sources),
                "immutable_support_files": deepcopy(self.immutable_support_files),
                "public_testbench": deepcopy(self.public_testbench),
                "build_files": deepcopy(self.build_files),
                "interface_contract": deepcopy(self.interface_contract),
                "numeric_tolerance": deepcopy(self.numeric_tolerance),
                "design_constraints": deepcopy(self.design_constraints),
                "target_part": self.target_part,
                "requested_clock_ns": self.requested_clock_ns,
                "resource_limits": deepcopy(self.resource_limits),
                "requires_cosim": self.requires_cosim,
                "input_mode": self.input_mode,
                "budget": deepcopy(self.budget),
                "legacy_ir": deepcopy(self.legacy_ir),
            }
        )

    def save(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_task_context_dict(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(data, dict):
        raise TaskContextError("TaskContext root must be a JSON object")

    schema_version = _require_non_empty_string(data, "schema_version", errors)
    if schema_version and schema_version != "hls-ir-v2":
        errors.append(f"schema_version must be 'hls-ir-v2', got {schema_version!r}")
    task_id = _require_non_empty_string(data, "task_id", errors)
    task_type = _require_non_empty_string(data, "task_type", errors)
    if task_type and task_type not in ALLOWED_TASK_TYPES:
        errors.append(f"task_type must be one of: {', '.join(sorted(ALLOWED_TASK_TYPES))}")
    description = _optional_string(data, "description", errors)
    top_function = _require_non_empty_string(data, "top_function", errors)
    initial_kernel = _validate_file_ref(data.get("initial_kernel"), "initial_kernel", errors, allow_none=False)
    source_files = _validate_file_ref_list(data.get("source_files"), "source_files", errors)
    editable_sources = _validate_file_ref_list(data.get("editable_sources"), "editable_sources", errors)
    immutable_support_files = _validate_file_ref_list(
        data.get("immutable_support_files"), "immutable_support_files", errors
    )
    public_testbench = _validate_file_ref(data.get("public_testbench"), "public_testbench", errors, allow_none=True)
    build_files = _validate_file_ref_list(data.get("build_files"), "build_files", errors)
    interface_contract = _optional_object(data, "interface_contract", errors)
    numeric_tolerance = _optional_object(data, "numeric_tolerance", errors)
    design_constraints = _optional_object(data, "design_constraints", errors)
    target_part = _require_non_empty_string(data, "target_part", errors)
    requested_clock_ns = _optional_positive_number(data, "requested_clock_ns", errors)
    resource_limits = _optional_object(data, "resource_limits", errors)
    requires_cosim = _require_bool(data, "requires_cosim", errors)
    input_mode = _require_non_empty_string(data, "input_mode", errors)
    if input_mode and input_mode not in ALLOWED_INPUT_MODES:
        errors.append(f"input_mode must be one of: {', '.join(sorted(ALLOWED_INPUT_MODES))}")
    budget = _validate_budget(data.get("budget"), errors)
    legacy_ir = _optional_object(data, "legacy_ir", errors) if "legacy_ir" in data else None

    if editable_sources is not None and len(editable_sources) > 1:
        errors.append("multiple editable sources are not supported")

    if errors:
        raise TaskContextError("; ".join(errors))

    return {
        "schema_version": schema_version,
        "task_id": task_id,
        "task_type": task_type,
        "description": description,
        "top_function": top_function,
        "initial_kernel": initial_kernel,
        "source_files": source_files,
        "editable_sources": editable_sources,
        "immutable_support_files": immutable_support_files,
        "public_testbench": public_testbench,
        "build_files": build_files,
        "interface_contract": interface_contract,
        "numeric_tolerance": numeric_tolerance,
        "design_constraints": design_constraints,
        "target_part": target_part,
        "requested_clock_ns": requested_clock_ns,
        "resource_limits": resource_limits,
        "requires_cosim": requires_cosim,
        "input_mode": input_mode,
        "budget": budget,
        "legacy_ir": legacy_ir,
    }


def _require_non_empty_string(data: dict[str, Any], field: str, errors: list[str]) -> str | None:
    if field not in data:
        errors.append(f"{field} is required")
        return None
    value = data[field]
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be a non-empty string")
        return None
    return value


def _optional_string(data: dict[str, Any], field: str, errors: list[str]) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append(f"{field} must be null or a string")
        return None
    return value


def _optional_object(data: dict[str, Any], field: str, errors: list[str]) -> dict[str, Any] | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append(f"{field} must be null or a JSON object")
        return None
    return deepcopy(value)


def _optional_positive_number(data: dict[str, Any], field: str, errors: list[str]) -> float | None:
    value = data.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        errors.append(f"{field} must be null or a positive number")
        return None
    return float(value)


def _require_bool(data: dict[str, Any], field: str, errors: list[str]) -> bool | None:
    if field not in data:
        errors.append(f"{field} is required")
        return None
    value = data[field]
    if not isinstance(value, bool):
        errors.append(f"{field} must be a boolean")
        return None
    return value


def _validate_file_ref_list(value: Any, field: str, errors: list[str]) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        errors.append(f"{field} must be a list")
        return None
    refs: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        ref = _validate_file_ref(item, f"{field}[{index}]", errors, allow_none=False)
        if ref is not None:
            refs.append(ref)
    return refs


def _validate_file_ref(
    value: Any,
    field: str,
    errors: list[str],
    *,
    allow_none: bool,
) -> dict[str, Any] | None:
    if value is None:
        if not allow_none:
            errors.append(f"{field} must be a JSON object")
        return None
    if not isinstance(value, dict):
        errors.append(f"{field} must be a JSON object")
        return None
    path = value.get("path")
    if path is not None and (not isinstance(path, str) or not path.strip()):
        errors.append(f"{field}.path must be null or a non-empty string")
    content = value.get("content")
    if content is not None and not isinstance(content, str):
        errors.append(f"{field}.content must be null or a string")
    role = value.get("role")
    if role is not None and (not isinstance(role, str) or not role.strip()):
        errors.append(f"{field}.role must be null or a non-empty string")
    return deepcopy(value)


def _validate_budget(value: Any, errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append("budget must be a JSON object")
        return None
    unified = value.get("unified_credits")
    if unified is not None and (isinstance(unified, bool) or not isinstance(unified, int) or unified <= 0):
        errors.append("budget.unified_credits must be null or a positive integer")
    per_tool = value.get("per_tool_limits")
    if not isinstance(per_tool, dict):
        errors.append("budget.per_tool_limits must be a JSON object")
        per_tool = {}
    else:
        for key, limit in per_tool.items():
            if not isinstance(key, str) or not key.strip():
                errors.append("budget.per_tool_limits keys must be non-empty strings")
            if limit is not None and (
                isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
            ):
                errors.append(f"budget.per_tool_limits.{key} must be null or a non-negative integer")
    return {"unified_credits": unified, "per_tool_limits": deepcopy(per_tool)}
