"""Deterministic candidate, frequency, and resource acceptance gates."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any

from llm4hls.task import Task

from scoring.scoring_v3 import check_capacity, verified_available_resources


_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_INCLUDE_RE = re.compile(r"^\s*#\s*include\s*([<\"][^>\"]+[>\"])", re.MULTILINE)
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_FORBIDDEN_EMBED_RE = re.compile(
    r"\b(?:hidden|reference)\s*[/\\]|"
    r"(?:^|[\"'/\\])(?:hidden|reference)(?:[\"'/\\]|$)|"
    r"\bhidden_tb\b|\breference_code\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class InterfaceContract:
    top: str
    canonical_signature: str
    required_includes: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "top": self.top,
            "canonical_signature": self.canonical_signature,
            "required_includes": list(self.required_includes),
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class CandidateValidation:
    ok: bool
    reason: str
    fingerprint: str | None
    canonical_signature: str | None
    required_includes_present: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "fingerprint": self.fingerprint,
            "canonical_signature": self.canonical_signature,
            "required_includes_present": self.required_includes_present,
        }


@dataclass(frozen=True)
class FrequencyGate:
    ok: bool
    reason: str
    target_clock_ns: float
    candidate_clock_ns: float | None
    frequency_mhz: float | None
    minimum_frequency_mhz: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "target_clock_ns": self.target_clock_ns,
            "candidate_clock_ns": self.candidate_clock_ns,
            "frequency_mhz": self.frequency_mhz,
            "minimum_frequency_mhz": self.minimum_frequency_mhz,
        }


@dataclass(frozen=True)
class ResourceGate:
    ok: bool
    reason: str
    resources: dict[str, int]
    available: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "resources": dict(self.resources),
            "available": dict(self.available),
        }


class CandidateValidator:
    """Validate that an LLM candidate preserves the public source contract."""

    def __init__(self, contract: InterfaceContract) -> None:
        self.contract = contract

    @classmethod
    def from_task(cls, task: Task) -> "CandidateValidator":
        return cls.from_source(task.top, task.kernel_code)

    @classmethod
    def from_source(cls, top: str, starter_code: str) -> "CandidateValidator":
        """Build a contract from the immutable public starter source."""

        signature = _extract_signature(starter_code, top)
        if signature is None:
            raise ValueError(f"top function {top!r} not found in starter kernel")
        canonical = _canonical_signature(signature)
        includes = tuple(sorted(set(_INCLUDE_RE.findall(starter_code))))
        return cls(
            InterfaceContract(
                top=top,
                canonical_signature=canonical,
                required_includes=includes,
                fingerprint=_interface_fingerprint(top, canonical, includes),
            )
        )

    def validate(self, code: str) -> CandidateValidation:
        if not isinstance(code, str) or not code.strip():
            return CandidateValidation(False, "empty_candidate", None, None, False)
        if "```" in code:
            return CandidateValidation(False, "markdown_fence_in_candidate", None, None, False)
        if _FORBIDDEN_EMBED_RE.search(code):
            return CandidateValidation(False, "hidden_or_reference_embedding", None, None, False)
        if not _balanced(code, "{", "}") or not _balanced(code, "(", ")"):
            return CandidateValidation(False, "unbalanced_cpp_delimiters", None, None, False)

        signature = _extract_signature(code, self.contract.top)
        if signature is None:
            return CandidateValidation(False, "top_function_missing", None, None, False)
        canonical = _canonical_signature(signature)
        if canonical != self.contract.canonical_signature:
            return CandidateValidation(
                False,
                "top_interface_changed",
                _interface_fingerprint(
                    self.contract.top,
                    canonical,
                    tuple(sorted(set(_INCLUDE_RE.findall(code)))),
                ),
                canonical,
                False,
            )

        includes = tuple(sorted(set(_INCLUDE_RE.findall(code))))
        includes_ok = set(self.contract.required_includes).issubset(includes)
        if not includes_ok:
            return CandidateValidation(
                False,
                "required_include_removed",
                _interface_fingerprint(self.contract.top, canonical, includes),
                canonical,
                False,
            )

        fingerprint = _interface_fingerprint(self.contract.top, canonical, includes)
        return CandidateValidation(True, "passed", fingerprint, canonical, True)


def _strip_comments(text: str) -> str:
    return _COMMENT_RE.sub(" ", text)


def _extract_signature(code: str, top: str) -> str | None:
    """Return the lexical top-function declaration through its closing ``)``."""

    clean = _strip_comments(code)
    clean = re.sub(r"^\s*#.*$", " ", clean, flags=re.MULTILINE)
    for match in re.finditer(rf"\b{re.escape(top)}\s*\(", clean):
        open_paren = clean.find("(", match.start())
        close_paren = _matching_delimiter(clean, open_paren, "(", ")")
        if close_paren is None:
            continue
        tail = clean[close_paren + 1 :]
        tail_match = re.match(r"\s*(?:const\s*)?(?:noexcept\s*)?(?:->[^{{;]+)?\s*([{{;])", tail)
        if tail_match is None or tail_match.group(1) != "{":
            continue
        start = match.start()
        while start > 0 and clean[start - 1] not in ";{}":
            start -= 1
        signature = clean[start : close_paren + 1].strip()
        if signature and _IDENT_RE.search(signature):
            return signature
    return None


def _canonical_signature(signature: str) -> str:
    tokens = re.findall(
        r"::|&&|\.\.\.|[A-Za-z_]\w*|\d+|[<>\[\]\(\),*&=:+\-]",
        signature,
    )
    return " ".join(tokens)


def _interface_fingerprint(
    top: str, canonical_signature: str, includes: tuple[str, ...]
) -> str:
    payload = "\n".join((top, canonical_signature, *sorted(includes)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _matching_delimiter(
    text: str, opening_index: int, opening: str, closing: str
) -> int | None:
    depth = 0
    for index in range(opening_index, len(text)):
        char = text[index]
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def _balanced(text: str, opening: str, closing: str) -> bool:
    clean = _strip_comments(text)
    depth = 0
    for char in clean:
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def frequency_gate(report: Any, target_clock_ns: float) -> FrequencyGate:
    value = getattr(report, "clock_period_ns", None) if report is not None else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return FrequencyGate(False, "candidate_clock_missing", target_clock_ns, None, None)
    period = float(value)
    if not math.isfinite(period) or period <= 0:
        return FrequencyGate(False, "candidate_clock_invalid", target_clock_ns, period, None)
    frequency = 1000.0 / period
    if period > 10.0:
        return FrequencyGate(
            False,
            "minimum_100mhz_not_met",
            target_clock_ns,
            period,
            frequency,
        )
    return FrequencyGate(True, "passed", target_clock_ns, period, frequency)


def resource_gate(report: Any) -> ResourceGate:
    resources = dict(getattr(report, "resources", None) or {})
    available = verified_available_resources(
        getattr(report, "available", None) if report is not None else None
    )
    if not available:
        return ResourceGate(False, "resource_capacity_missing", resources, {})
    if not resources or not check_capacity(resources, available):
        return ResourceGate(False, "resource_capacity_exceeded", resources, available)
    return ResourceGate(True, "passed", resources, available)


def validation_cost(budget: Any, *, requires_cosim: bool) -> int:
    if budget is None:
        return 0
    kinds = ["csim", "synth"]
    if requires_cosim:
        kinds.append("cosim")
    costs = getattr(budget, "cost", None)
    if not isinstance(costs, dict):
        # Lightweight unit-test doubles predating the budget contract have no
        # meter. Production ToolServer instances always expose ``cost``.
        return 0
    return sum(int(costs[kind]) for kind in kinds)


def can_afford_validation(budget: Any, *, requires_cosim: bool) -> bool:
    cost = validation_cost(budget, requires_cosim=requires_cosim)
    remaining = getattr(budget, "remaining", None)
    if cost == 0 or not callable(remaining):
        return True
    return int(remaining()) >= cost
