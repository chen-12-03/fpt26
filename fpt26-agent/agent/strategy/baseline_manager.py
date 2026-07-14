from __future__ import annotations

import hashlib
from pathlib import Path

from agent.core.task_context import TaskContext


class BaselineManager:
    """Return the official initial kernel unchanged."""

    def initial_kernel(self, task_context: TaskContext) -> str:
        content = task_context.initial_kernel.get("content")
        if isinstance(content, str):
            return content
        path_text = task_context.initial_kernel.get("path")
        if not isinstance(path_text, str) or not path_text:
            raise ValueError("initial kernel must provide content or a readable path")
        return Path(path_text).read_text(encoding="utf-8")

    def sha256(self, kernel_code: str) -> str:
        return hashlib.sha256(kernel_code.encode("utf-8")).hexdigest()
