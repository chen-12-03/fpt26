"""Strategy contract enforcement and candidate fingerprinting — pure functions."""

from __future__ import annotations

import re
from typing import Any

_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_SINGLE_STATEMENT_FOR_RE = re.compile(
    r"(?P<header>\bfor\s*\([^{}]*\)\s*)"
    r"\{\s*(?P<body>[^{};]+;)\s*\}",
    re.DOTALL,
)


def _strip_comments(code: str) -> str:
    without_blocks = _BLOCK_COMMENT_RE.sub("", code)
    return "\n".join(
        line.split("//", 1)[0] for line in without_blocks.splitlines()
    )


def _normalize_optional_for_braces(code: str) -> str:
    """Remove braces only around one plain ``for`` body statement."""
    current = code
    while True:
        def replace(match: re.Match[str]) -> str:
            body = match.group("body")
            if "#" in body or re.search(
                r"\b(?:for|while|if|switch|do)\b", body
            ):
                return match.group(0)
            return match.group("header") + body.strip()

        updated = _SINGLE_STATEMENT_FOR_RE.sub(replace, current)
        if updated == current:
            return current
        current = updated


def _candidate_fingerprint(code: str) -> str:
    """Normalize comments and layout before comparing measured candidates."""
    normalized = _normalize_optional_for_braces(_strip_comments(code))
    return re.sub(r"\s+", " ", normalized).strip()


def _without_hls_pragmas_fingerprint(code: str) -> str:
    """Normalize source while omitting standalone HLS directive lines."""
    without_blocks = _strip_comments(code)
    normalized = []
    for line in without_blocks.splitlines():
        line = line.split("//", 1)[0]
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if re.match(r"^#\s*pragma\s+HLS\b", line, re.IGNORECASE):
            continue
        normalized.append(line)
    return re.sub(r"\s+", " ", " ".join(normalized)).strip()


def _top_function_inline_noop(
    best: str, candidate: str, top_function: str
) -> bool:
    """Identify a top-function INLINE-only edit, which HLS cannot realize."""
    if (
        _without_hls_pragmas_fingerprint(best)
        != _without_hls_pragmas_fingerprint(candidate)
    ):
        return False
    best_pragmas = {pragma.lower() for pragma in _hls_pragmas(best)}
    added = [
        pragma
        for pragma in _hls_pragmas(candidate)
        if pragma.lower() not in best_pragmas
    ]
    if not added or any(
        re.fullmatch(
            r"#\s*pragma\s+HLS\s+INLINE(?:\s+OFF)?",
            pragma,
            re.IGNORECASE,
        )
        is None
        for pragma in added
    ):
        return False
    source = _strip_comments(candidate)
    return (
        re.search(
            rf"\b{re.escape(top_function)}\s*\([^;{{}}]*\)\s*\{{"
            rf"\s*#\s*pragma\s+HLS\s+INLINE(?:\s+OFF)?\b",
            source,
            re.IGNORECASE,
        )
        is not None
    )


def _hls_pragmas(code: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in code.splitlines()
        if re.match(r"^\s*#\s*pragma\s+HLS\b", line, re.IGNORECASE)
    ]


def candidate_action_summary(best: str, candidate: str) -> dict[str, Any]:
    """Return a bounded semantic action summary for public run evidence."""

    best_pragmas = {pragma.lower(): pragma for pragma in _hls_pragmas(best)}
    candidate_pragmas = {
        pragma.lower(): pragma for pragma in _hls_pragmas(candidate)
    }
    added = [
        candidate_pragmas[key]
        for key in sorted(candidate_pragmas.keys() - best_pragmas.keys())
    ]
    removed = [
        best_pragmas[key]
        for key in sorted(best_pragmas.keys() - candidate_pragmas.keys())
    ]
    families = sorted(
        {
            match.group(1).upper()
            for pragma in added
            for match in [
                re.search(
                    r"#\s*pragma\s+HLS\s+([A-Za-z_]+)",
                    pragma,
                    re.IGNORECASE,
                )
            ]
            if match is not None
        }
    )
    source_changed = (
        _without_hls_pragmas_fingerprint(best)
        != _without_hls_pragmas_fingerprint(candidate)
    )
    if source_changed and not families:
        families = ["SOURCE_RESTRUCTURE"]
    return {
        "families": families[:4],
        "added_pragmas": added[:8],
        "removed_pragmas": removed[:8],
        "source_changed": source_changed,
    }


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
