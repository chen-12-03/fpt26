from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from agent.llm.schemas import LLMCallRecord


class TokenLimitError(RuntimeError):
    pass


class TokenTracker:
    def __init__(
        self,
        *,
        max_call_total_tokens: int | None = None,
        max_total_tokens: int | None = None,
        persist_dir: str | Path | None = None,
    ) -> None:
        self.max_call_total_tokens = max_call_total_tokens
        self.max_total_tokens = max_total_tokens
        self.persist_dir = Path(persist_dir) if persist_dir is not None else None
        self.records: list[LLMCallRecord] = []

    def ensure_can_call(self, *, max_output_tokens: int) -> None:
        if self.max_call_total_tokens is not None and max_output_tokens > self.max_call_total_tokens:
            raise TokenLimitError(
                f"configured max output tokens {max_output_tokens} exceed single-call token limit {self.max_call_total_tokens}"
            )
        if self.max_total_tokens is not None:
            known_total = self.known_total_tokens()
            if known_total + max_output_tokens > self.max_total_tokens:
                raise TokenLimitError(
                    f"request would exceed cumulative token limit: {known_total}+{max_output_tokens}>{self.max_total_tokens}"
                )

    def record(self, record: LLMCallRecord) -> None:
        self.records.append(record)
        self._persist()

    def known_total_tokens(self) -> int:
        return sum(record.total_tokens or 0 for record in self.records)

    def summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "total_input_tokens": _sum_optional(record.input_tokens for record in self.records),
            "total_output_tokens": _sum_optional(record.output_tokens for record in self.records),
            "total_tokens": _sum_optional(record.total_tokens for record in self.records),
            "attempt_count": len(self.records),
            "unknown_usage_count": sum(1 for record in self.records if record.total_tokens is None),
            "by_purpose": {},
            "by_model": {},
        }
        for record in self.records:
            _accumulate(summary["by_purpose"], record.purpose or "unspecified", record)
            _accumulate(summary["by_model"], record.model, record)
        return summary

    def _persist(self) -> None:
        if self.persist_dir is None:
            return
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        calls_path = self.persist_dir / "calls.jsonl"
        summary_path = self.persist_dir / "token_summary.json"
        lines = [json.dumps(record.to_dict(), sort_keys=True, ensure_ascii=False) for record in self.records]
        _atomic_write_text(calls_path, "\n".join(lines) + ("\n" if lines else ""))
        _atomic_write_text(
            summary_path,
            json.dumps(self.summary(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        )


def _sum_optional(values: Any) -> int | None:
    total = 0
    seen = False
    for value in values:
        if value is None:
            continue
        total += value
        seen = True
    return total if seen else None


def _accumulate(bucket: dict[str, Any], key: str, record: LLMCallRecord) -> None:
    entry = bucket.setdefault(
        key,
        {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "attempt_count": 0,
            "unknown_usage_count": 0,
        },
    )
    entry["attempt_count"] += 1
    if record.input_tokens is not None:
        entry["input_tokens"] += record.input_tokens
    if record.output_tokens is not None:
        entry["output_tokens"] += record.output_tokens
    if record.total_tokens is not None:
        entry["total_tokens"] += record.total_tokens
    else:
        entry["unknown_usage_count"] += 1


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as file_obj:
            file_obj.write(text)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
