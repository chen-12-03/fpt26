"""Deterministic QoR knowledge retrieval for the optimization loop.

The runtime deliberately uses a small, auditable hybrid retriever instead of
an embedding service.  Rules are curated seeds; measured cases are admitted
only when their evidence proves the required public validation gates.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


KNOWLEDGE_SCHEMA_VERSION = 1
MAX_KNOWLEDGE_PROMPT_TOKENS = 1_800
_CHARS_PER_TOKEN_UPPER_BOUND = 3
_MAX_KNOWLEDGE_PROMPT_CHARS = (
    MAX_KNOWLEDGE_PROMPT_TOKENS * _CHARS_PER_TOKEN_UPPER_BOUND
)
_ASSET_ROOT = Path(__file__).with_name("knowledge_assets")
_DEFAULT_SEED_PATH = _ASSET_ROOT / "hls_generator_seeds.json"
_DEFAULT_CASE_PATH = _ASSET_ROOT / "verified_cases.json"
_FORBIDDEN_RUNTIME_COMPONENTS = frozenset(
    {"hidden", "reference", "evaluator"}
)
_KINDS = frozenset({"rule", "verified_case", "failure_case"})
_STATUSES = frozenset(
    {"unverified_seed", "verified_case", "verified_failure"}
)
_CONFIDENCE = frozenset({"low", "medium", "high"})
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class KnowledgeValidationError(ValueError):
    """Raised when a knowledge source violates schema or provenance policy."""


@dataclass(frozen=True)
class KnowledgeEntry:
    """One bounded optimization rule or measured case."""

    id: str
    family: str
    preconditions: tuple[str, ...]
    action: str
    expected_signal: str
    contraindications: tuple[str, ...]
    source: str
    confidence: str
    vitis_version: str
    kind: str = "rule"
    status: str = "unverified_seed"
    tags: tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "KnowledgeEntry":
        if not isinstance(raw, Mapping):
            raise KnowledgeValidationError("knowledge entry must be an object")
        entry = cls(
            id=_required_text(raw, "id"),
            family=_required_text(raw, "family").lower(),
            preconditions=_text_tuple(raw, "preconditions"),
            action=_required_text(raw, "action"),
            expected_signal=_required_text(raw, "expected_signal"),
            contraindications=_text_tuple(raw, "contraindications"),
            source=_required_text(raw, "source"),
            confidence=_required_text(raw, "confidence").lower(),
            vitis_version=_required_text(raw, "vitis_version"),
            kind=str(raw.get("kind", "rule")).strip().lower(),
            status=str(raw.get("status", "unverified_seed")).strip().lower(),
            tags=tuple(
                sorted(
                    {
                        str(item).strip().lower()
                        for item in raw.get("tags", [])
                        if str(item).strip()
                    }
                )
            ),
            evidence=(
                dict(raw.get("evidence", {}))
                if isinstance(raw.get("evidence", {}), Mapping)
                else {}
            ),
        )
        entry.validate()
        return entry

    def validate(self) -> None:
        if self.kind not in _KINDS:
            raise KnowledgeValidationError(
                f"{self.id}: unsupported kind {self.kind!r}"
            )
        if self.status not in _STATUSES:
            raise KnowledgeValidationError(
                f"{self.id}: unsupported status {self.status!r}"
            )
        if self.confidence not in _CONFIDENCE:
            raise KnowledgeValidationError(
                f"{self.id}: unsupported confidence {self.confidence!r}"
            )
        if not self.preconditions or not self.contraindications:
            raise KnowledgeValidationError(
                f"{self.id}: preconditions and contraindications are required"
            )
        _reject_forbidden_provenance(self.source, entry_id=self.id)
        _reject_forbidden_provenance(self.evidence, entry_id=self.id)

        if self.kind == "rule":
            if self.status != "unverified_seed":
                raise KnowledgeValidationError(
                    f"{self.id}: imported rules must remain unverified_seed"
                )
            return

        if not self.source.startswith("submission:"):
            raise KnowledgeValidationError(
                f"{self.id}: measured cases require submission: provenance"
            )
        if self.kind == "verified_case":
            if self.status != "verified_case":
                raise KnowledgeValidationError(
                    f"{self.id}: successful case must have verified_case status"
                )
            _validate_success_evidence(self.id, self.evidence)
        elif self.status != "verified_failure":
            raise KnowledgeValidationError(
                f"{self.id}: failure case must have verified_failure status"
            )
        elif not self.evidence.get("observed_failure"):
            raise KnowledgeValidationError(
                f"{self.id}: failure case lacks observed_failure evidence"
            )
        else:
            _validate_q_hw_failure_evidence(self.id, self.evidence)

    def prompt_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "family": self.family,
            "status": self.status,
            "preconditions": list(self.preconditions),
            "action": self.action,
            "expected_signal": self.expected_signal,
            "contraindications": list(self.contraindications),
            "source": self.source,
            "confidence": self.confidence,
            "vitis_version": self.vitis_version,
        }
        if self.evidence:
            record["evidence"] = _bounded_value(self.evidence)
        return record


@dataclass(frozen=True)
class KnowledgeQuery:
    """Structured evidence used by every runtime retrieval."""

    source_metadata: Mapping[str, Any]
    baseline_qor: Mapping[str, Any]
    synth_diagnostics: Any
    resource_headroom: Mapping[str, Any]
    history: Sequence[Any]
    description: str = ""
    target_part: str = ""
    vitis_version: str = ""
    task_id: str = ""

    def validate(self) -> None:
        missing = []
        if not isinstance(self.source_metadata, Mapping):
            missing.append("source_metadata")
        if not isinstance(self.baseline_qor, Mapping):
            missing.append("baseline_qor")
        if self.synth_diagnostics is None:
            missing.append("synth_diagnostics")
        if not isinstance(self.resource_headroom, Mapping):
            missing.append("resource_headroom")
        if not isinstance(self.history, Sequence) or isinstance(
            self.history, (str, bytes)
        ):
            missing.append("history")
        if missing:
            raise KnowledgeValidationError(
                "structured retrieval requires: " + ", ".join(missing)
            )

    def signature(self) -> str:
        self.validate()
        payload = {
            "source_metadata": self.source_metadata,
            "baseline_qor": self.baseline_qor,
            "synth_diagnostics": self.synth_diagnostics,
            "resource_headroom": self.resource_headroom,
            "history": list(self.history),
            "description": self.description,
            "target_part": self.target_part,
            "vitis_version": self.vitis_version,
            "task_id": self.task_id,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8", errors="replace")
        return hashlib.sha256(encoded).hexdigest()


def load_knowledge_entries(
    *,
    seed_path: Path | str = _DEFAULT_SEED_PATH,
    case_paths: Sequence[Path | str] = (_DEFAULT_CASE_PATH,),
) -> tuple[KnowledgeEntry, ...]:
    """Load curated seeds and policy-compliant public submission cases."""

    entries = list(_load_entry_file(Path(seed_path), runtime_cases=False))
    for path_like in case_paths:
        path = Path(path_like)
        _validate_runtime_case_path(path)
        entries.extend(_load_entry_file(path, runtime_cases=True))

    seen: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            raise KnowledgeValidationError(
                f"duplicate knowledge id: {entry.id}"
            )
        seen.add(entry.id)
    return tuple(sorted(entries, key=lambda item: item.id))


def retrieve_knowledge(
    query: KnowledgeQuery,
    *,
    entries: Sequence[KnowledgeEntry] | None = None,
    generalized: bool = False,
) -> tuple[KnowledgeEntry, ...]:
    """Return at most one rule, one successful case, and one failure case."""

    query.validate()
    candidates = tuple(entries) if entries is not None else load_knowledge_entries()
    buckets = (
        ("rule", "unverified_seed"),
        ("verified_case", "verified_case"),
        ("failure_case", "verified_failure"),
    )
    selected: list[KnowledgeEntry] = []
    for kind, status in buckets:
        ranked = sorted(
            (
                (
                    _entry_score(entry, query, generalized=generalized),
                    entry.id,
                    entry,
                )
                for entry in candidates
                if entry.kind == kind
                and entry.status == status
                and _version_compatible(entry, query)
                and _case_structure_compatible(
                    entry, query, generalized=generalized
                )
            ),
            key=lambda item: (-item[0], item[1]),
        )
        if ranked and ranked[0][0] > 0:
            selected.append(ranked[0][2])
    return tuple(selected)


def format_for_prompt(
    matches: Sequence[KnowledgeEntry],
    *,
    max_tokens: int = MAX_KNOWLEDGE_PROMPT_TOKENS,
) -> str:
    """Serialize retrieved knowledge with a conservative token upper bound."""

    if not matches:
        return ""
    limit = max(
        300,
        min(int(max_tokens), MAX_KNOWLEDGE_PROMPT_TOKENS)
        * _CHARS_PER_TOKEN_UPPER_BOUND,
    )
    payload = {
        "policy": [
            "Retrieved knowledge is advisory; validation and measured Q_HW decide acceptance.",
            "Seeds are unverified hypotheses; check preconditions.",
            "Historical parameters are observations, not defaults; derive current values from evidence.",
            "Failures reject only exact signatures absent causal evidence.",
            "Use one family per candidate.",
        ],
        "entries": [entry.prompt_record() for entry in matches[:3]],
    }
    text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    if len(text) <= limit:
        return text

    compact_entries = []
    for entry in matches[:3]:
        compact_entries.append(
            {
                "id": entry.id,
                "kind": entry.kind,
                "family": entry.family,
                "status": entry.status,
                "preconditions": list(entry.preconditions[:2]),
                "action": entry.action[:500],
                "expected_signal": entry.expected_signal[:320],
                "contraindications": list(entry.contraindications[:2]),
                "source": entry.source,
            }
        )
    compact = json.dumps(
        {
            "policy": payload["policy"],
            "entries": compact_entries,
            "truncated": True,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 18)] + "...[truncated]"


def prompt_token_upper_bound(text: str) -> int:
    """Conservative deterministic budget estimate used by offline gates."""

    return math.ceil(len(text) / _CHARS_PER_TOKEN_UPPER_BOUND)


def resource_headroom_from_report(report: Any) -> dict[str, float | str]:
    """Project measured resource availability into normalized free capacity."""

    if report is None:
        return {}
    used = getattr(report, "resources", None) or {}
    available = getattr(report, "available", None) or {}
    result: dict[str, float | str] = {}
    for key in ("LUT", "FF", "DSP", "BRAM_18K", "URAM"):
        capacity = available.get(key)
        value = used.get(key)
        if not isinstance(capacity, (int, float)) or capacity <= 0:
            result[key] = "unknown"
            continue
        numeric = value if isinstance(value, (int, float)) else 0
        result[key] = round(max(0.0, (capacity - numeric) / capacity), 4)
    return result


def baseline_qor_from_report(
    report: Any,
    *,
    q_hw: float | None,
    bottleneck: str = "",
) -> dict[str, Any]:
    """Build the compact baseline-QoR portion of a retrieval query."""

    if report is None:
        return {
            "latency_worst": None,
            "clock_period_ns": None,
            "resources": {},
            "loop_metrics": [],
            "q_hw": q_hw,
            "bottleneck": bottleneck,
        }
    loops = []
    for loop in (getattr(report, "loop_metrics", None) or [])[:12]:
        loops.append(
            {
                "name": loop.get("name"),
                "trip_count": loop.get("trip_count"),
                "latency": loop.get("latency"),
                "pipeline_ii": loop.get("pipeline_ii"),
            }
        )
    return {
        "latency_worst": getattr(report, "latency_worst", None),
        "interval_max": getattr(report, "interval_max", None),
        "clock_period_ns": getattr(report, "clock_period_ns", None),
        "resources": dict(getattr(report, "resources", None) or {}),
        "loop_metrics": loops,
        "q_hw": q_hw,
        "bottleneck": bottleneck,
    }


def _load_entry_file(
    path: Path, *, runtime_cases: bool
) -> tuple[KnowledgeEntry, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KnowledgeValidationError(
            f"cannot load knowledge file {path}: {exc}"
        ) from exc
    if not isinstance(raw, Mapping):
        raise KnowledgeValidationError(f"{path}: root must be an object")
    if raw.get("schema_version") != KNOWLEDGE_SCHEMA_VERSION:
        raise KnowledgeValidationError(
            f"{path}: unsupported schema_version"
        )
    records = raw.get("entries")
    if not isinstance(records, list):
        raise KnowledgeValidationError(f"{path}: entries must be a list")
    parsed = tuple(KnowledgeEntry.from_dict(record) for record in records)
    if not runtime_cases and any(
        entry.kind != "rule" or entry.status != "unverified_seed"
        for entry in parsed
    ):
        raise KnowledgeValidationError(
            f"{path}: seed files may contain only unverified rule entries"
        )
    if runtime_cases and any(entry.kind == "rule" for entry in parsed):
        raise KnowledgeValidationError(
            f"{path}: runtime case files cannot introduce rules"
        )
    return parsed


def _required_text(raw: Mapping[str, Any], key: str) -> str:
    value = str(raw.get(key, "")).strip()
    if not value:
        raise KnowledgeValidationError(f"missing required field: {key}")
    return value


def _text_tuple(raw: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise KnowledgeValidationError(f"{key} must be a list")
    items = tuple(str(item).strip() for item in value if str(item).strip())
    if not items:
        raise KnowledgeValidationError(f"{key} cannot be empty")
    return items


def _validate_runtime_case_path(path: Path) -> None:
    resolved = path.resolve(strict=False)
    lowered = {part.lower() for part in resolved.parts}
    forbidden = lowered & _FORBIDDEN_RUNTIME_COMPONENTS
    if forbidden:
        raise KnowledgeValidationError(
            f"runtime case path uses forbidden component: {sorted(forbidden)}"
        )


def _reject_forbidden_provenance(value: Any, *, entry_id: str) -> None:
    for text in _iter_strings(value):
        normalized = text.replace("\\", "/").lower()
        parts = {part for part in normalized.split("/") if part}
        if parts & _FORBIDDEN_RUNTIME_COMPONENTS:
            raise KnowledgeValidationError(
                f"{entry_id}: forbidden provenance component"
            )


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _iter_strings(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            yield from _iter_strings(item)


def _validate_success_evidence(
    entry_id: str, evidence: Mapping[str, Any]
) -> None:
    required_true = ("interface_ok", "csim_ok", "synth_ok", "frequency_ok", "resource_ok")
    missing = [key for key in required_true if evidence.get(key) is not True]
    if evidence.get("cosim_required") and evidence.get("cosim_ok") is not True:
        missing.append("cosim_ok")
    before = evidence.get("q_hw_before")
    after = evidence.get("q_hw_after")
    if not isinstance(before, (int, float)) or not isinstance(
        after, (int, float)
    ) or not after > before:
        missing.append("q_hw_improvement")
    if missing:
        raise KnowledgeValidationError(
            f"{entry_id}: verified case lacks gates: {sorted(set(missing))}"
        )


def _validate_q_hw_failure_evidence(
    entry_id: str, evidence: Mapping[str, Any]
) -> None:
    stage = str(evidence.get("stage", "") or "")
    has_q_hw = "q_hw_before" in evidence or "q_hw_after" in evidence
    if stage != "q_hw_selection" and not has_q_hw:
        return
    required_true = ("interface_ok", "csim_ok", "synth_ok", "frequency_ok", "resource_ok")
    missing = [key for key in required_true if evidence.get(key) is not True]
    if evidence.get("cosim_required") and evidence.get("cosim_ok") is not True:
        missing.append("cosim_ok")
    before = evidence.get("q_hw_before")
    after = evidence.get("q_hw_after")
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        missing.append("q_hw_measurement")
    elif after > before:
        missing.append("non_improving_q_hw")
    if missing:
        raise KnowledgeValidationError(
            f"{entry_id}: q_hw failure case lacks gates: {sorted(set(missing))}"
        )


def _bounded_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        return "<bounded>"
    if isinstance(value, Mapping):
        return {
            str(key)[:80]: _bounded_value(item, depth=depth + 1)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))[:20]
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_bounded_value(item, depth=depth + 1) for item in value[:20]]
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:200]


def _tokens(value: Any) -> set[str]:
    text = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    ).lower()
    return set(_TOKEN_RE.findall(text))


def _entry_tokens(entry: KnowledgeEntry) -> set[str]:
    return _tokens(
        {
            "family": entry.family,
            "preconditions": entry.preconditions,
            "action": entry.action,
            "expected_signal": entry.expected_signal,
            "contraindications": entry.contraindications,
            "tags": entry.tags,
            "evidence": entry.evidence,
        }
    )


def _entry_score(
    entry: KnowledgeEntry,
    query: KnowledgeQuery,
    *,
    generalized: bool = False,
) -> float:
    entry_tokens = _entry_tokens(entry)
    score = 0.0
    score += 3.0 * len(entry_tokens & _tokens(query.source_metadata))
    score += 2.0 * len(entry_tokens & _tokens(query.baseline_qor))
    score += 4.0 * len(entry_tokens & _tokens(query.synth_diagnostics))
    score += 2.0 * len(entry_tokens & _tokens(query.resource_headroom))
    score += 3.0 * len(entry_tokens & _tokens(list(query.history)))
    score += 1.0 * len(entry_tokens & _tokens(query.description))

    signals = _family_signals(query)
    score += 24.0 * signals.get(entry.family, 0.0)
    score += _entry_specific_boost(entry, query, generalized=generalized)
    if entry.kind == "verified_case":
        score += 3.0
    if entry.kind == "failure_case":
        history_tokens = _tokens(list(query.history))
        if entry_tokens & history_tokens:
            score += 8.0
    return score


def _family_signals(query: KnowledgeQuery) -> dict[str, float]:
    diagnostic = _tokens(query.synth_diagnostics)
    description = _tokens(query.description)
    metadata = query.source_metadata
    combined = diagnostic | description | _tokens(metadata)
    signals: dict[str, float] = {"report_driven": 0.15}

    loops = metadata.get("loops", []) if isinstance(metadata, Mapping) else []
    qor_loops = (
        query.baseline_qor.get("loop_metrics", [])
        if isinstance(query.baseline_qor, Mapping)
        else []
    )
    all_loops = [
        loop
        for loop in [*loops, *qor_loops]
        if isinstance(loop, Mapping)
    ]
    arrays = metadata.get("arrays", []) if isinstance(metadata, Mapping) else []
    loop_iis = [
        loop.get("pipeline_ii")
        for loop in all_loops
        if isinstance(loop.get("pipeline_ii"), (int, float))
    ]
    nesting = [
        loop.get("nesting_depth")
        for loop in loops
        if isinstance(loop, Mapping)
        and isinstance(loop.get("nesting_depth"), (int, float))
    ]

    if (
        {"memory", "port"} <= diagnostic
        or {"memory", "ports"} <= diagnostic
        or "448" in diagnostic
        or {"parallel", "reads"} <= diagnostic
        or "contended" in diagnostic
    ):
        signals["array_partition"] = 1.0
    if {"adjacent", "bandwidth"} & combined or "reshape" in combined:
        signals["array_reshape"] = 0.9
    if {"reduction", "accumulate", "sum", "dot", "recurrence"} & combined:
        signals["reduction"] = 1.0
    if {"gemm", "matmul", "multiply", "multiplication"} & combined and (
        max(nesting, default=0) >= 1 or len(loops) >= 2
    ):
        signals["gemm"] = 1.0
    if {
        "cholesky",
        "lu",
        "factorization",
        "decomposition",
        "triangular",
        "solve",
    } & combined:
        signals["linear_algebra_factorization"] = 1.0
    if {"stencil", "neighbor", "grid", "window"} & combined:
        signals["stencil"] = 1.0
    if {"dataflow", "stream", "fifo", "producer", "consumer", "deadlock"} & combined:
        signals["dataflow"] = 1.0
    if {"stream", "fifo", "axis", "tlast", "side", "channel"} & combined:
        signals["stream_fifo"] = 1.0
    if {
        "bank",
        "banking",
        "bundle",
        "burst",
        "m_axi",
        "local",
        "buffer",
    } & combined:
        signals["memory_banking"] = 1.0
    if {"flatten", "perfect", "nest"} & combined:
        signals["loop_flatten"] = 1.0
    if {"fission", "split", "separate"} & combined:
        signals["loop_fission"] = 1.0
    if {"fusion", "fuse", "sweep", "sweeps"} & combined:
        signals["loop_fusion"] = 1.0
    if {"bitwidth", "fixed", "ap_fixed", "ap_int", "range"} & combined:
        signals["bitwidth"] = 1.0
    if {
        "aes",
        "cipher",
        "crypto",
        "encrypt",
        "encryption",
        "decrypt",
        "decryption",
        "sbox",
        "substitution",
        "byte",
        "xor",
        "galois",
    } & combined:
        signals["crypto_lookup"] = 1.0
    if {"math", "floating", "float", "cordic", "fir", "fft", "unsafe"} & combined:
        signals["math_kernel"] = 1.0
    if {"interface", "m_axi", "s_axilite", "depth", "bundle"} & combined:
        signals["interface"] = 1.0
    if {"failure", "fail", "rejected", "deadlock", "noop", "no", "op"} & combined:
        signals["failure_triage"] = 1.0

    # Task descriptions carry architectural intent.  Give explicit families
    # enough weight to outrank generic report/II vocabulary that is present in
    # nearly every synthesis summary.
    if {"gemm", "matmul"} & description or {
        "matrix",
        "multiplication",
    } <= description:
        signals["gemm"] = max(signals.get("gemm", 0.0), 2.5)
    if {
        "cholesky",
        "lu",
        "factorization",
        "decomposition",
        "triangular",
    } & description:
        signals["linear_algebra_factorization"] = max(
            signals.get("linear_algebra_factorization", 0.0), 2.4
        )
    if {"stencil", "neighborhood"} & description or (
        "grid" in description and {"window", "neighbor"} & description
    ):
        signals["stencil"] = max(signals.get("stencil", 0.0), 2.5)
    if {"reduction", "dot", "popcount", "accumulate"} & description or {
        "cumulative",
        "sum",
    } <= description:
        signals["reduction"] = max(signals.get("reduction", 0.0), 2.0)
    if "dataflow" in description and {
        "producer",
        "consumer",
        "stage",
        "stream",
    } & description:
        signals["dataflow"] = max(signals.get("dataflow", 0.0), 2.0)
    if {"stream", "fifo", "axis"} & description:
        signals["stream_fifo"] = max(signals.get("stream_fifo", 0.0), 2.0)
    if {"banking", "bank", "bundle", "burst"} & description:
        signals["memory_banking"] = max(
            signals.get("memory_banking", 0.0), 2.0
        )
    if "flatten" in description:
        signals["loop_flatten"] = max(signals.get("loop_flatten", 0.0), 2.0)
    if "fission" in description or "split" in description:
        signals["loop_fission"] = max(signals.get("loop_fission", 0.0), 2.0)
    if "fusion" in description or "fuse" in description:
        signals["loop_fusion"] = max(signals.get("loop_fusion", 0.0), 2.0)
    if {"bitwidth", "ap_fixed", "ap_int"} & description:
        signals["bitwidth"] = max(signals.get("bitwidth", 0.0), 2.0)
    if {
        "aes",
        "cipher",
        "crypto",
        "encrypt",
        "encryption",
        "sbox",
        "substitution",
        "byte",
    } & description:
        signals["crypto_lookup"] = max(
            signals.get("crypto_lookup", 0.0), 2.4
        )
    if {"cordic", "fir", "fft"} & description or {
        "math",
        "kernel",
    } <= description:
        signals["math_kernel"] = max(signals.get("math_kernel", 0.0), 2.0)
    if {"interface", "s_axilite", "m_axi"} & description:
        signals["interface"] = max(signals.get("interface", 0.0), 2.0)
    if {"failure", "fail", "rejected", "noop", "deadlock"} & description:
        signals["failure_triage"] = max(
            signals.get("failure_triage", 0.0), 2.0
        )
    if loop_iis and max(loop_iis) > 1:
        signals["report_driven"] = 0.9
        if not (
            {"memory", "port"} <= diagnostic
            or {"memory", "ports"} <= diagnostic
            or "448" in diagnostic
        ):
            signals["pipeline"] = 0.75
    elif loops:
        # Loop length and PipelineII=1 are observations, not evidence for a
        # particular transformation family.
        signals["report_driven"] = max(
            signals.get("report_driven", 0.0), 0.6
        )

    if any(
        isinstance(array, Mapping)
        and isinstance(array.get("access_pattern"), Mapping)
        and array["access_pattern"].get("kind") == "contiguous"
        for array in arrays
    ) and {"lane", "packed", "adjacent"} & combined:
        signals["array_reshape"] = 1.0
    return signals


def _entry_specific_boost(
    entry: KnowledgeEntry,
    query: KnowledgeQuery,
    *,
    generalized: bool = False,
) -> float:
    """Disambiguate entries within one family using explicit evidence."""

    description = _tokens(query.description)
    combined = (
        _tokens(query.synth_diagnostics)
        | description
        | _tokens(query.baseline_qor)
    )
    metadata = query.source_metadata
    loops = metadata.get("loops", []) if isinstance(metadata, Mapping) else []
    qor_loops = (
        query.baseline_qor.get("loop_metrics", [])
        if isinstance(query.baseline_qor, Mapping)
        else []
    )
    loop_iis = [
        loop.get("pipeline_ii")
        for loop in [*loops, *qor_loops]
        if isinstance(loop, Mapping)
        and isinstance(loop.get("pipeline_ii"), (int, float))
    ]
    nested = (
        len(loops) >= 2
        or any(
            isinstance(loop, Mapping)
            and isinstance(loop.get("nesting_depth"), (int, float))
            and loop["nesting_depth"] >= 1
            for loop in loops
        )
    )

    if entry.id == "hlsgen.report_driven.ii_triage":
        explicit_architecture = bool(
            {"gemm", "matmul", "stencil", "neighborhood"} & description
            or {"matrix", "multiplication"} <= description
        )
        if loop_iis and max(loop_iis) > 1 and (
            {"recurrence", "timing", "target", "violation"} & combined
        ) and not explicit_architecture:
            return 28.0
    if entry.id == "hlsgen.report_driven.baseline_first":
        if {"baseline", "report", "measurable", "stacking"} & combined:
            return 22.0
    if entry.id == "hlsgen.gemm.tiled_reuse" and (
        {"gemm", "matmul"} & description
        or {"matrix", "multiplication"} <= description
    ):
        return 18.0
    if entry.id == "hlsgen.linear_algebra.factorization_dependency_guard" and (
        {
            "cholesky",
            "lu",
            "factorization",
            "decomposition",
            "triangular",
        }
        & description
    ):
        return 18.0
    if entry.id == "hlsgen.stencil.line_buffer" and (
        {"stencil", "neighborhood"} & description
        or ("grid" in description and {"window", "neighbor"} & description)
    ):
        return 18.0
    if entry.id == "hlsgen.crypto.lookup_round_guard" and (
        {
            "aes",
            "cipher",
            "crypto",
            "encrypt",
            "encryption",
            "sbox",
            "substitution",
            "byte",
        }
        & description
    ):
        return 18.0
    if entry.id == "hlsgen.pipeline.outer_concurrency":
        if nested and "outer" in combined and (
            {"inner", "concurrency", "concurrent"} & combined
        ):
            return 34.0
    if entry.kind != "rule" and not generalized:
        source_tokens = _tokens(entry.source)
        if (
            "dot_product" in entry.tags
            and {"dotproduct", "optimize"} <= source_tokens
            and ({"dot", "product"} <= description or "dotproduct" in description)
        ):
            return 36.0
        if "popcount" in entry.tags and "popcount" in description:
            return 36.0
    return 0.0


def _version_compatible(
    entry: KnowledgeEntry, query: KnowledgeQuery
) -> bool:
    if entry.kind != "rule":
        measured_part = str(entry.evidence.get("target_part", "") or "").strip()
        requested_part = str(query.target_part or "").strip()
        if measured_part and requested_part and measured_part != requested_part:
            return False
    requested = str(query.vitis_version or "").strip()
    if not requested or entry.vitis_version.endswith("+"):
        return True
    entry_version = entry.vitis_version.strip()
    return requested == entry_version or requested.startswith(entry_version)


def _case_structure_compatible(
    entry: KnowledgeEntry,
    query: KnowledgeQuery,
    *,
    generalized: bool = False,
) -> bool:
    """Reject measured examples whose workload semantics are not compatible."""

    if entry.kind == "rule":
        description = _tokens(query.description)
        architecture_requirements = {
            "gemm": {"gemm", "matmul", "matrix", "multiplication"},
            "stencil": {"stencil", "neighborhood", "window", "grid"},
            "crypto_lookup": {
                "aes",
                "cipher",
                "crypto",
                "encrypt",
                "encryption",
                "sbox",
                "substitution",
            },
            "linear_algebra_factorization": {
                "cholesky",
                "lu",
                "factorization",
                "decomposition",
                "triangular",
            },
        }
        required = architecture_requirements.get(entry.family)
        return required is None or bool(required & description)
    if generalized and _source_matches_task_id(entry.source, query.task_id):
        return False
    description = _tokens(query.description)
    specific_workloads = {
        "aes",
        "cipher",
        "des",
        "fft",
        "fir",
        "gemm",
        "matmul",
        "stencil",
        "cordic",
        "popcount",
    }
    entry_semantics = set(entry.tags)
    if not generalized:
        entry_semantics |= _tokens(entry.source)
    if {"aes", "cipher", "des"} & description:
        return False
    if {"dot", "product"} <= description or "dotproduct" in description:
        if "dot_product" not in entry.tags and "dotproduct" not in entry_semantics:
            return False
    for token in specific_workloads & description:
        if token not in entry_semantics:
            return False
    if "dot_product" in entry.tags:
        return "dotproduct" in description or {
            "dot",
            "product",
        } <= description
    if "popcount" in entry.tags:
        return "popcount" in description
    for family_tag in ("gemm", "stencil", "cordic"):
        if family_tag in entry.tags:
            return family_tag in description
    return True


def _source_matches_task_id(source: str, task_id: str) -> bool:
    normalized_task = _normalize_identifier(task_id)
    if not normalized_task:
        return False
    normalized_source = _normalize_identifier(source)
    if normalized_task in normalized_source:
        return True
    task_tokens = set(_TOKEN_RE.findall(task_id.lower()))
    source_tokens = set(_TOKEN_RE.findall(source.lower()))
    return bool(task_tokens and task_tokens <= source_tokens)


def _normalize_identifier(value: str) -> str:
    return "".join(_TOKEN_RE.findall(str(value).lower()))
