from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.analysis.log_normalizer import NormalizedLog
from agent.core.task_context import TaskContext
from agent.execution.result_adapter import UnifiedToolResult


STRUCTURAL_CATEGORIES = {
    "deadlock",
    "stream_underflow",
    "stream_overflow",
    "producer_consumer_mismatch",
    "protocol_error",
}


@dataclass(frozen=True)
class CoSimDiagnosis:
    status: str
    category: str
    confidence: str
    summary: str | None
    evidence: list[str]
    affected_streams: list[str]
    artifacts: dict[str, Any]
    recommended_action: str

    @property
    def requires_structural_repair(self) -> bool:
        return self.category in STRUCTURAL_CATEGORIES

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "category": self.category,
            "confidence": self.confidence,
            "summary": self.summary,
            "evidence": list(self.evidence),
            "affected_streams": list(self.affected_streams),
            "artifacts": _json_value(self.artifacts),
            "recommended_action": self.recommended_action,
            "requires_structural_repair": self.requires_structural_repair,
        }


class CoSimAnalyzer:
    def analyze(
        self,
        task_context: TaskContext,
        cosim_result: UnifiedToolResult,
        normalized_log: NormalizedLog,
    ) -> CoSimDiagnosis:
        del task_context
        evidence = normalized_log.key_lines[:8]
        searchable = "\n".join([cosim_result.summary, *normalized_log.key_lines]).lower()
        artifacts = artifact_index(cosim_result.artifacts)

        if cosim_result.status == "pass":
            return CoSimDiagnosis(
                status="pass",
                category="none",
                confidence="high",
                summary="cosim passed",
                evidence=evidence,
                affected_streams=[],
                artifacts=artifacts,
                recommended_action="no_structural_repair_needed",
            )

        if normalized_log.missing_logs:
            return CoSimDiagnosis(
                status=cosim_result.status,
                category="unknown",
                confidence="low",
                summary="cosim log is missing",
                evidence=["tool log is missing"],
                affected_streams=[],
                artifacts=artifacts,
                recommended_action="collect_cosim_logs",
            )

        category, confidence, action = _classify(searchable, cosim_result.status)
        summary = _diagnostic_summary(normalized_log, cosim_result.summary, category)
        return CoSimDiagnosis(
            status=cosim_result.status,
            category=category,
            confidence=confidence,
            summary=summary,
            evidence=evidence or ([summary] if summary else []),
            affected_streams=_affected_streams("\n".join(evidence)),
            artifacts=artifacts,
            recommended_action=action,
        )


def artifact_index(artifacts: dict[str, Any]) -> dict[str, Any]:
    indexed: dict[str, Any] = {"run_dirs": [], "logs": [], "reports": [], "other": []}

    def add(path_text: str, key: str) -> None:
        path = Path(path_text)
        if not path.exists():
            return
        resolved = str(path)
        if path.is_dir() or "run_dir" in key:
            indexed["run_dirs"].append(resolved)
        elif "log" in key.lower():
            indexed["logs"].append(resolved)
        elif "report" in key.lower() or path.suffix in {".rpt", ".xml"}:
            indexed["reports"].append(resolved)
        else:
            indexed["other"].append(resolved)

    def visit(key: str, value: Any) -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(str(child_key), child_value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(key, item)
        elif isinstance(value, (str, Path)):
            add(str(value), key)

    for key, value in artifacts.items():
        visit(str(key), value)
    return {key: sorted(dict.fromkeys(value)) for key, value in indexed.items()}


def _classify(text: str, status: str) -> tuple[str, str, str]:
    has_timeout = status == "timeout" or re.search(r"\b(timeout|timed out)\b", text) is not None
    if _match(text, r"\b(deadlock|dataflow.*deadlock|hang|stalled|stalling)\b"):
        return "deadlock", "high", "repair_dataflow_deadlock"
    if _match(text, r"\b(underflow|read from empty|empty fifo|empty stream)\b"):
        return "stream_underflow", "high", "repair_stream_read_write_schedule"
    if _match(text, r"\b(overflow|fifo full|stream full|write blocked|blocked write)\b"):
        return "stream_overflow", "high", "repair_stream_read_write_schedule"
    if _match(text, r"\b(producer.*consumer|consumer.*producer|read.*write.*mismatch|write.*read.*mismatch)\b"):
        return "producer_consumer_mismatch", "high", "balance_producer_consumer_rates"
    if _match(text, r"\b(protocol|handshake|ap_ctrl|transaction)\b.*\b(error|fail|violation|invalid)\b"):
        return "protocol_error", "high", "repair_interface_protocol"
    if has_timeout and _match(text, r"\b(stream|fifo|dataflow|channel|deadlock|blocked|stall)\b"):
        return "deadlock", "medium", "repair_dataflow_deadlock"
    if _match(text, r"\b(mismatch|expected|actual|output differs|rtl.*fail|cosim.*fail)\b"):
        return "cosim_mismatch", "medium", "inspect_rtl_c_mismatch"
    if has_timeout:
        return "timeout", "medium", "inspect_cosim_timeout"
    return "unknown", "low", "inspect_cosim_logs"


def _diagnostic_summary(normalized_log: NormalizedLog, fallback: str, category: str) -> str | None:
    category_patterns = {
        "deadlock": r"\b(deadlock|blocked|stall|fifo|stream|dataflow|channel)\b",
        "stream_underflow": r"\b(underflow|empty fifo|empty stream|read from empty)\b",
        "stream_overflow": r"\b(overflow|fifo full|stream full|blocked write)\b",
        "producer_consumer_mismatch": r"\b(producer|consumer|read.*write|write.*read)\b",
        "protocol_error": r"\b(protocol|handshake|ap_ctrl|transaction)\b",
        "cosim_mismatch": r"\b(mismatch|expected|actual|output differs)\b",
        "timeout": r"\b(timeout|timed out)\b",
    }
    pattern = category_patterns.get(category)
    if pattern is not None:
        for line in normalized_log.key_lines:
            if re.search(pattern, line, flags=re.IGNORECASE):
                return line
    return normalized_log.error_summary or fallback


def _match(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) is not None


def _affected_streams(text: str) -> list[str]:
    names: set[str] = set()
    patterns = (
        r"\b(s_[A-Za-z_]\w*)\b",
        r"\bstream\s+['\"]?([A-Za-z_]\w*)['\"]?",
        r"\bfifo\s+['\"]?([A-Za-z_]\w*)['\"]?",
        r"\bchannel\s+['\"]?([A-Za-z_]\w*)['\"]?",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            name = match.group(1)
            if name.lower() not in {"stream", "fifo", "channel"}:
                names.add(name)
    return sorted(names)


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
