"""Unified candidate validation — the single authority for all gate checks.

Every agent (repair, structural, optimize) and pipeline stage (baseline,
evaluator) MUST use the functions and classes exported here.  Direct
CSim/Synth/CoSim calls with ad-hoc gate logic are deprecated.

This is the **only** CandidateValidator.  ``agent.validation`` is a thin
re-export compatibility layer — it must not contain independent business rules.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from agent.errors import SecurityError
from agent.models import (
    CandidateEvaluation,
    CoSimGateEvidence,
    FrequencyGateEvidence,
    InterfaceGateEvidence,
    ResourceGateEvidence,
)
from scoring.scoring_v3 import check_capacity, verified_available_resources

# ═══════════════════════════════════════════════════════════════════════════════
# Code extraction utility (was duplicated in 4 files)
# ═══════════════════════════════════════════════════════════════════════════════

_CODE_RE = re.compile(r"```(.*?)```", re.DOTALL)
_FENCE_LANGS = ("cpp", "c++", "c", "cc", "cxx")


def extract_code(text: str) -> str | None:
    """Extract kernel source from an LLM response (```cpp fenced block)."""
    blocks = [_fenced_source(match) for match in _CODE_RE.findall(text)]
    if blocks:
        return blocks[0].strip() + "\n"
    if "```" in text:
        unfenced = _unmatched_fenced_source(text).strip()
        if unfenced:
            return unfenced + "\n"
    stripped = text.strip()
    return stripped + "\n" if stripped else None


def _unmatched_fenced_source(text: str) -> str:
    marker = text.find("```")
    if marker < 0:
        return text
    content = text[marker + 3:]
    return _fenced_source(content)


def _fenced_source(content: str) -> str:
    first, separator, rest = content.partition("\n")
    first = first.rstrip("\r")
    stripped = first.strip()
    lowered = stripped.lower()
    for lang in _FENCE_LANGS:
        if lowered == lang:
            return rest
        prefix = lang + " "
        if lowered.startswith(prefix):
            after_lang = stripped[len(lang):].strip()
            if _looks_like_cpp_source(after_lang):
                return after_lang + (separator + rest if separator else "")
            return rest
    return content


def _looks_like_cpp_source(text: str) -> bool:
    return bool(text) and (
        text.lstrip().startswith("#")
        or any(token in text for token in (";", "{", "}", "(", ")"))
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Interface contract — deterministic source validation (consolidated from
# agent/validation.py)
# ═══════════════════════════════════════════════════════════════════════════════

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
    """The immutable public source contract extracted from starter code."""
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
    """Result of validating a candidate against the interface contract."""
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
    """Result of the mandatory 100 MHz timing gate."""
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
    """Result of the device-capacity gate."""
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


# ═══════════════════════════════════════════════════════════════════════════════
# Interface contract helpers (consolidated from agent/validation.py)
# ═══════════════════════════════════════════════════════════════════════════════


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
        tail = clean[close_paren + 1:]
        tail_match = re.match(r"\s*(?:const\s*)?(?:noexcept\s*)?(?:->[^{{;]+)?\s*([{{;])", tail)
        if tail_match is None or tail_match.group(1) != "{":
            continue
        start = match.start()
        while start > 0 and clean[start - 1] not in ";{}":
            start -= 1
        signature = clean[start:close_paren + 1].strip()
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


# ═══════════════════════════════════════════════════════════════════════════════
# Gate functions (consolidated from agent/validation.py)
# ═══════════════════════════════════════════════════════════════════════════════


def frequency_gate(report: Any, target_clock_ns: float) -> FrequencyGate:
    """Check that the synthesised design meets the 100 MHz minimum."""
    value = getattr(report, "clock_period_ns", None) if report is not None else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return FrequencyGate(False, "candidate_clock_missing", target_clock_ns, None, None)
    period = float(value)
    if not math.isfinite(period) or period <= 0:
        return FrequencyGate(False, "candidate_clock_invalid", target_clock_ns, period, None)
    frequency = 1000.0 / period
    if period > 10.0:
        return FrequencyGate(
            False, "minimum_100mhz_not_met", target_clock_ns, period, frequency,
        )
    return FrequencyGate(True, "passed", target_clock_ns, period, frequency)


def resource_gate(report: Any) -> ResourceGate:
    """Check that the synthesised design fits within device capacity."""
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
    """Estimate credit cost for a full validation pass."""
    if budget is None:
        return 0
    kinds = ["csim", "synth"]
    if requires_cosim:
        kinds.append("cosim")
    costs = getattr(budget, "cost", None)
    if not isinstance(costs, dict):
        return 0
    return sum(int(costs[kind]) for kind in kinds)


def can_afford_validation(budget: Any, *, requires_cosim: bool) -> bool:
    """Check whether remaining budget covers a full validation pass."""
    cost = validation_cost(budget, requires_cosim=requires_cosim)
    remaining = getattr(budget, "remaining", None)
    if cost == 0 or not callable(remaining):
        return True
    return int(remaining()) >= cost


# ═══════════════════════════════════════════════════════════════════════════════
# Validation plan
# ═══════════════════════════════════════════════════════════════════════════════

class ValidationPlan(str, Enum):
    """What gates a candidate must pass to be accepted."""
    INTERFACE_ONLY = "interface_only"
    CSIM_ONLY = "csim_only"
    CSIM_SYNTH = "csim_synth"            # + synthesizable + freq + resource
    FULL = "full"                         # + cosim (structural tasks)
    SCORING = "scoring"                   # hidden CSim + synth(cand) + synth(base) + cosim


# ═══════════════════════════════════════════════════════════════════════════════
# Interface-only validator (the "old" CandidateValidator, now embedded)
# ═══════════════════════════════════════════════════════════════════════════════


class InterfaceValidator:
    """Validate that an LLM candidate preserves the public source contract.

    This is the former ``agent.validation.CandidateValidator``, now the
    embedded interface-checking core of the unified ``CandidateValidator``.
    """

    def __init__(self, contract: InterfaceContract) -> None:
        self.contract = contract

    @classmethod
    def from_task(cls, task: Any) -> "InterfaceValidator":
        return cls.from_source(task.top, task.kernel_code)

    @classmethod
    def from_source(cls, top: str, starter_code: str) -> "InterfaceValidator":
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
        """Check *code* against the interface contract."""
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
                False, "top_interface_changed",
                _interface_fingerprint(
                    self.contract.top, canonical,
                    tuple(sorted(set(_INCLUDE_RE.findall(code)))),
                ),
                canonical, False,
            )

        includes = tuple(sorted(set(_INCLUDE_RE.findall(code))))
        includes_ok = set(self.contract.required_includes).issubset(includes)
        if not includes_ok:
            return CandidateValidation(
                False, "required_include_removed",
                _interface_fingerprint(self.contract.top, canonical, includes),
                canonical, False,
            )

        fingerprint = _interface_fingerprint(self.contract.top, canonical, includes)
        return CandidateValidation(True, "passed", fingerprint, canonical, True)


# ═══════════════════════════════════════════════════════════════════════════════
# Unified CandidateValidator — injected with ToolExecutor, owns all gate logic
# ═══════════════════════════════════════════════════════════════════════════════


class CandidateValidator:
    """Validate candidate kernels through a :class:`ValidationPlan`.

    All tool calls go through the injected ``tool_executor``.  The validator
    owns interface checking, frequency/resource gating, and CoSim verification.

    This is the **single** CandidateValidator.  It embeds ``InterfaceValidator``
    directly — it does NOT import from ``agent.validation``.
    """

    def __init__(
        self,
        task: Any,
        starter_code: str,
        *,
        tool_executor: Any = None,
    ) -> None:
        self._task = task
        self._starter_code = starter_code
        self._tool = tool_executor
        # Build the interface contract once from starter source
        self._interface = InterfaceValidator.from_source(task.top, starter_code)
        self._contract = self._interface.contract

    @classmethod
    def from_task(cls, task: Any) -> "CandidateValidator":
        """Build a validator from a Task object's public starter code."""
        return cls(task, task.kernel_code)

    @property
    def contract(self) -> InterfaceContract:
        return self._contract

    # ── Full integration: validate + record state ─────────────────────

    def validate_and_record(
        self,
        code: str,
        *,
        stage: str = "candidate",
        state: Any = None,
    ) -> CandidateEvaluation:
        """Run interface gate and return structured result.  When *state* is
        provided, results are also recorded into ``state.metadata`` for
        backward compatibility with the existing RunState-based pipeline."""
        ev = self.validate_interface(code)
        ev.stage = stage
        if state is not None:
            _record_interface_into_state(
                state,
                stage,
                ev.interface.ok,
                ev.interface.reason,
                code=code,
                source_sha256=ev.source_sha256,
                top=getattr(self._task, "top", ""),
            )
        return ev

    # ── Public API ─────────────────────────────────────────────────────

    def validate_interface(self, code: str) -> CandidateEvaluation:
        """Check only the interface/source contract (zero tool calls)."""
        result = self._interface.validate(code)
        ev = CandidateEvaluation(
            source_sha256=hashlib.sha256(code.encode("utf-8")).hexdigest(),
        )
        ev.interface = InterfaceGateEvidence(
            ok=result.ok, reason=result.reason,
            fingerprint=result.fingerprint,
            canonical_signature=result.canonical_signature,
            required_includes_present=result.required_includes_present,
        )
        if not result.ok:
            ev.fail(result.reason or "interface")
        else:
            ev.accepted = True
        return ev

    def validate(
        self,
        code: str,
        *,
        plan: ValidationPlan = ValidationPlan.CSIM_SYNTH,
        build_dir: Path | None = None,
        stage: str = "candidate",
        state: Any = None,
    ) -> CandidateEvaluation:
        """Run every gate required by *plan* and return structured results.

        When *state* is provided, results are also recorded into the legacy
        ``RunState`` for backward compatibility.
        """
        import time
        _t0 = time.monotonic()

        source_sha = hashlib.sha256(code.encode("utf-8")).hexdigest()
        ev = CandidateEvaluation(source_sha256=source_sha, stage=stage)

        # ── 0. Interface gate (always) ──────────────────────────────────
        iface = self._check_interface(code)
        ev.interface = iface
        if not iface.ok:
            ev.fail(iface.reason or "interface")
            if state is not None:
                _record_interface_into_state(state, stage, False, iface.reason)
            return ev
        if state is not None:
            _record_interface_into_state(state, stage, True, None)

        # ── 1. CSim gate ────────────────────────────────────────────────
        if plan in (ValidationPlan.CSIM_ONLY, ValidationPlan.CSIM_SYNTH,
                     ValidationPlan.FULL, ValidationPlan.SCORING):
            csim_ok = self._run_csim(code, build_dir, stage)
            ev.csim = "pass" if csim_ok else "fail"
            if state is not None:
                state.csim_ok = csim_ok
            if not csim_ok:
                ev.fail("csim")
                return ev

        # ── 2. Synth + freq + resource gates ────────────────────────────
        if plan in (ValidationPlan.CSIM_SYNTH, ValidationPlan.FULL,
                     ValidationPlan.SCORING):
            synth_report = self._run_synth(code, build_dir, stage)
            if synth_report is None:
                ev.synth = "fail"
                if state is not None:
                    state.synth_ok = False
                ev.fail("synth")
                return ev
            ev.synth = "pass"
            if state is not None:
                state.synth_ok = True

            ev.frequency = self._check_frequency(synth_report)
            if not ev.frequency.ok:
                if state is not None:
                    state.frequency_ok = False
                ev.fail(ev.frequency.reason or "frequency")
                return ev
            if state is not None:
                state.frequency_ok = True

            ev.resource = self._check_resource(synth_report)
            if not ev.resource.ok:
                if state is not None:
                    state.resource_ok = False
                ev.fail(ev.resource.reason or "resource")
                return ev
            if state is not None:
                state.resource_ok = True

            ev.synth_latency = _latency_from_report(synth_report)
            ev.synth_ii = getattr(synth_report, "interval_max", None)
            ev.synth_clock_ns = getattr(synth_report, "clock_period_ns", None)
            ev.synth_resources = dict(getattr(synth_report, "resources", {}) or {})

            # Record synth into legacy state
            if state is not None:
                _record_synth_into_state(state, stage, synth_report, ev)

        # ── 3. CoSim gate (only for structural tasks) ──────────────────
        requires_cosim = getattr(self._task, "requires_cosim", False)
        if plan == ValidationPlan.FULL and requires_cosim:
            cosim_ok, cosim_report = self._run_cosim_full(code, build_dir, stage)
            ev.cosim = CoSimGateEvidence(
                ok=cosim_ok,
                source_sha256=source_sha,
                latency_max=getattr(cosim_report, "latency_max", None) if cosim_report else None,
            )
            if state is not None:
                state.cosim_ok = cosim_ok
                _record_cosim_into_state(state, stage, cosim_ok, source_sha, cosim_report)
            if not cosim_ok:
                ev.fail("cosim")
                return ev

        # ── 4. Mark fully verified in legacy state ────────────────────
        ev.accepted = True
        ev.elapsed_s = round(time.monotonic() - _t0, 3)
        if state is not None:
            _mark_fully_verified(state)
        return ev

    # ── Gate implementations ────────────────────────────────────────────

    def _check_interface(self, code: str) -> InterfaceGateEvidence:
        result = self._interface.validate(code)
        return InterfaceGateEvidence(
            ok=result.ok, reason=result.reason,
            fingerprint=result.fingerprint,
            canonical_signature=result.canonical_signature,
            required_includes_present=result.required_includes_present,
        )

    def _run_csim(self, code: str, build_dir: Path | None, stage: str) -> bool:
        if self._tool is None:
            return False
        d = build_dir or Path("/tmp")
        try:
            files = self._task.assemble(code, self._task.public_tb_code,
                                        self._task.public_tb_name)
        except AttributeError:
            files = {self._task.kernel_name: code}
        try:
            r = self._tool.csim(d / f"{stage}_csim", files, self._task.top,
                               part=self._task.part, clock_ns=self._task.clock_ns)
            return bool(getattr(r, "ok", False))
        except Exception:
            return False

    def _run_synth(self, code: str, build_dir: Path | None, stage: str) -> Any | None:
        if self._tool is None:
            return None
        d = build_dir or Path("/tmp")
        files = dict(getattr(self._task, "headers", {}))
        files[self._task.kernel_name] = code
        try:
            r = self._tool.synth(d / f"{stage}_synth", files,
                                synth_sources=[self._task.kernel_name],
                                top=self._task.top, part=self._task.part,
                                clock_ns=self._task.clock_ns)
            if getattr(r, "ok", False) and getattr(r, "report", None) is not None:
                return r.report
        except Exception:
            pass
        return None

    def _run_cosim_full(self, code: str, build_dir: Path | None, stage: str) -> tuple[bool, Any]:
        """Run CoSim and return (passed, cosim_report)."""
        if self._tool is None:
            return False, None
        d = build_dir or Path("/tmp")
        try:
            files = self._task.assemble(code, self._task.public_tb_code,
                                        self._task.public_tb_name)
        except AttributeError:
            files = {self._task.kernel_name: code}
        try:
            r = self._tool.cosim(d / f"{stage}_cosim", files,
                                synth_sources=[self._task.kernel_name],
                                tb_sources=[getattr(self._task, "public_tb_name", "tb.cpp")],
                                top=self._task.top, part=self._task.part,
                                clock_ns=self._task.clock_ns)
            payload = getattr(r, "cosim", None)
            passed = bool(getattr(r, "ok", False) and payload is not None
                         and getattr(payload, "passed", False))
            return passed, payload
        except Exception:
            return False, None

    def _check_frequency(self, report: Any) -> FrequencyGateEvidence:
        g = frequency_gate(report, self._task.clock_ns)
        return FrequencyGateEvidence(
            ok=g.ok, reason=g.reason,
            target_clock_ns=g.target_clock_ns,
            candidate_clock_ns=g.candidate_clock_ns,
            frequency_mhz=g.frequency_mhz,
        )

    def _check_resource(self, report: Any) -> ResourceGateEvidence:
        g = resource_gate(report)
        return ResourceGateEvidence(
            ok=g.ok, reason=g.reason,
            resources=g.resources, available=g.available,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Legacy state recording helpers (write into RunState.metadata)
# ═══════════════════════════════════════════════════════════════════════════════

def _record_interface_into_state(
    state: Any,
    stage: str,
    ok: bool,
    reason: str | None,
    *,
    code: str | None = None,
    source_sha256: str | None = None,
    top: str = "",
) -> None:
    if not isinstance(getattr(state, "metadata", None), dict):
        state.metadata = {}
    record = {"stage": stage, "ok": ok, "reason": reason}
    if code is not None:
        record["source_diagnostics"] = _source_diagnostics(
            code, source_sha256=source_sha256, top=top
        )
    state.metadata.setdefault("interface_validations", []).append(record)
    state.interface_ok = ok
    state.metadata["interface_gate"] = record


def _source_diagnostics(
    code: str,
    *,
    source_sha256: str | None,
    top: str,
) -> dict[str, Any]:
    stripped = code.strip()
    fence_offsets = [match.start() for match in re.finditer(r"```", code)]
    return {
        "source_sha256": source_sha256,
        "char_count": len(code),
        "line_count": code.count("\n") + (1 if code else 0),
        "markdown_fence_count": len(fence_offsets),
        "first_markdown_fence_offset": (
            fence_offsets[0] if fence_offsets else None
        ),
        "last_markdown_fence_offset": (
            fence_offsets[-1] if fence_offsets else None
        ),
        "starts_with_markdown_fence": stripped.startswith("```"),
        "ends_with_markdown_fence": stripped.endswith("```"),
        "has_top_function_token": bool(
            top and re.search(rf"\b{re.escape(top)}\s*\(", code)
        ),
    }


def _record_synth_into_state(state: Any, stage: str, report: Any, ev: CandidateEvaluation) -> None:
    if not isinstance(getattr(state, "metadata", None), dict):
        state.metadata = {}
    freq_d = ev.frequency.to_dict() if ev.frequency else {}
    res_d = ev.resource.to_dict() if ev.resource else {}
    state.metadata.setdefault("synth_gate_history", []).append({
        "stage": stage, "frequency": freq_d, "resource": res_d,
    })
    state.frequency_ok = ev.frequency.ok if ev.frequency else False
    state.resource_ok = ev.resource.ok if ev.resource else False
    state.metadata["frequency_gate"] = freq_d
    state.metadata["resource_gate"] = res_d
    state.metadata["best_synth_metrics"] = {
        "stage": stage,
        "latency_worst": ev.synth_latency,
        "latency_avg": ev.synth_latency,
        "interval_max": ev.synth_ii,
        "clock_period_ns": ev.synth_clock_ns,
        "frequency_mhz": ev.frequency.frequency_mhz if ev.frequency else None,
        "resources": ev.synth_resources,
        "available": ev.resource.available if ev.resource else {},
        "pipeline_type": getattr(report, "pipeline_type", None),
        "loop_metrics": [dict(item) for item in (getattr(report, "loop_metrics", None) or [])],
    }


def _record_cosim_into_state(state: Any, stage: str, passed: bool, source_sha: str,
                              cosim_report: Any) -> None:
    if not isinstance(getattr(state, "metadata", None), dict):
        state.metadata = {}
    record = {
        "stage": stage, "ok": passed,
        "source_sha256": source_sha,
        "latency_min": getattr(cosim_report, "latency_min", None),
        "latency_avg": getattr(cosim_report, "latency_avg", None),
        "latency_max": getattr(cosim_report, "latency_max", None),
    }
    state.metadata.setdefault("cosim_gate_history", []).append(record)
    state.cosim_ok = passed
    state.metadata["cosim_gate"] = record


def _mark_fully_verified(state: Any) -> None:
    if (
        getattr(state, "interface_ok", False)
        and getattr(state, "csim_ok", False)
        and getattr(state, "synth_ok", False)
        and getattr(state, "frequency_ok", False)
        and getattr(state, "resource_ok", False)
        and (not getattr(getattr(state, "task", None), "requires_cosim", False)
             or getattr(state, "cosim_ok", False))
    ):
        state.last_verified_kernel = state.kernel
        if isinstance(getattr(state, "metadata", None), dict):
            state.metadata["last_verified_kernel_stage"] = "public_acceptance"


# ═══════════════════════════════════════════════════════════════════════════════
# Utility
# ═══════════════════════════════════════════════════════════════════════════════

def _latency_from_report(report: Any) -> int | None:
    """Extract worst-case latency from a synthesis report."""
    if report is None:
        return None
    return (
        report.latency_worst
        if getattr(report, "latency_worst", None) is not None
        else getattr(report, "latency_avg", None)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Backward-compatible re-exports for agents migrating from workflow.py
# ═══════════════════════════════════════════════════════════════════════════════

def validate_candidate(
    state: Any, code: str, *, stage: str, current_best: bool = True,
) -> bool:
    """Interface-gate check with RunState recording.  Import from here, not workflow."""
    if not isinstance(getattr(state, "metadata", None), dict):
        state.metadata = {}
    had_interface_ok = hasattr(state, "interface_ok")
    previous_interface_ok = getattr(state, "interface_ok", None)
    had_interface_gate = "interface_gate" in state.metadata
    previous_interface_gate = state.metadata.get("interface_gate")
    task = getattr(state, "task", None)
    starter = getattr(task, "kernel_code", None) if task else None
    if not starter:
        starter = getattr(state, "kernel", "")
    v = CandidateValidator(task, starter)
    ev = v.validate_and_record(code, stage=stage, state=state)
    if current_best:
        state.interface_ok = ev.interface.ok
        state.metadata["interface_gate"] = {
            "stage": stage, "ok": ev.interface.ok, "reason": ev.interface.reason,
        }
    else:
        if had_interface_ok:
            state.interface_ok = previous_interface_ok
        elif hasattr(state, "interface_ok"):
            delattr(state, "interface_ok")
        if had_interface_gate:
            state.metadata["interface_gate"] = previous_interface_gate
        else:
            state.metadata.pop("interface_gate", None)
    if not ev.interface.ok:
        if hasattr(state, "log"):
            state.log(f"{stage}: interface gate FAIL ({ev.interface.reason})")
    return ev.interface.ok


def record_synth_gates(
    state: Any, result: Any, *, stage: str, current_best: bool = True,
) -> bool:
    """Synth/freq/resource gate recording.  Import from here, not workflow."""
    if not isinstance(getattr(state, "metadata", None), dict):
        state.metadata = {}
    freq = frequency_gate(result.report if getattr(result, "ok", False) else None,
                          state.task.clock_ns)
    capacity = resource_gate(result.report if getattr(result, "ok", False) else None)
    state.metadata.setdefault("synth_gate_history", []).append({
        "stage": stage, "frequency": freq.to_dict(), "resource": capacity.to_dict(),
    })
    if current_best:
        state.frequency_ok = freq.ok
        state.resource_ok = capacity.ok
        state.metadata["frequency_gate"] = freq.to_dict()
        state.metadata["resource_gate"] = capacity.to_dict()
        if getattr(result, "ok", False) and getattr(result, "report", None) is not None:
            state.best_synth_result = result
            rp = result.report
            state.metadata["best_synth_metrics"] = {
                "stage": stage,
                "latency_worst": getattr(rp, "latency_worst", None),
                "latency_avg": getattr(rp, "latency_avg", None),
                "interval_max": getattr(rp, "interval_max", None),
                "clock_period_ns": getattr(rp, "clock_period_ns", None),
                "frequency_mhz": freq.frequency_mhz,
                "resources": dict(getattr(rp, "resources", None) or {}),
                "available": dict(capacity.available),
                "pipeline_type": getattr(rp, "pipeline_type", None),
                "loop_metrics": [dict(item) for item in (getattr(rp, "loop_metrics", None) or [])],
            }
    return bool(getattr(result, "ok", False) and freq.ok and capacity.ok)


def record_cosim_gate(
    state: Any, result: Any, *, stage: str, current_best: bool = True,
    source_code: str | None = None,
) -> bool:
    """CoSim gate recording.  Import from here, not workflow."""
    if not isinstance(getattr(state, "metadata", None), dict):
        state.metadata = {}
    payload = getattr(result, "cosim", None)
    passed = bool(getattr(result, "ok", False) and payload is not None
                  and getattr(payload, "passed", False))
    record = {
        "stage": stage, "ok": passed,
        "phase": getattr(result, "phase", "unknown"),
        "source_sha256": hashlib.sha256(
            (state.kernel if source_code is None else source_code).encode("utf-8")
        ).hexdigest(),
        "latency_min": getattr(payload, "latency_min", None),
        "latency_avg": getattr(payload, "latency_avg", None),
        "latency_max": getattr(payload, "latency_max", None),
    }
    state.metadata.setdefault("cosim_gate_history", []).append(record)
    if current_best:
        state.cosim_ok = passed
        state.metadata["cosim_gate"] = record
    return passed


def mark_fully_verified(state: Any) -> None:
    """Mark the current kernel as fully verified.  Import from here, not workflow."""
    _mark_fully_verified(state)
