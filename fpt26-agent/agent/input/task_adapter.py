from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.core.task_context import TaskContext, TaskContextError


class TaskAdapterError(ValueError):
    pass


class TaskAdapter:
    @staticmethod
    def from_official_task(task: Any) -> TaskContext:
        return official_task_to_context(task)


def official_task_to_context(task: Any) -> TaskContext:
    errors: list[str] = []
    task_dir = _task_dir(task, errors)
    task_id = _string_attr(task, "id", errors)
    task_type = _string_attr(task, "type", errors)
    top = _string_attr(task, "top", errors)
    kernel_name = _kernel_name(task, errors)
    public_tb_name = _string_attr(task, "public_tb_name", errors)
    part = _string_attr(task, "part", errors)
    clock_ns = _positive_float_attr(task, "clock_ns", errors)
    budget = _positive_int_attr(task, "budget", errors)
    kernel_code = getattr(task, "kernel_code", None)
    public_tb_code = getattr(task, "public_tb_code", None)
    headers = getattr(task, "headers", {})

    if not isinstance(kernel_code, str):
        errors.append("task.kernel_code must be a string")
    if not isinstance(public_tb_code, str):
        errors.append("task.public_tb_code must be a string")
    if not isinstance(headers, dict):
        errors.append("task.headers must be a dictionary")
        headers = {}
    if errors:
        raise TaskAdapterError("; ".join(errors))

    assert task_dir is not None
    assert kernel_name is not None
    assert public_tb_name is not None

    kernel_path = _required_existing_file(task_dir, kernel_name, "kernel source")
    public_tb_path = _required_existing_file(task_dir, public_tb_name, "public testbench")

    kernel_ref = _file_ref(kernel_path, role="kernel", content=kernel_code, editable=True)
    public_tb_ref = _file_ref(public_tb_path, role="public_testbench", content=public_tb_code, editable=False)

    immutable_refs: list[dict[str, Any]] = []
    for header_name in sorted(headers):
        header_content = headers[header_name]
        if not isinstance(header_name, str) or not header_name.strip():
            raise TaskAdapterError("header file names must be non-empty strings")
        if not isinstance(header_content, str):
            raise TaskAdapterError(f"header content must be a string: {header_name}")
        header_path = _required_existing_file(task_dir, header_name, "header")
        immutable_refs.append(_file_ref(header_path, role="header", content=header_content, editable=False))

    initial_condition = getattr(task, "initial_condition", "")
    design_constraints = {"initial_condition": initial_condition} if isinstance(initial_condition, str) and initial_condition else None

    context = {
        "schema_version": "hls-ir-v2",
        "task_id": task_id,
        "task_type": task_type,
        "description": getattr(task, "description", None) if isinstance(getattr(task, "description", None), str) else None,
        "top_function": top,
        "initial_kernel": kernel_ref,
        "source_files": [kernel_ref, *immutable_refs],
        "editable_sources": [kernel_ref],
        "immutable_support_files": immutable_refs,
        "public_testbench": public_tb_ref,
        "build_files": [kernel_ref, *immutable_refs, public_tb_ref],
        "interface_contract": None,
        "numeric_tolerance": None,
        "design_constraints": design_constraints,
        "target_part": part,
        "requested_clock_ns": clock_ns,
        "resource_limits": None,
        "requires_cosim": bool(getattr(task, "requires_cosim", False)),
        "input_mode": "official_task",
        "budget": {"unified_credits": budget, "per_tool_limits": {}},
        "legacy_ir": None,
    }
    try:
        return TaskContext.from_dict(context)
    except TaskContextError as exc:
        raise TaskAdapterError(str(exc)) from exc


def _task_dir(task: Any, errors: list[str]) -> Path | None:
    value = getattr(task, "dir", None)
    if value is None:
        errors.append("task.dir is required")
        return None
    path = Path(value).resolve()
    if not path.is_dir():
        errors.append(f"task.dir does not exist: {path}")
        return None
    return path


def _kernel_name(task: Any, errors: list[str]) -> str | None:
    editable_sources = getattr(task, "editable_sources", None)
    if isinstance(editable_sources, list) and len(editable_sources) > 1:
        errors.append("multiple editable sources are not supported")
        return None
    value = getattr(task, "kernel_name", None)
    if isinstance(value, (list, tuple)):
        errors.append("multiple editable sources are not supported")
        return None
    if not isinstance(value, str) or not value.strip():
        errors.append("task.kernel_name must be a non-empty string")
        return None
    return value


def _string_attr(task: Any, name: str, errors: list[str]) -> str | None:
    value = getattr(task, name, None)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"task.{name} must be a non-empty string")
        return None
    return value


def _positive_float_attr(task: Any, name: str, errors: list[str]) -> float | None:
    value = getattr(task, name, None)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        errors.append(f"task.{name} must be a positive number")
        return None
    return float(value)


def _positive_int_attr(task: Any, name: str, errors: list[str]) -> int | None:
    value = getattr(task, name, None)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        errors.append(f"task.{name} must be a positive integer")
        return None
    return value


def _required_existing_file(task_dir: Path, file_name: str, label: str) -> Path:
    path = Path(file_name)
    if not path.is_absolute():
        path = task_dir / path
    path = path.resolve()
    if not path.is_file():
        raise TaskAdapterError(f"{label} file does not exist: {path}")
    return path


def _file_ref(path: Path, *, role: str, content: str | None, editable: bool) -> dict[str, Any]:
    return {
        "path": str(path),
        "role": role,
        "content": content,
        "editable": editable,
        "language": "c++",
    }
