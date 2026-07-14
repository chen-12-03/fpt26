from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.execution.result_adapter import UnifiedToolResult


ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
PATH_RE = re.compile(r"(?<!\w)(?:/[A-Za-z0-9_.:-]+)+")
KEYWORD_RE = re.compile(
    r"\b(error|fatal|failed|failure|fail|mismatch|deadlock|timeout|timed out|"
    r"undefined|not found|cannot|warning|violation|segmentation|stream|dataflow|fifo)\b",
    re.IGNORECASE,
)
WARNING_RE = re.compile(r"\b(warning|warn)\b", re.IGNORECASE)


@dataclass(frozen=True)
class NormalizedLog:
    stage: str
    status: str
    log_paths: list[str]
    error_summary: str | None
    warnings: list[str]
    key_lines: list[str]
    truncated: bool
    missing_logs: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "log_paths": list(self.log_paths),
            "error_summary": self.error_summary,
            "warnings": list(self.warnings),
            "key_lines": list(self.key_lines),
            "truncated": self.truncated,
            "missing_logs": self.missing_logs,
        }


class LogNormalizer:
    def __init__(
        self,
        *,
        max_summary_chars: int = 500,
        max_line_chars: int = 240,
        max_key_lines: int = 40,
        max_warnings: int = 20,
    ) -> None:
        self.max_summary_chars = max_summary_chars
        self.max_line_chars = max_line_chars
        self.max_key_lines = max_key_lines
        self.max_warnings = max_warnings

    def normalize(self, result: UnifiedToolResult) -> NormalizedLog:
        log_paths = self._log_paths(result.artifacts)
        existing_files = [Path(path) for path in log_paths if Path(path).is_file()]
        key_lines: list[str] = []
        warnings: list[str] = []
        seen: set[str] = set()
        truncated = False

        for path in existing_files:
            try:
                raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for raw_line in raw_lines:
                normalized = self._normalize_line(raw_line)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                if WARNING_RE.search(normalized) and len(warnings) < self.max_warnings:
                    warnings.append(normalized)
                if KEYWORD_RE.search(normalized):
                    if len(key_lines) < self.max_key_lines:
                        key_lines.append(normalized)
                    else:
                        truncated = True

        error_summary = self._summary(key_lines, result.summary)
        return NormalizedLog(
            stage=result.stage,
            status=result.status,
            log_paths=log_paths,
            error_summary=error_summary,
            warnings=warnings,
            key_lines=key_lines,
            truncated=truncated,
            missing_logs=not existing_files,
        )

    def _normalize_line(self, line: str) -> str:
        stripped = ANSI_RE.sub("", line).strip()
        stripped = PATH_RE.sub("<path>", stripped)
        stripped = re.sub(r"\s+", " ", stripped)
        if len(stripped) > self.max_line_chars:
            stripped = stripped[: self.max_line_chars - 3].rstrip() + "..."
        return stripped

    def _summary(self, key_lines: list[str], fallback: str) -> str | None:
        text = key_lines[0] if key_lines else self._normalize_line(fallback)
        if not text:
            return None
        if len(text) > self.max_summary_chars:
            return text[: self.max_summary_chars - 3].rstrip() + "..."
        return text

    def _log_paths(self, artifacts: dict[str, Any]) -> list[str]:
        paths: list[str] = []

        def visit(key: str, value: Any) -> None:
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    visit(str(child_key), child_value)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    visit(key, item)
            elif isinstance(value, (str, Path)) and "log" in key.lower():
                paths.append(str(value))

        for key, value in artifacts.items():
            visit(str(key), value)
        return sorted(dict.fromkeys(paths))
