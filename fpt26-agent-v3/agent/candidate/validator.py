"""Unified candidate validation — the single authority for all gate checks.

Every agent (repair, structural, optimize) and pipeline stage (baseline,
evaluator) must use :class:`CandidateValidator` to check a proposed kernel.
Direct CSim/Synth/CoSim calls with ad-hoc gate logic are deprecated.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from agent.models import (
    CandidateEvaluation,
    CoSimGateEvidence,
    FrequencyGateEvidence,
    InterfaceGateEvidence,
    ResourceGateEvidence,
)
from agent.errors import SecurityError


# ── Validation plan ──────────────────────────────────────────────────────────

class ValidationPlan(str, Enum):
    """What gates a candidate must pass to be accepted."""
    CSIM_ONLY = "csim_only"               # just functional correctness
    CSIM_SYNTH = "csim_synth"             # + synthesizable + freq + resource
    FULL = "full"                          # + cosim (structural tasks)
    SCORING = "scoring"                    # hidden CSim + synth(cand) + synth(base) + cosim


# ── Candidate validator ──────────────────────────────────────────────────────

class CandidateValidator:
    """Validate a candidate kernel through a :class:`ValidationPlan`.

    All tool calls go through the injected ``tool_executor`` (which handles
    security, env sanitisation, and harness invocation).  Gate logic is
    applied *after* tools return — the validator does not embed tool policy.
    """

    def __init__(
        self,
        task: Any,
        starter_code: str,
        *,
        tool_executor: Any = None,
        interface_contract: Any = None,
    ) -> None:
        self._task = task
        self._starter_code = starter_code
        self._tool = tool_executor
        # Build the interface contract once from starter source
        if interface_contract is not None:
            self._contract = interface_contract
        else:
            from agent.validation import CandidateValidator as _OldV
            self._contract = _OldV.from_source(task.top, starter_code).contract

    @property
    def contract(self) -> Any:
        return self._contract

    # ── Public API ───────────────────────────────────────────────────────

    def validate(
        self,
        code: str,
        *,
        plan: ValidationPlan = ValidationPlan.CSIM_SYNTH,
        build_dir: Path | None = None,
        stage: str = "candidate",
    ) -> CandidateEvaluation:
        """Run every gate required by *plan* and return structured results.

        Tool failures (timeout, synth error, etc.) are recorded as gate
        failures — they do NOT raise exceptions.
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
            return ev

        # ── 1. CSim gate ────────────────────────────────────────────────
        if plan in (ValidationPlan.CSIM_ONLY, ValidationPlan.CSIM_SYNTH,
                     ValidationPlan.FULL, ValidationPlan.SCORING):
            csim_ok = self._run_csim(code, build_dir, stage)
            ev.csim = "pass" if csim_ok else "fail"
            if not csim_ok:
                ev.fail("csim")
                return ev

        # ── 2. Synth + freq + resource gates ────────────────────────────
        if plan in (ValidationPlan.CSIM_SYNTH, ValidationPlan.FULL,
                     ValidationPlan.SCORING):
            synth_report = self._run_synth(code, build_dir, stage)
            if synth_report is None:
                ev.synth = "fail"
                ev.fail("synth")
                return ev
            ev.synth = "pass"

            ev.frequency = self._check_frequency(synth_report)
            if not ev.frequency.ok:
                ev.fail(ev.frequency.reason or "frequency")
                return ev

            ev.resource = self._check_resource(synth_report)
            if not ev.resource.ok:
                ev.fail(ev.resource.reason or "resource")
                return ev

            # Store synth PPA for scoring
            ev.synth_latency = getattr(synth_report, "latency_worst", None) or getattr(synth_report, "latency_avg", None)
            ev.synth_ii = getattr(synth_report, "interval_max", None)
            ev.synth_clock_ns = getattr(synth_report, "clock_period_ns", None)
            ev.synth_resources = dict(getattr(synth_report, "resources", {}) or {})

        # ── 3. CoSim gate (only for structural tasks) ──────────────────
        requires_cosim = getattr(self._task, "requires_cosim", False)
        if plan == ValidationPlan.FULL and requires_cosim:
            cosim_ok = self._run_cosim(code, build_dir, stage)
            if not cosim_ok:
                ev.fail("cosim")
                return ev

        # All required gates passed
        ev.accepted = True
        ev.elapsed_s = round(time.monotonic() - _t0, 3)
        return ev

    # ── Gate implementations ────────────────────────────────────────────

    def _check_interface(self, code: str) -> InterfaceGateEvidence:
        from agent.validation import CandidateValidator as _OldV
        v = _OldV(self._contract)
        result = v.validate(code)
        return InterfaceGateEvidence(
            ok=result.ok,
            reason=result.reason,
            fingerprint=result.fingerprint,
            canonical_signature=result.canonical_signature,
            required_includes_present=result.required_includes_present,
        )

    def _run_csim(self, code: str, build_dir: Path | None, stage: str) -> bool:
        if self._tool is None:
            return False
        d = build_dir or Path("/tmp")
        files = self._task.assemble(code, self._task.public_tb_code, self._task.public_tb_name)
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
        files = dict(self._task.headers)
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

    def _run_cosim(self, code: str, build_dir: Path | None, stage: str) -> bool:
        if self._tool is None:
            return False
        d = build_dir or Path("/tmp")
        files = self._task.assemble(code, self._task.public_tb_code, self._task.public_tb_name)
        try:
            r = self._tool.cosim(d / f"{stage}_cosim", files,
                                synth_sources=[self._task.kernel_name],
                                tb_sources=[self._task.public_tb_name],
                                top=self._task.top, part=self._task.part,
                                clock_ns=self._task.clock_ns)
            payload = getattr(r, "cosim", None)
            return bool(getattr(r, "ok", False) and payload is not None
                       and getattr(payload, "passed", False))
        except Exception:
            return False

    def _check_frequency(self, report: Any) -> FrequencyGateEvidence:
        from agent.validation import frequency_gate
        g = frequency_gate(report, self._task.clock_ns)
        return FrequencyGateEvidence(
            ok=g.ok, reason=g.reason,
            target_clock_ns=g.target_clock_ns,
            candidate_clock_ns=g.candidate_clock_ns,
            frequency_mhz=g.frequency_mhz,
        )

    def _check_resource(self, report: Any) -> ResourceGateEvidence:
        from agent.validation import resource_gate
        g = resource_gate(report)
        return ResourceGateEvidence(
            ok=g.ok, reason=g.reason,
            resources=g.resources, available=g.available,
        )
