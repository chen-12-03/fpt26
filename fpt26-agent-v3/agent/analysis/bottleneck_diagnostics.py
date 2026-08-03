"""Evidence-first HLS bottleneck diagnosis from complete synthesis logs.

The parser intentionally supports only message families observed in repository
``runs`` artifacts.  Missing or ambiguous evidence remains ``unknown``; the
module never infers a root cause from latency magnitude or resource ratios.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.analysis.synth_diagnostics import extract_ii_resource_limits
from agent.security.redaction import redact_sensitive_text


_SUPPORTED_MESSAGE_IDS = (
    "HLS 200-448",
    "HLS 200-880",
    "SCHED 204-65",
    "HLS 214-187",
    "HLS 200-871",
    "HLS 200-1016",
    "HLS 200-2199",
    "HLS 214-114",
    "HLS 200-471",
    "HLS 200-805",
    "HLS 200-2250",
    "HLS 200-1603",
)
_CONFIDENCE_RANK = {"confirmed": 0, "probable": 1, "unknown": 2}
_CAUSE_RANK = {
    "carried_dependency": 0,
    "memory_port": 1,
    "shared_resource_conflict": 2,
    "timing_critical_path": 3,
    "serial_loop_latency": 4,
    "pipeline_structure": 5,
    "variable_trip_count": 6,
    "dataflow_noncanonical": 7,
    "stream_depth_risk": 8,
    "rewind_dependency": 9,
    "rewind_synchronization": 10,
    "m_axi_widening_limit": 11,
    "m_axi_conditional_access": 12,
    "m_axi_alignment_limit": 13,
    "m_axi_width_mismatch": 14,
    "m_axi_bundle_write_conflict": 15,
    "unknown": 99,
}


@dataclass(frozen=True)
class LoadedSynthesisLog:
    text: str
    source: str
    complete: bool


@dataclass(frozen=True)
class BottleneckFinding:
    cause: str
    target: dict[str, Any]
    confidence: str
    symptom: str
    evidence: tuple[str, ...]
    observations: dict[str, Any] = field(default_factory=dict)
    allowed_actions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    expected_validation_signals: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "cause": self.cause,
            "target": dict(self.target),
            "confidence": self.confidence,
            "symptom": self.symptom,
            "evidence": list(self.evidence),
            "observations": dict(self.observations),
            "allowed_actions": list(self.allowed_actions),
            "forbidden_actions": list(self.forbidden_actions),
            "expected_validation_signals": list(
                self.expected_validation_signals
            ),
            "missing_evidence": list(self.missing_evidence),
        }


@dataclass(frozen=True)
class BottleneckDiagnosis:
    findings: tuple[BottleneckFinding, ...]
    primary_index: int
    evidence_source: str
    evidence_complete: bool
    supported_message_ids: tuple[str, ...]
    diagnostic_state: str
    schema_version: int = 2

    @property
    def primary(self) -> BottleneckFinding:
        return self.findings[self.primary_index]

    def summary(self) -> str:
        primary = self.primary
        target = ", ".join(
            f"{key}={value}" for key, value in primary.target.items() if value
        ) or "target=unknown"
        evidence_match = next(
            (
                match
                for item in primary.evidence
                for match in [re.search(r"\[([^]]+)\]", item)]
                if match is not None
            ),
            None,
        )
        evidence_id = (
            evidence_match.group(1)
            if evidence_match is not None
            else "SynthReport loop_metrics"
            if primary.evidence
            else "no direct message"
        )
        return (
            f"state={self.diagnostic_state}; primary={primary.cause}; {target}; "
            f"confidence={primary.confidence}; evidence={evidence_id}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "primary_finding": self.primary_index,
            "summary": self.summary(),
            "evidence_source": self.evidence_source,
            "evidence_complete": self.evidence_complete,
            "diagnostic_state": self.diagnostic_state,
            "supported_message_ids": list(self.supported_message_ids),
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def to_prompt_dict(self) -> dict[str, Any]:
        """Return a bounded prompt projection; the full report stays auditable."""

        payload = self.to_dict()
        bounded_findings = []
        for finding in payload["findings"][:4]:
            finding["evidence"] = finding["evidence"][:2]
            bounded_findings.append(finding)
        payload["findings"] = bounded_findings
        payload["finding_count"] = len(self.findings)
        payload["prompt_findings_truncated"] = len(self.findings) > 4
        return payload


def load_synthesis_log(result: Any) -> LoadedSynthesisLog:
    """Read the complete persisted HLS log when the agent runner recorded it."""

    artifact_dir = getattr(result, "_artifact_dir", None)
    if artifact_dir:
        directory = Path(artifact_dir)
        path = directory / "logs" / "hls_run_tcl.log"
        try:
            resolved_directory = directory.resolve(strict=True)
            resolved_path = path.resolve(strict=True)
            if (
                resolved_path.is_file()
                and resolved_path.parent.parent == resolved_directory
            ):
                return LoadedSynthesisLog(
                    resolved_path.read_text(encoding="utf-8", errors="replace"),
                    "full_hls_run_tcl_log",
                    True,
                )
        except OSError:
            pass
    return LoadedSynthesisLog(
        str(getattr(result, "log", "") or ""),
        "tool_result_excerpt",
        False,
    )


def diagnose_synthesis(
    result: Any,
    loaded_log: LoadedSynthesisLog | None = None,
) -> BottleneckDiagnosis:
    """Return a bounded diagnosis based on deterministic report/log evidence."""

    loaded = loaded_log or load_synthesis_log(result)
    text = loaded.text
    findings: list[BottleneckFinding] = []

    findings.extend(_memory_port_findings(text))
    findings.extend(_carried_dependency_findings(text))
    findings.extend(_shared_resource_findings(text))
    findings.extend(_timing_findings(text))
    findings.extend(_serial_loop_findings(result, text))
    findings.extend(_pipeline_structure_findings(text))
    findings.extend(_variable_trip_findings(text))
    findings.extend(_dataflow_findings(text))
    findings.extend(_stream_risk_findings(text))
    findings.extend(_rewind_dependency_findings(text))
    findings.extend(_m_axi_burst_findings(result, text))

    if not findings:
        findings.append(_unknown_finding(result, text, loaded.complete))

    findings = _deduplicate_findings(findings)
    findings.sort(
        key=lambda item: (
            _CONFIDENCE_RANK.get(item.confidence, 9),
            _CAUSE_RANK.get(item.cause, 98),
            str(item.target),
        )
    )
    observed_ids = tuple(
        message_id
        for message_id in _SUPPORTED_MESSAGE_IDS
        if f"[{message_id}]" in text
    )
    primary = findings[0]
    explicit_ok = getattr(result, "ok", None)
    report = getattr(result, "report", None)
    if explicit_ok is False:
        diagnostic_state = "synthesis_failed"
    elif primary.cause != "unknown":
        diagnostic_state = (
            "confirmed_bottleneck"
            if primary.confidence == "confirmed"
            else "conditional_bottleneck"
        )
    elif (
        primary.observations.get("loops_with_ii_gt_1")
        or "HLS 200-1603" in observed_ids
    ):
        diagnostic_state = "unresolved_bottleneck_cause"
    elif report is not None and loaded.complete:
        diagnostic_state = "no_confirmed_bottleneck"
    else:
        diagnostic_state = "insufficient_artifacts"
    return BottleneckDiagnosis(
        findings=tuple(findings[:12]),
        primary_index=0,
        evidence_source=loaded.source,
        evidence_complete=loaded.complete,
        supported_message_ids=observed_ids,
        diagnostic_state=diagnostic_state,
    )


def assess_action_alignment(
    diagnosis: BottleneckDiagnosis,
    candidate_action: dict[str, Any],
    source_architecture_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assess whether a candidate addresses the selected evidence target.

    This is an audit signal, not a universal hard gate: source rewrites cannot
    always be mapped to a loop/array name without another semantic analysis.
    """

    primary = diagnosis.primary
    families = {str(value) for value in candidate_action.get("families", [])}
    targets = candidate_action.get("targets", {})
    arrays = set(targets.get("arrays", [])) if isinstance(targets, dict) else set()
    loops = set(targets.get("loops", [])) if isinstance(targets, dict) else set()
    source_changed = bool(candidate_action.get("source_changed"))
    expected_families = {
        "memory_port": {"MEMORY_BANKING", "SOURCE_RESTRUCTURE"},
        "carried_dependency": {"SOURCE_RESTRUCTURE"},
        "shared_resource_conflict": {"MEMORY_BANKING", "SOURCE_RESTRUCTURE"},
        "timing_critical_path": {"PIPELINE", "RESOURCE_BINDING", "SOURCE_RESTRUCTURE"},
        "serial_loop_latency": {"LOOP_UNROLL", "SOURCE_RESTRUCTURE"},
        "pipeline_structure": {"LOOP_UNROLL", "SOURCE_RESTRUCTURE"},
        "variable_trip_count": {"SOURCE_RESTRUCTURE"},
        "dataflow_noncanonical": {"DATAFLOW", "SOURCE_RESTRUCTURE"},
        "stream_depth_risk": {"STREAM", "DATAFLOW", "SOURCE_RESTRUCTURE"},
        "rewind_dependency": {"SOURCE_RESTRUCTURE"},
        "rewind_synchronization": {"SOURCE_RESTRUCTURE"},
        "m_axi_widening_limit": {"INTERFACE", "SOURCE_RESTRUCTURE"},
        "m_axi_conditional_access": {"SOURCE_RESTRUCTURE"},
        "m_axi_alignment_limit": {"INTERFACE", "SOURCE_RESTRUCTURE"},
        "m_axi_width_mismatch": {"INTERFACE", "SOURCE_RESTRUCTURE"},
        "m_axi_bundle_write_conflict": {"INTERFACE", "SOURCE_RESTRUCTURE"},
    }.get(primary.cause, set())
    target_name = str(
        primary.target.get("array")
        or primary.target.get("loop")
        or primary.target.get("resource")
        or ""
    )
    target_matches = not target_name or target_name in arrays or target_name in loops
    family_matches = bool(families & expected_families) or (
        source_changed and "SOURCE_RESTRUCTURE" in expected_families
    )
    source_supported_families = {
        str(value)
        for item in source_architecture_evidence or []
        if isinstance(item, dict)
        for value in item.get("candidate_families", [])
        if str(value)
    }
    source_architecture_match = bool(families & source_supported_families)
    if not source_architecture_match:
        source_architecture_match = any(
            bool(item.get("composite_family"))
            and families
            <= {
                str(value)
                for value in item.get("composite_family_members", [])
                if str(value)
            }
            and source_changed
            for item in source_architecture_evidence or []
            if isinstance(item, dict)
        )
    if source_architecture_match:
        status = "aligned"
        reason = (
            "candidate family is supported by deterministic source "
            "architecture evidence"
        )
    elif primary.cause == "unknown":
        status = "unknown"
        reason = "root cause is unknown; alignment cannot be asserted"
    elif family_matches and (target_matches or source_changed):
        status = "aligned"
        reason = "candidate family addresses the selected cause/target"
    elif families and expected_families and not families & expected_families:
        status = "contradicted"
        reason = (
            f"candidate families {sorted(families)} do not address "
            f"{primary.cause}"
        )
    else:
        status = "unknown"
        reason = "candidate target could not be mapped deterministically"
    return {
        "status": status,
        "reason": reason,
        "selected_cause": primary.cause,
        "selected_target": dict(primary.target),
        "candidate_families": sorted(families),
        "source_supported_families": sorted(source_supported_families),
    }


def _line(text: str, message_id: str) -> list[str]:
    return [
        item.strip()
        for item in text.splitlines()
        if f"[{message_id}]" in item
    ]


def _evidence(line: str) -> str:
    bounded = redact_sensitive_text(line.strip())[:700]
    return re.sub(
        r"(?<!\w)(?:/[A-Za-z0-9_.:-]+)+",
        lambda match: "<path>/" + match.group(0).rsplit("/", 1)[-1],
        bounded,
    )


def _memory_port_findings(text: str) -> list[BottleneckFinding]:
    result = []
    for limit in extract_ii_resource_limits(text):
        matched = next(
            (
                line
                for line in _line(text, "HLS 200-448")
                if f"Lower bound of II is {limit.lower_bound}" in line
                and (
                    (limit.array and f"array '{limit.array}'" in line)
                    or (limit.port and f"'{limit.port}'" in line)
                )
            ),
            "",
        )
        target = {
            "storage_kind": limit.storage_kind,
            "array": limit.array,
            "port": limit.port,
            "source": limit.source,
        }
        if limit.storage_kind == "local_memory":
            allowed = (
                "inspect the exact concurrent index mapping before banking",
                "bank/reshape only the reported local array and proven dimension",
                "reduce repeated reads with source-level locality or buffering",
            )
            forbidden = (
                "standalone PIPELINE or UNROLL as a port-conflict fix",
                "partition an unreported or top-level array",
            )
        else:
            allowed = (
                "inspect source access order and interface contract",
                "coalesce/burst accesses or add semantics-preserving local buffering",
                "change port width or bundle only when the public interface permits it",
            )
            forbidden = (
                "treat an m_axi port as a local array-partition target",
                "standalone PIPELINE as a bus-bandwidth fix",
            )
        result.append(
            BottleneckFinding(
                cause="memory_port",
                target=target,
                confidence="confirmed",
                symptom="loop initiation interval has a resource lower bound",
                evidence=(_evidence(matched),) if matched else (),
                observations={
                    "ii_lower_bound": limit.lower_bound,
                    "operation": limit.operation,
                    "core": limit.core,
                },
                allowed_actions=allowed,
                forbidden_actions=forbidden,
                expected_validation_signals=(
                    "HLS 200-448 disappears or reports a lower II bound",
                    "reported loop PipelineII decreases without worse clock/resource gates",
                    "CSim and required CoSim remain passing",
                ),
            )
        )
    return result


def _carried_dependency_findings(text: str) -> list[BottleneckFinding]:
    result = []
    pattern = re.compile(
        r"module '([^']+)' \((loop|function) '([^']+)'\).*?"
        r"carried dependence constraint \(II\s*=\s*(\d+),\s*"
        r"distance\s*=\s*(\d+),\s*offset\s*=\s*(\d+)\)",
        re.IGNORECASE,
    )
    for line in _line(text, "HLS 200-880"):
        match = pattern.search(line)
        if not match:
            continue
        variable = re.search(r"(?:of|on(?: local)?) variable '([^']+)'", line)
        result.append(
            BottleneckFinding(
                cause="carried_dependency",
                target={
                    "module": match.group(1),
                    match.group(2).lower(): match.group(3),
                    "variable": variable.group(1) if variable else None,
                },
                confidence="confirmed",
                symptom="requested pipeline II cannot satisfy a carried dependence",
                evidence=(_evidence(line),),
                observations={
                    "requested_ii": int(match.group(4)),
                    "distance": int(match.group(5)),
                    "offset": int(match.group(6)),
                },
                allowed_actions=(
                    "restructure the named dependence while preserving arithmetic semantics",
                    "use a proven partial-sum/reduction architecture when numerical tolerance permits",
                ),
                forbidden_actions=(
                    "repeat PIPELINE II=1 without changing the dependence",
                    "add a false DEPENDENCE pragma without a source proof",
                    "assume memory banking removes a scalar recurrence",
                ),
                expected_validation_signals=(
                    "HLS 200-880 disappears or the achieved loop II decreases",
                    "CSim numerical tolerance remains passing",
                    "effective latency improves faster than worst resource growth",
                ),
            )
        )
    return result


def _shared_resource_findings(text: str) -> list[BottleneckFinding]:
    result = []
    pattern = re.compile(
        r"module '([^']+)' \((loop|function) '([^']+)'\).*?"
        r"common resource '([^']+)'",
        re.IGNORECASE,
    )
    for line in _line(text, "HLS 200-2199"):
        match = pattern.search(line)
        if not match:
            continue
        result.append(
            BottleneckFinding(
                cause="shared_resource_conflict",
                target={
                    "module": match.group(1),
                    match.group(2).lower(): match.group(3),
                    "resource": match.group(4),
                },
                confidence="confirmed",
                symptom="multiple scheduled accesses contend for one resource",
                evidence=(_evidence(line),),
                allowed_actions=(
                    "reduce concurrent accesses to the named resource",
                    "bank a named local array only with source-proven mapping",
                    "restructure stream or memory access scheduling",
                ),
                forbidden_actions=(
                    "standalone PIPELINE without changing resource demand",
                    "bank an unrelated array",
                ),
                expected_validation_signals=(
                    "HLS 200-2199 disappears for the named resource",
                    "achieved loop II or latency improves",
                ),
            )
        )
    return result


def _timing_findings(text: str) -> list[BottleneckFinding]:
    result = []
    pattern = re.compile(
        r"Estimated clock period \(([0-9.]+) ns\).*?"
        r"target clock period: ([0-9.]+) ns, clock uncertainty: "
        r"([0-9.]+) ns, effective delay budget: ([0-9.]+) ns",
        re.IGNORECASE,
    )
    modules = [
        match.group(1)
        for line in _line(text, "HLS 200-1016")
        for match in [re.search(r"module '([^']+)'", line)]
        if match
    ]
    for line in _line(text, "HLS 200-871"):
        match = pattern.search(line)
        if not match:
            continue
        result.append(
            BottleneckFinding(
                cause="timing_critical_path",
                target={"module": modules[0] if modules else None},
                confidence="confirmed",
                symptom="estimated critical path exceeds the effective delay budget",
                evidence=(_evidence(line),),
                observations={
                    "estimated_clock_ns": float(match.group(1)),
                    "target_clock_ns": float(match.group(2)),
                    "clock_uncertainty_ns": float(match.group(3)),
                    "effective_delay_budget_ns": float(match.group(4)),
                },
                allowed_actions=(
                    "inspect the HLS 200-1016 critical-path operations",
                    "shorten the named combinational path or add a legal pipeline boundary",
                    "change operation binding only when the critical operation supports it",
                ),
                forbidden_actions=(
                    "infer timing failure only from target clock",
                    "blindly unroll a timing-limited path",
                ),
                expected_validation_signals=(
                    "estimated clock period fits the effective delay budget",
                    "frequency gate passes without disproportionate resource growth",
                ),
                missing_evidence=(
                    () if modules else ("HLS 200-1016 module/operation detail",)
                ),
            )
        )
    return result


def _pipeline_structure_findings(text: str) -> list[BottleneckFinding]:
    result = []
    for line in _line(text, "SCHED 204-65"):
        match = re.search(r"(?:for )?(loop|function) '([^']+)'", line)
        if match:
            result.append(
                BottleneckFinding(
                    cause="pipeline_structure",
                    target={match.group(1).lower(): match.group(2)},
                    confidence="confirmed",
                    symptom="pipeline directive is unsatisfied by nested loop structure",
                    evidence=(_evidence(line),),
                    allowed_actions=(
                        "inspect and legally unroll/flatten the named loop's subloops",
                        "refactor the loop nest while preserving behavior",
                    ),
                    forbidden_actions=(
                        "repeat the same PIPELINE directive without changing subloops",
                        "blindly unroll a variable-trip-count subloop",
                    ),
                    expected_validation_signals=(
                        "SCHED 204-65 disappears",
                        "the intended loop reports a valid PipelineII",
                    ),
                )
            )
    return result


def _serial_loop_findings(result: Any, text: str) -> list[BottleneckFinding]:
    """Report the largest measured II=1 loop without prescribing a factor."""

    report = getattr(result, "report", None)
    top_latency = (
        getattr(report, "latency_worst", None)
        or getattr(report, "latency_avg", None)
        if report is not None
        else None
    )
    if not isinstance(top_latency, int) or top_latency <= 0:
        return []
    candidates = []
    for loop in list(getattr(report, "loop_metrics", None) or []):
        if (
            str(loop.get("name") or "")
            and loop.get("pipeline_ii") == 1
            and isinstance(loop.get("trip_count"), int)
            and loop["trip_count"] > 1
            and isinstance(loop.get("latency"), int)
            and loop["latency"] > 0
        ):
            candidates.append(loop)
    if not candidates:
        return []
    loop = max(candidates, key=lambda item: item["latency"])
    name = str(loop["name"])
    trip_count = loop["trip_count"]
    loop_latency = loop["latency"]
    pipeline_ii = loop["pipeline_ii"]
    rewind_lines = _line(text, "HLS 200-2250")
    dependence_line = next(
        (line for line in rewind_lines if f"loop '{name}'" in line), ""
    )
    variable_match = re.search(
        r"dependence on variable '([^']+)'", dependence_line
    )
    report_evidence = (
        "SynthReport loop_metrics: "
        f"loop='{name}', trip_count={trip_count}, latency={loop_latency}, "
        f"PipelineII={pipeline_ii}; top_latency={top_latency}"
    )
    evidence = [report_evidence]
    if dependence_line:
        evidence.append(_evidence(dependence_line))
    return [
        BottleneckFinding(
            cause="serial_loop_latency",
            target={
                "loop": name,
                "variable": (
                    variable_match.group(1) if variable_match else None
                ),
            },
            confidence="probable",
            symptom=(
                "largest reported II=1 loop has a measured contribution to "
                "top latency; dominance is not assumed"
            ),
            evidence=tuple(evidence),
            observations={
                "trip_count": trip_count,
                "loop_latency": loop_latency,
                "top_latency": top_latency,
                "top_latency_fraction": round(loop_latency / top_latency, 4),
                "pipeline_ii": pipeline_ii,
            },
            allowed_actions=(
                "inspect dependence, numerical semantics, and memory accesses",
                "derive candidate transformations and parameters from the "
                "editable source without preferring a factor",
                "measure one source-legal loop or reduction transformation",
            ),
            forbidden_actions=(
                "add another PIPELINE to a loop already at PipelineII=1",
                "treat the largest reported loop as automatically dominant",
                "select UNROLL or a factor from loop length alone",
            ),
            expected_validation_signals=(
                "named loop and top effective latency improve",
                "CSim numerical tolerance remains passing",
                "Q_HW improves after clock and all resource growth are included",
            ),
            missing_evidence=(
                "editable-source proof for independence or reduction legality",
                "a source-supported transformation and parameter choice",
            ),
        )
    ]


def _variable_trip_findings(text: str) -> list[BottleneckFinding]:
    result = []
    pattern = re.compile(
        r"Cannot unroll loop '([^']+)' \(([^)]+)\) in function '([^']+)'"
        r" as it has a variable trip count",
        re.IGNORECASE,
    )
    for line in _line(text, "HLS 214-187"):
        match = pattern.search(line)
        if match:
            result.append(
                BottleneckFinding(
                    cause="variable_trip_count",
                    target={
                        "loop": match.group(1),
                        "function": match.group(3),
                        "source": match.group(2),
                    },
                    confidence="confirmed",
                    symptom="requested unroll was not applied",
                    evidence=(_evidence(line),),
                    allowed_actions=(
                        "establish a compile-time bound only when the public contract proves it",
                        "restructure or partially unroll only with source-supported bounds",
                    ),
                    forbidden_actions=(
                        "repeat full UNROLL on the same variable-trip loop",
                        "invent a fixed trip count",
                    ),
                    expected_validation_signals=(
                        "HLS 214-187 disappears for the named loop",
                        "the synthesis report confirms the intended unroll/latency change",
                    ),
                )
            )
    return result


def _dataflow_findings(text: str) -> list[BottleneckFinding]:
    lines = _line(text, "HLS 214-114")
    if not lines:
        return []
    count_line = next(iter(_line(text, "HLS 200-471")), "")
    count_match = re.search(r"found (\d+) issue", count_line)
    source_match = re.search(r"\(([^)]+)\)", lines[0])
    return [
        BottleneckFinding(
            cause="dataflow_noncanonical",
            target={"source": source_match.group(1) if source_match else None},
            confidence="confirmed",
            symptom="DATAFLOW region contains non-canonical statements",
            evidence=tuple(_evidence(item) for item in [lines[0], count_line] if item),
            observations={
                "reported_issue_count": int(count_match.group(1))
                if count_match
                else None
            },
            allowed_actions=(
                "refactor the region into declarations, loops, and function calls accepted by HLS",
                "re-synthesize before tuning FIFO depths",
            ),
            forbidden_actions=(
                "claim task-level overlap while form checks still fail",
                "use FIFO depth as the sole fix for a non-canonical region",
            ),
            expected_validation_signals=(
                "HLS 214-114 and HLS 200-471 disappear",
                "the synthesis report confirms DATAFLOW processes/channels",
            ),
        )
    ]


def _stream_risk_findings(text: str) -> list[BottleneckFinding]:
    result = []
    for line in _line(text, "HLS 200-805"):
        match = re.search(
            r"stream '([^']+)'(?: \(([^)]+)\))? with default size",
            line,
        )
        if match:
            result.append(
                BottleneckFinding(
                    cause="stream_depth_risk",
                    target={"stream": match.group(1), "source": match.group(2)},
                    confidence="probable",
                    symptom="default internal stream depth may deadlock",
                    evidence=(_evidence(line),),
                    allowed_actions=(
                        "set an explicit bounded depth supported by producer/consumer behavior",
                        "restructure producer/consumer ordering when required CoSim confirms blocking",
                    ),
                    forbidden_actions=(
                        "claim an actual deadlock from this warning alone",
                        "choose an arbitrary large depth without validation",
                    ),
                    expected_validation_signals=(
                        "HLS 200-805 disappears",
                        "required RTL CoSim passes without timeout/deadlock",
                    ),
                    missing_evidence=("required CoSim blocking/deadlock evidence",),
                )
            )
    return result


def _rewind_dependency_findings(text: str) -> list[BottleneckFinding]:
    result = []
    pattern = re.compile(
        r"Rewind delay = (\d+) for the pipelined loop '([^']+)' due to a "
        r"(write-after-read|read-after-write) dependence on variable '([^']+)'",
        re.IGNORECASE,
    )
    sync_pattern = re.compile(
        r"Rewind delay = (\d+) for the pipelined loop '([^']+)' to "
        r"synchronize the writ(?:t)?ing of port '([^']+)' with ap_done",
        re.IGNORECASE,
    )
    for line in _line(text, "HLS 200-2250"):
        match = pattern.search(line)
        if match:
            result.append(
                BottleneckFinding(
                    cause="rewind_dependency",
                    target={"loop": match.group(2), "variable": match.group(4)},
                    confidence="probable",
                    symptom="loop rewind has a write-after-read delay",
                    evidence=(_evidence(line),),
                    observations={
                        "rewind_delay": int(match.group(1)),
                        "dependence_kind": match.group(3).lower(),
                    },
                    allowed_actions=(
                        "inspect whether rewind delay affects the measured transaction objective",
                        "restructure the named dependence only when source semantics permit",
                    ),
                    forbidden_actions=(
                        "claim this is the primary latency bottleneck without loop/report correlation",
                        "add PIPELINE again without changing the dependence",
                    ),
                    expected_validation_signals=(
                        "rewind delay or measured loop latency decreases",
                        "CSim remains within numerical tolerance",
                    ),
                    missing_evidence=("correlation to dominant loop latency or achieved II",),
                )
            )
            continue
        sync_match = sync_pattern.search(line)
        if sync_match:
            result.append(
                BottleneckFinding(
                    cause="rewind_synchronization",
                    target={
                        "loop": sync_match.group(2),
                        "port": sync_match.group(3),
                    },
                    confidence="probable",
                    symptom="loop rewind waits for port/ap_done synchronization",
                    evidence=(_evidence(line),),
                    observations={"rewind_delay": int(sync_match.group(1))},
                    allowed_actions=(
                        "inspect whether the port synchronization affects the measured transaction objective",
                        "change control/interface scheduling only when the public contract permits it",
                    ),
                    forbidden_actions=(
                        "claim the synchronization delay is the primary bottleneck without report correlation",
                        "remove required ap_done/interface synchronization",
                    ),
                    expected_validation_signals=(
                        "measured rewind/transaction interval decreases",
                        "interface, CSim, and required CoSim gates remain passing",
                    ),
                    missing_evidence=(
                        "correlation to measured top interval or latency",
                    ),
                )
            )
    return result


def _m_axi_burst_findings(result: Any, text: str) -> list[BottleneckFinding]:
    """Classify explicit per-access M_AXI failures from ``ReportBurst``.

    HLS 200-1603 alone remains unknown.  A finding is emitted only when the
    parsed report supplies a recognized status and problem/resolution pair.
    """

    report = getattr(result, "report", None)
    accesses = list(getattr(report, "burst_accesses", None) or [])
    if not accesses:
        return []

    rules = (
        (
            "m_axi_widening_limit",
            "214-353",
            "max_widen_bitwidth",
            "M_AXI access could not be widened because of the configured width limit",
        ),
        (
            "m_axi_conditional_access",
            "214-232",
            "conditional branch",
            "M_AXI burst inference failed because the access is conditional",
        ),
        (
            "m_axi_alignment_limit",
            "214-307",
            "alignment",
            "M_AXI access could not be widened because of alignment",
        ),
        (
            "m_axi_width_mismatch",
            "",
            "data width is different from m_axi port width",
            "inferred M_AXI burst was reverted because access and port widths differ",
        ),
        (
            "m_axi_bundle_write_conflict",
            "214-224",
            "multiple potential writes",
            "M_AXI burst inference failed because one region may write the "
            "same bundle multiple times",
        ),
    )
    findings = []
    for access in accesses:
        status = str(access.get("burst_status") or "")
        if status == "Inferred":
            continue
        resolution = str(access.get("resolution") or "")
        problem = str(access.get("problem") or "")
        matched_rule = next(
            (
                rule
                for rule in rules
                if (not rule[1] or resolution == rule[1])
                and rule[2].lower() in problem.lower()
            ),
            None,
        )
        if matched_rule is None:
            continue
        cause, _, _, symptom = matched_rule
        target = {
            "interface": access.get("hw_interface") or None,
            "variable": access.get("variable") or None,
            "direction": access.get("direction") or None,
            "loop": access.get("loop") or None,
            "source": access.get("access_location") or None,
        }
        evidence = (
            "csynth.xml ReportBurst"
            + (f" [{resolution}]" if resolution else "")
            + f": status={status}; problem={problem}"
        )
        findings.append(
            BottleneckFinding(
                cause=cause,
                target=target,
                confidence="confirmed",
                symptom=symptom,
                evidence=(_evidence(evidence),),
                observations={
                    "burst_status": status,
                    "resolution": resolution or None,
                    "loop_location": access.get("loop_location") or None,
                },
                allowed_actions=(
                    "inspect the named M_AXI access and preserve the public "
                    "interface contract",
                    "change only the reported access pattern or compatible "
                    "interface width/alignment setting",
                ),
                forbidden_actions=(
                    "treat the external M_AXI port as a local ARRAY_PARTITION target",
                    "claim a different burst cause than the ReportBurst problem field",
                ),
                expected_validation_signals=(
                    "the named ReportBurst access becomes Inferred or the "
                    "explicit failure reason disappears",
                    "effective latency improves without violating CSim, CoSim, "
                    "frequency, or resource gates",
                ),
                missing_evidence=(
                    "correlation to measured latency or interface throughput",
                ),
            )
        )
    return findings


def _unknown_finding(result: Any, text: str, complete: bool) -> BottleneckFinding:
    report = getattr(result, "report", None)
    loop_metrics = list(getattr(report, "loop_metrics", None) or [])
    high_ii = [
        {
            "loop": item.get("name"),
            "pipeline_ii": item.get("pipeline_ii"),
            "latency": item.get("latency"),
        }
        for item in loop_metrics
        if isinstance(item.get("pipeline_ii"), int)
        and item.get("pipeline_ii") > 1
    ]
    burst_summary = bool(_line(text, "HLS 200-1603"))
    missing = []
    if not complete:
        missing.append("complete persisted hls_run_tcl.log")
    if high_ii:
        missing.append("direct scheduler cause for the reported loop II")
    if burst_summary:
        missing.append("per-port missed-burst detail referenced by the HLS GUI report")
    if not missing:
        missing.append("direct timing/dependence/port/resource diagnostic")
    return BottleneckFinding(
        cause="unknown",
        target={},
        confidence="unknown",
        symptom=(
            "loop II is elevated but its cause is not present in supported evidence"
            if high_ii
            else "no supported root-cause diagnostic is present"
        ),
        evidence=tuple(_evidence(line) for line in _line(text, "HLS 200-1603")[:1]),
        observations={"loops_with_ii_gt_1": high_ii},
        allowed_actions=(
            "inspect the named full HLS report and source before selecting an action",
            "ask the LLM to explain ambiguity without upgrading confidence",
        ),
        forbidden_actions=(
            "infer a root cause from absolute latency or FF/LUT/DSP ratios",
            "apply speculative PIPELINE, UNROLL, ARRAY_PARTITION, or DATAFLOW",
        ),
        expected_validation_signals=(
            "a subsequent synthesis emits direct cause/target evidence",
            "any trial must pass CSim and improve scoring_v3 Q_HW",
        ),
        missing_evidence=tuple(missing),
    )


def _deduplicate_findings(
    findings: list[BottleneckFinding],
) -> list[BottleneckFinding]:
    result = []
    seen = set()
    for finding in findings:
        key = (finding.cause, tuple(sorted(finding.target.items())), finding.evidence)
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result
