from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.core.candidate import sha256_text
from agent.core.task_context import TaskContext


@dataclass(frozen=True)
class KernelValidationResult:
    status: str
    errors: list[str]
    top_function: str
    original_signature: str | None
    candidate_signature: str | None
    kernel_sha256: str | None

    @property
    def ok(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "errors": list(self.errors),
            "top_function": self.top_function,
            "original_signature": self.original_signature,
            "candidate_signature": self.candidate_signature,
            "kernel_sha256": self.kernel_sha256,
        }


class KernelValidator:
    def __init__(self, *, max_kernel_bytes: int = 256_000) -> None:
        self.max_kernel_bytes = max_kernel_bytes

    def validate(self, task_context: TaskContext, candidate_kernel: str) -> KernelValidationResult:
        errors: list[str] = []
        top = task_context.top_function
        original_kernel = _initial_kernel(task_context)
        original_signature = _signature(original_kernel, top)
        candidate_signature = _signature(candidate_kernel, top)

        if not isinstance(candidate_kernel, str) or not candidate_kernel.strip():
            errors.append("replacement kernel must be non-empty")
        elif len(candidate_kernel.encode("utf-8")) > self.max_kernel_bytes:
            errors.append(f"replacement kernel exceeds {self.max_kernel_bytes} bytes")

        if "```" in candidate_kernel:
            errors.append("replacement kernel must not contain Markdown code fences")

        if original_signature is None:
            errors.append(f"original top function signature not found: {top}")
        if candidate_signature is None:
            errors.append(f"replacement top function signature not found: {top}")
        elif original_signature is not None and candidate_signature != original_signature:
            errors.append("top function signature changed")

        for include_name in _local_includes(candidate_kernel):
            if include_name not in _known_local_files(task_context):
                errors.append(f"replacement kernel includes unknown local file: {include_name}")

        status = "pass" if not errors else "fail"
        return KernelValidationResult(
            status=status,
            errors=errors,
            top_function=top,
            original_signature=original_signature,
            candidate_signature=candidate_signature,
            kernel_sha256=sha256_text(candidate_kernel) if isinstance(candidate_kernel, str) else None,
        )


def _initial_kernel(task_context: TaskContext) -> str:
    content = task_context.initial_kernel.get("content")
    if isinstance(content, str):
        return content
    path = task_context.initial_kernel.get("path")
    if isinstance(path, str) and path:
        return Path(path).read_text(encoding="utf-8")
    return ""


def _signature(code: str, top_function: str) -> str | None:
    stripped = _strip_comments(code)
    pattern = re.compile(
        r"([A-Za-z_][\w:<>,\s*&~]*?\b"
        + re.escape(top_function)
        + r"\s*\((?P<params>[^)]*)\))\s*(?:\{|;)",
        re.MULTILINE,
    )
    match = pattern.search(stripped)
    if not match:
        return None
    return _normalize_signature(match.group(1))


def _normalize_signature(signature: str) -> str:
    text = re.sub(r"\s+", " ", signature.strip())
    text = re.sub(r"\s*([(),*&])\s*", r"\1", text)
    return text


def _strip_comments(code: str) -> str:
    no_block = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    return re.sub(r"//.*", "", no_block)


def _local_includes(code: str) -> list[str]:
    return re.findall(r'^\s*#\s*include\s+"([^"]+)"', code, flags=re.MULTILINE)


def _known_local_files(task_context: TaskContext) -> set[str]:
    names: set[str] = set()
    for ref in task_context.build_files:
        path = ref.get("path")
        if isinstance(path, str) and path:
            names.add(Path(path).name)
    return names
