from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.security.redaction import redact_sensitive_text

ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
PATH_RE = re.compile(r"(?<!\w)(?:/[A-Za-z0-9_.:-]+)+")
KEYWORD_RE = re.compile(
    r"\b(error|fatal|failed|failure|fail|mismatch|deadlock|timeout|timed out|"
    r"undefined|symbol|extern|did you mean|not found|cannot|warning|violation|"
    r"segmentation|stream|dataflow|fifo|linker)\b",
    re.IGNORECASE,
)
WARNING_RE = re.compile(r"\b(warning|warn)\b", re.IGNORECASE)
HIGH_SIGNAL_RE = re.compile(
    r"\b(error|fatal|undefined|symbol|extern|did you mean|not found|cannot|"
    r"mismatch|deadlock|timeout|timed out|segmentation|linker)\b",
    re.IGNORECASE,
)


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
        key_candidates: list[tuple[int, str]] = []
        warnings: list[str] = []
        seen: set[str] = set()
        truncated = False

        safe_log_text = self._safe_text(log_text)
        raw_lines = safe_log_text.splitlines()
        for raw_line in raw_lines:
            if len(raw_line) > self.max_line_chars:
                truncated = True
            normalized = self._normalize_line(raw_line)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            if WARNING_RE.search(normalized) and len(warnings) < self.max_warnings:
                warnings.append(normalized)
            elif WARNING_RE.search(normalized):
                truncated = True
            if KEYWORD_RE.search(normalized):
                key_candidates.append((len(key_candidates), normalized))

        key_candidates.sort(
            key=lambda item: (
                0 if HIGH_SIGNAL_RE.search(item[1]) else 1,
                item[0],
            )
        )
        key_lines = [line for _, line in key_candidates[: self.max_key_lines]]
        if len(key_candidates) > self.max_key_lines:
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
            missing_logs=not safe_log_text.strip(),
        )

    def _normalize_line(self, line: str) -> str:
        stripped = ANSI_RE.sub(
            "", redact_sensitive_text(self._safe_text(line))
        ).strip()
        stripped = PATH_RE.sub(self._redact_path, stripped)
        stripped = re.sub(r"\s+", " ", stripped)
        if len(stripped) > self.max_line_chars:
            stripped = stripped[: self.max_line_chars - 3].rstrip() + "..."
        return stripped

    @staticmethod
    def _safe_text(value: Any) -> str:
        """Return deterministic UTF-8-safe text for untrusted tool output."""
        if value is None:
            return ""
        if isinstance(value, bytes):
            text = value.decode("utf-8", errors="replace")
        else:
            try:
                text = str(value)
            except Exception:
                text = "<unprintable tool output>"
        return text.encode("utf-8", errors="replace").decode("utf-8")

    @staticmethod
    def _redact_path(match: re.Match[str]) -> str:
        """Redact host directories while retaining the diagnostic basename."""
        raw = match.group(0)
        basename = raw.rstrip("/").rsplit("/", 1)[-1]
        if "." in basename:
            return f"<path>/{basename}"
        return "<path>"

    def _summary(self, key_lines: list[str], fallback: str) -> str | None:
        text = key_lines[0] if key_lines else self._normalize_line(fallback)
        if not text:
            return None
        if len(text) > self.max_summary_chars:
            return text[: self.max_summary_chars - 3].rstrip() + "..."
        return text
