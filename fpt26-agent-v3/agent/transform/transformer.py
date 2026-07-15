from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any

from llm4hls.task import Task
from agent.transform.actions import TransformAction


class TransformError(ValueError):
    pass


@dataclass(frozen=True)
class LoopInfo:
    target: str
    index: int
    label: str | None
    iterator: str | None
    bound: str | None
    constant_bound: int | None
    start: int
    body_start: int
    end: int
    has_pipeline: bool
    has_unroll: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "index": self.index,
            "label": self.label,
            "iterator": self.iterator,
            "bound": self.bound,
            "constant_bound": self.constant_bound,
            "has_pipeline": self.has_pipeline,
            "has_unroll": self.has_unroll,
        }


@dataclass(frozen=True)
class TransformResult:
    status: str
    kernel_code: str | None
    action: TransformAction
    diff_patch: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "kernel_code": self.kernel_code,
            "action": self.action.to_dict(),
            "diff_patch": self.diff_patch,
            "error": self.error,
        }


class DeterministicTransformer:
    def discover_loops(self, kernel_code: str) -> list[LoopInfo]:
        return _discover_loops(kernel_code)

    def discover_array_parameters(self, task: Task, kernel_code: str) -> list[str]:
        signature = _function_signature_text(kernel_code, task.top)
        if signature is None:
            return []
        params = _parameter_text(signature)
        arrays: list[str] = []
        for param in _split_params(params):
            match = re.search(r"\b([A-Za-z_]\w*)\s*\[[^\]]*\]", param)
            if match:
                arrays.append(match.group(1))
        return arrays

    def apply(
        self,
        task: Task,
        kernel_code: str,
        action: TransformAction,
    ) -> TransformResult:
        try:
            if action.action_type in {"pipeline_loop", "unroll_loop"}:
                transformed = self._apply_loop_action(kernel_code, action)
            elif action.action_type == "array_partition":
                transformed = self._apply_array_partition(task, kernel_code, action)
            else:
                raise TransformError(f"unsupported action_type: {action.action_type}")
        except TransformError as exc:
            return TransformResult("fail", None, action, "", str(exc))

        if transformed == kernel_code:
            return TransformResult("fail", None, action, "", "transform produced no code change")
        return TransformResult(
            "pass",
            transformed,
            action,
            _diff(kernel_code, transformed),
            None,
        )

    def _apply_loop_action(self, kernel_code: str, action: TransformAction) -> str:
        loops = [loop for loop in _discover_loops(kernel_code) if loop.target == action.target]
        if len(loops) != 1:
            raise TransformError(f"could not find unique loop target: {action.target}")
        loop = loops[0]
        body = kernel_code[loop.body_start : loop.end]
        pragma = _loop_pragma(action)
        _reject_loop_conflicts(body, action, pragma)
        return _insert_after_open_brace(kernel_code, loop.body_start, pragma)

    def _apply_array_partition(
        self,
        task: Task,
        kernel_code: str,
        action: TransformAction,
    ) -> str:
        arrays = self.discover_array_parameters(task, kernel_code)
        if action.target not in arrays:
            raise TransformError(f"array partition target is not a top-level array parameter: {action.target}")
        function_open = _function_open_brace(kernel_code, task.top)
        if function_open is None:
            raise TransformError(f"top function body not found: {task.top}")
        function_end = _matching_brace(kernel_code, function_open)
        if function_end is None:
            raise TransformError("top function body has unbalanced braces")
        function_body = kernel_code[function_open + 1 : function_end]
        pragma = (
            f"#pragma HLS ARRAY_PARTITION variable={action.target} "
            f"{action.partition_mode} factor={action.factor} dim={action.dimension}"
        )
        _reject_array_partition_conflicts(function_body, action, pragma)
        return _insert_after_open_brace(kernel_code, function_open + 1, pragma)


def _discover_loops(kernel_code: str) -> list[LoopInfo]:
    loop_re = re.compile(
        r"(?P<label>(?:[A-Za-z_]\w*\s*:\s*)?)"
        r"for\s*\((?P<init>[^;]*);(?P<cond>[^;]*);(?P<inc>[^)]*)\)\s*\{",
        re.MULTILINE,
    )
    loops: list[LoopInfo] = []
    for match in loop_re.finditer(kernel_code):
        open_brace = match.end() - 1
        end = _matching_brace(kernel_code, open_brace)
        if end is None:
            continue
        index = len(loops) + 1
        label = match.group("label").strip().rstrip(":").strip() or None
        target = label or f"loop_{index}"
        iterator, bound, constant_bound = _loop_bounds(match.group("init"), match.group("cond"))
        body = kernel_code[match.end() : end]
        loops.append(
            LoopInfo(
                target=target,
                index=index,
                label=label,
                iterator=iterator,
                bound=bound,
                constant_bound=constant_bound,
                start=match.start(),
                body_start=match.end(),
                end=end,
                has_pipeline=bool(re.search(r"#\s*pragma\s+HLS\s+PIPELINE\b", body)),
                has_unroll=bool(re.search(r"#\s*pragma\s+HLS\s+UNROLL\b", body)),
            )
        )
    return loops


def _loop_bounds(init: str, cond: str) -> tuple[str | None, str | None, int | None]:
    init_match = re.search(r"\b([A-Za-z_]\w*)\s*=", init)
    iterator = init_match.group(1) if init_match else None
    if iterator is None:
        return None, None, None
    cond_match = re.search(r"\b" + re.escape(iterator) + r"\s*(<|<=)\s*([A-Za-z_]\w*|\d+)\b", cond)
    if not cond_match:
        return iterator, None, None
    bound = cond_match.group(2)
    constant_bound = int(bound) if bound.isdigit() else None
    if constant_bound is not None and cond_match.group(1) == "<=":
        constant_bound += 1
    return iterator, bound, constant_bound


def _loop_pragma(action: TransformAction) -> str:
    if action.action_type == "pipeline_loop":
        return f"#pragma HLS PIPELINE II={action.ii}"
    if action.action_type == "unroll_loop":
        return f"#pragma HLS UNROLL factor={action.factor}"
    raise TransformError(f"not a loop action: {action.action_type}")


def _reject_loop_conflicts(body: str, action: TransformAction, pragma: str) -> None:
    if action.action_type == "pipeline_loop":
        existing = re.findall(r"#\s*pragma\s+HLS\s+PIPELINE[^\n]*", body)
        if existing:
            if any(_normalize_pragma(line) == _normalize_pragma(pragma) for line in existing):
                raise TransformError("equivalent PIPELINE pragma already exists")
            raise TransformError("conflicting PIPELINE pragma already exists")
    if action.action_type == "unroll_loop":
        existing = re.findall(r"#\s*pragma\s+HLS\s+UNROLL[^\n]*", body)
        if existing:
            if any(_normalize_pragma(line) == _normalize_pragma(pragma) for line in existing):
                raise TransformError("equivalent UNROLL pragma already exists")
            raise TransformError("conflicting UNROLL pragma already exists")


def _reject_array_partition_conflicts(body: str, action: TransformAction, pragma: str) -> None:
    existing = re.findall(
        r"#\s*pragma\s+HLS\s+ARRAY_PARTITION[^\n]*\bvariable\s*=\s*" + re.escape(action.target) + r"\b[^\n]*",
        body,
    )
    if existing:
        if any(_normalize_pragma(line) == _normalize_pragma(pragma) for line in existing):
            raise TransformError("equivalent ARRAY_PARTITION pragma already exists")
        raise TransformError("conflicting ARRAY_PARTITION pragma already exists")


def _insert_after_open_brace(kernel_code: str, insert_pos: int, pragma: str) -> str:
    line_start = kernel_code.rfind("\n", 0, insert_pos) + 1
    base_indent = re.match(r"\s*", kernel_code[line_start:insert_pos]).group(0)
    indent = base_indent + "    "
    insertion = "\n" + indent + pragma
    return kernel_code[:insert_pos] + insertion + kernel_code[insert_pos:]


def _matching_brace(text: str, open_brace: int) -> int | None:
    depth = 0
    for index in range(open_brace, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _function_open_brace(kernel_code: str, top_function: str) -> int | None:
    signature = _function_signature_text(kernel_code, top_function)
    if signature is None:
        return None
    start = kernel_code.find(signature)
    if start < 0:
        return None
    open_index = kernel_code.find("{", start + len(signature))
    return open_index if open_index >= 0 else None


def _function_signature_text(kernel_code: str, top_function: str) -> str | None:
    pattern = re.compile(
        r"[A-Za-z_][\w:<>,\s*&~]*?\b"
        + re.escape(top_function)
        + r"\s*\([^)]*\)\s*(?:\{|;)",
        re.MULTILINE,
    )
    match = pattern.search(kernel_code)
    if not match:
        return None
    text = match.group(0)
    return text[:-1].rstrip() if text.endswith("{") or text.endswith(";") else text


def _parameter_text(signature: str) -> str:
    start = signature.find("(")
    end = signature.rfind(")")
    if start < 0 or end < start:
        return ""
    return signature[start + 1 : end]


def _split_params(params: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in params:
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _normalize_pragma(pragma: str) -> str:
    return re.sub(r"\s+", " ", pragma.strip()).lower()


def _diff(before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="before/kernel.cpp",
            tofile="after/kernel.cpp",
        )
    )
