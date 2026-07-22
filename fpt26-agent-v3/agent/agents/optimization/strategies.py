"""Strategy contract enforcement and candidate fingerprinting — pure functions."""

from __future__ import annotations

import re
from typing import Any

_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _candidate_fingerprint(code: str) -> str:
    """Normalize comments and layout before comparing measured candidates."""
    without_blocks = _BLOCK_COMMENT_RE.sub("", code)
    normalized = []
    for line in without_blocks.splitlines():
        line = line.split("//", 1)[0]
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            normalized.append(line)
    return "\n".join(normalized)


def _without_hls_pragmas_fingerprint(code: str) -> str:
    """Normalize source while omitting standalone HLS directive lines."""
    without_blocks = _BLOCK_COMMENT_RE.sub("", code)
    normalized = []
    for line in without_blocks.splitlines():
        line = line.split("//", 1)[0]
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if re.match(r"^#\s*pragma\s+HLS\b", line, re.IGNORECASE):
            continue
        normalized.append(line)
    return "\n".join(normalized)


def _hls_pragmas(code: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in code.splitlines()
        if re.match(r"^\s*#\s*pragma\s+HLS\b", line, re.IGNORECASE)
    ]


def _source_array_rank(code: str, variable: str) -> int | None:
    ranks = [
        brackets.count("[")
        for brackets in re.findall(rf"\b{re.escape(variable)}\s*((?:\[[^\[\]]*\]\s*)+)", code)
    ]
    return max(ranks) if ranks else None


def _strategy_contract_violation(
    best: str, candidate: str, strategy: dict[str, Any] | None,
) -> str | None:
    """Enforce mutually distinct candidate families before tool spending."""
    if not strategy:
        return None
    name = strategy.get("name")
    best_pragmas = {p.lower() for p in _hls_pragmas(best)}
    candidate_pragmas = _hls_pragmas(candidate)
    added_pragmas = [p for p in candidate_pragmas if p.lower() not in best_pragmas]
    source_changed = (
        _without_hls_pragmas_fingerprint(best)
        != _without_hls_pragmas_fingerprint(candidate)
    )

    if name == "conservative_loop_parallelism":
        if source_changed:
            return "conservative lane must preserve non-pragma source"
        if len(added_pragmas) != 1 or not re.search(r"\bUNROLL\b", added_pragmas[0], re.IGNORECASE):
            return "conservative lane requires exactly one added UNROLL pragma"
        if re.search(r"\b(ARRAY_PARTITION|ARRAY_RESHAPE|PIPELINE)\b", added_pragmas[0], re.IGNORECASE):
            return "conservative lane cannot mix banking or pipeline directives"
        return None

    if name == "source_reduction_restructure":
        if added_pragmas:
            return "source-restructure lane cannot add HLS pragmas"
        if not source_changed:
            return "source-restructure lane must change the non-pragma architecture"
        return None

    if name == "speed_first_parallel_architecture":
        if source_changed:
            return None
        unrolls = [p for p in added_pragmas if re.search(r"\bUNROLL\b", p, re.IGNORECASE)]
        if not unrolls:
            return "speed-first lane requires a distinct parallel architecture"
        for pragma in unrolls:
            factor = re.search(r"\bfactor\s*=\s*(\d+)", pragma, re.IGNORECASE)
            if factor and int(factor.group(1)) <= 2:
                return "speed-first lane cannot reuse conservative factor<=2"
        return None

    return f"unknown strategy contract: {name}"


def _is_minimum_unroll_frontier(
    best: str, candidate: str, card: Any, best_report: Any,
) -> bool:
    """Return true when factor=2 is the only measured program change and loses Q_HW."""
    pragmas = [
        l.strip() for l in candidate.splitlines()
        if re.search(r"#\s*pragma\s+HLS\b", l, re.IGNORECASE)
    ]
    if len(pragmas) != 1 or not re.search(r"\bUNROLL\b.*\bfactor\s*=\s*2\b", pragmas[0], re.IGNORECASE):
        return False
    if _without_hls_pragmas_fingerprint(best) != _without_hls_pragmas_fingerprint(candidate):
        return False
    loop_iis = [
        loop.get("pipeline_ii")
        for loop in (getattr(best_report, "loop_metrics", None) or [])
        if loop.get("pipeline_ii") is not None
    ]
    return bool(loop_iis and all(ii == 1 for ii in loop_iis)
                and card.latency_ratio > 1.0 and card.area_growth > 1.0)
