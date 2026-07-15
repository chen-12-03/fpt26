from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


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

    def normalize(self, kind: str, phase: str, log_text: str) -> NormalizedLog:
        """Normalize a tool result's log for LLM prompt consumption.

        Args:
            kind: Tool kind (csim/synth/cosim).
            phase: Tool phase (pass/compile_error/runtime_fail/...).
            log_text: Raw log output from the tool run.
        """
        key_lines: list[str] = []
        warnings: list[str] = []
        seen: set[str] = set()
        truncated = False

        raw_lines = (log_text or "").splitlines()
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

        error_summary = self._summary(key_lines, phase)
        return NormalizedLog(
            stage=kind,
            status=phase,
            log_paths=["<tool log>"],
            error_summary=error_summary,
            warnings=warnings,
            key_lines=key_lines,
            truncated=truncated,
            missing_logs=not log_text or not log_text.strip(),
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

