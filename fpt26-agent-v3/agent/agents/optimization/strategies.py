"""Strategy contract enforcement and candidate fingerprinting — pure functions."""

from __future__ import annotations

import re
from typing import Any

from agent.analysis.source_metadata import (
    evaluate_source_banking_trial,
    extract_design_metadata,
)

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


def _canonical_optimization_family(directive: str) -> str:
    """Collapse directive aliases that express the same optimization family."""
    name = directive.upper()
    if name == "UNROLL":
        return "LOOP_UNROLL"
    if name in {"ARRAY_PARTITION", "ARRAY_RESHAPE"}:
        return "MEMORY_BANKING"
    if name in {"BIND_STORAGE", "BIND_OP", "ALLOCATION"}:
        return "RESOURCE_BINDING"
    return name


def _metadata_action_targets(
    best: str,
    candidate: str,
    loop_metrics: list[dict[str, Any]] | None = None,
) -> tuple[set[str], set[str]]:
    """Identify loop/array targets whose HLS metadata changed."""
    best_metadata = extract_design_metadata(best, loop_metrics=loop_metrics)
    candidate_metadata = extract_design_metadata(
        candidate, loop_metrics=loop_metrics
    )

    loop_targets: set[str] = set()
    best_loops = list(best_metadata.loops)
    candidate_loops = list(candidate_metadata.loops)
    for index, loop in enumerate(candidate_loops):
        prior = best_loops[index] if index < len(best_loops) else {}
        for key in ("pipeline", "unroll"):
            value = loop.get(key)
            if value != prior.get(key) and isinstance(value, dict) and value.get(
                "enabled"
            ):
                report_name = str(loop.get("report_loop_name") or "")
                loop_targets.add(
                    report_name
                    if report_name and report_name != "unknown"
                    else str(loop.get("name") or f"loop_{index}")
                )

    array_targets: set[str] = set()
    best_arrays = {
        str(item.get("name")): item
        for item in best_metadata.arrays
        if item.get("name")
    }
    for item in candidate_metadata.arrays:
        name = str(item.get("name") or "")
        if not name:
            continue
        prior = best_arrays.get(name, {})
        if any(
            item.get(key, "none") != prior.get(key, "none")
            and item.get(key, "none") != "none"
            for key in ("partition", "reshape")
        ):
            array_targets.add(name)
    return loop_targets, array_targets


def _semantic_action_signature(action: dict[str, Any]) -> str:
    """Return a factor/layout-insensitive signature for an optimization action."""
    families = sorted(
        str(value) for value in action.get("families", []) if str(value)
    )
    targets = action.get("targets", {})
    target_tokens: list[str] = []
    if isinstance(targets, dict):
        for kind in ("loops", "arrays", "functions"):
            values = targets.get(kind, [])
            if isinstance(values, list):
                target_tokens.extend(
                    f"{kind[:-1]}:{value}"
                    for value in values
                    if str(value)
                )
    return "|".join(
        [
            "families=" + ",".join(families),
            "targets=" + ",".join(sorted(target_tokens)),
            f"source_changed={bool(action.get('source_changed'))}",
        ]
    )


def candidate_action_summary(
    best: str,
    candidate: str,
    *,
    top_function: str = "",
    loop_metrics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
    directive_names = {
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
    families = sorted(
        {
            _canonical_optimization_family(name)
            for name in directive_names
        }
    )
    source_changed = (
        _without_hls_pragmas_fingerprint(best)
        != _without_hls_pragmas_fingerprint(candidate)
    )
    if source_changed and not families:
        families = ["SOURCE_RESTRUCTURE"]

    loop_targets, array_targets = _metadata_action_targets(
        best, candidate, loop_metrics
    )
    for pragma in added:
        variable = re.search(
            r"\bvariable\s*=\s*([A-Za-z_]\w*)",
            pragma,
            re.IGNORECASE,
        )
        if variable and re.search(
            r"\b(?:ARRAY_PARTITION|ARRAY_RESHAPE|BIND_STORAGE)\b",
            pragma,
            re.IGNORECASE,
        ):
            array_targets.add(variable.group(1))
    function_targets: set[str] = set()
    if top_function and (
        source_changed
        or directive_names
        & {"DATAFLOW", "INLINE", "ALLOCATION", "BIND_OP"}
        or ("PIPELINE" in directive_names and not loop_targets)
    ):
        function_targets.add(top_function)

    summary = {
        "families": families[:4],
        "targets": {
            "loops": sorted(loop_targets)[:8],
            "arrays": sorted(array_targets)[:8],
            "functions": sorted(function_targets)[:8],
        },
        "added_pragmas": added[:8],
        "removed_pragmas": removed[:8],
        "source_changed": source_changed,
    }
    summary["semantic_signature"] = _semantic_action_signature(summary)
    return summary


def _anti_repeat_action_violation(
    action: dict[str, Any],
    measured_rejections: list[dict[str, Any]],
) -> str | None:
    """Reject any family or target already measured as non-improving."""
    action_families = {
        str(value) for value in action.get("families", []) if str(value)
    }
    action_targets = action.get("targets", {})
    flattened_targets = {
        f"{kind}:{value}"
        for kind in ("loops", "arrays", "functions")
        for value in (
            action_targets.get(kind, [])
            if isinstance(action_targets, dict)
            and isinstance(action_targets.get(kind, []), list)
            else []
        )
        if str(value)
    }
    action_signature = str(
        action.get("semantic_signature") or _semantic_action_signature(action)
    )

    for entry in measured_rejections:
        prior = entry.get("action", entry)
        if not isinstance(prior, dict):
            continue
        prior_signature = str(
            prior.get("semantic_signature")
            or _semantic_action_signature(prior)
        )
        if action_signature == prior_signature:
            return (
                "semantic equivalent of a measured Q_HW rejection "
                f"({action_signature})"
            )
        prior_families = {
            str(value) for value in prior.get("families", []) if str(value)
        }
        repeated_families = sorted(action_families & prior_families)
        if repeated_families:
            return (
                "optimization family already measured without Q_HW improvement: "
                + ", ".join(repeated_families)
            )
        prior_targets = prior.get("targets", {})
        prior_flattened = {
            f"{kind}:{value}"
            for kind in ("loops", "arrays", "functions")
            for value in (
                prior_targets.get(kind, [])
                if isinstance(prior_targets, dict)
                and isinstance(prior_targets.get(kind, []), list)
                else []
            )
            if str(value)
        }
        repeated_targets = sorted(flattened_targets & prior_flattened)
        if repeated_targets:
            return (
                "optimization target already measured without Q_HW improvement: "
                + ", ".join(repeated_targets)
            )
    return None


def _report_supported_action_violation(
    action: dict[str, Any],
    report: Any,
    measured_action_contract: dict[str, Any] | None,
    source_banking_evidence: list[dict[str, Any]] | None = None,
    source_metadata: dict[str, Any] | None = None,
) -> str | None:
    """Reject actions contradicted by report or deterministic source evidence."""
    families = {
        str(value) for value in action.get("families", []) if str(value)
    }
    loop_metrics = list(getattr(report, "loop_metrics", None) or [])
    all_loops_measured_at_ii_one = bool(loop_metrics) and all(
        loop.get("pipeline_ii") == 1 for loop in loop_metrics
    )
    if "PIPELINE" in families:
        targets = action.get("targets", {})
        target_loops = {
            str(value)
            for value in (
                targets.get("loops", [])
                if isinstance(targets, dict)
                and isinstance(targets.get("loops", []), list)
                else []
            )
            if str(value)
        }
        ii_one_targets = {
            str(loop.get("name") or "")
            for loop in loop_metrics
            if loop.get("pipeline_ii") == 1
        }
        repeated_ii_one = sorted(target_loops & ii_one_targets)
        if repeated_ii_one:
            return (
                "target loop(s) already have PipelineII=1; another PIPELINE "
                "action is forbidden: " + ", ".join(repeated_ii_one)
            )
        if all_loops_measured_at_ii_one:
            return (
                "all measured loops already have PipelineII=1; another PIPELINE "
                "action is forbidden"
            )
    if "LOOP_UNROLL" in families and isinstance(source_metadata, dict):
        targets = action.get("targets", {})
        target_loops = set(
            targets.get("loops", [])
            if isinstance(targets, dict)
            and isinstance(targets.get("loops", []), list)
            else []
        )
        for loop in source_metadata.get("loops", []):
            if not isinstance(loop, dict):
                continue
            names = {
                str(loop.get("name") or ""),
                str(loop.get("report_loop_name") or ""),
            }
            if not target_loops.intersection(names):
                continue
            auto = loop.get("auto_parallelism", {})
            if isinstance(auto, dict) and auto.get("hierarchy_sensitive"):
                ancestors = ", ".join(auto.get("pipeline_ancestors", []))
                detail = (
                    f" under inferred-pipelined ancestor(s) {ancestors}"
                    if ancestors
                    else ""
                )
                return (
                    "explicit UNROLL targets a loop whose Vitis auto "
                    f"pipeline/unroll/flatten hierarchy is already active{detail}; "
                    "the edit may move the pipeline boundary and is forbidden "
                    "without a measured hierarchy-specific action contract"
                )
    if "MEMORY_BANKING" in families and not measured_action_contract:
        banking_violation = _source_banking_action_violation(
            action, source_banking_evidence or []
        )
        if banking_violation is not None:
            return banking_violation
    return None


def _source_banking_action_violation(
    action: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> str | None:
    """Require every source-backed storage action to improve its access map."""
    by_array = {
        str(item.get("array") or ""): item
        for item in evidence
        if isinstance(item, dict) and item.get("array")
    }
    targets = action.get("targets", {})
    arrays = (
        [str(value) for value in targets.get("arrays", []) if str(value)]
        if isinstance(targets, dict)
        and isinstance(targets.get("arrays", []), list)
        else []
    )
    if not arrays:
        return (
            "ARRAY_PARTITION/RESHAPE requires an exact measured or source-proven "
            "array target"
        )
    unsupported = sorted(set(arrays) - set(by_array))
    if unsupported:
        return (
            "ARRAY_PARTITION/RESHAPE lacks source-proven concurrent-access evidence "
            "for array(s): " + ", ".join(unsupported)
        )

    pragmas = [
        pragma
        for pragma in action.get("added_pragmas", [])
        if re.search(r"\bARRAY_(?:PARTITION|RESHAPE)\b", pragma, re.IGNORECASE)
    ]
    if len(pragmas) != len(set(arrays)):
        return (
            "source-backed banking requires exactly one storage directive "
            "per proven array target"
        )
    for pragma in pragmas:
        pragma_class = (
            "ARRAY_RESHAPE"
            if re.search(r"\bARRAY_RESHAPE\b", pragma, re.IGNORECASE)
            else "ARRAY_PARTITION"
        )
        variable = re.search(
            r"\bvariable\s*=\s*([A-Za-z_]\w*)", pragma, re.IGNORECASE
        )
        if variable is None or variable.group(1) not in by_array:
            return "storage directive variable is not source-proven"
        item = by_array[variable.group(1)]
        dimension = re.search(r"\bdim\s*=\s*(\d+)", pragma, re.IGNORECASE)
        factor = re.search(r"\bfactor\s*=\s*(\d+)", pragma, re.IGNORECASE)
        kind = re.search(r"\b(cyclic|block|complete)\b", pragma, re.IGNORECASE)
        if dimension is None or int(dimension.group(1)) != item.get("dimension"):
            return (
                f"{pragma_class} for {variable.group(1)} must use proven "
                f"dimension {item.get('dimension')}"
            )
        if kind is None:
            return (
                f"{pragma_class} for {variable.group(1)} must declare "
                "cyclic, block, or complete"
            )
        support = evaluate_source_banking_trial(
            item,
            pragma_class=pragma_class,
            partition_type=kind.group(1),
            factor=int(factor.group(1)) if factor is not None else None,
        )
        if not support.get("supported"):
            return (
                f"{pragma_class} for {variable.group(1)} is not supported "
                f"by its affine bank mapping: {support.get('reason')}"
            )
    return None


def distinct_report_supported_alternatives(
    report: Any,
    measured_action_contract: dict[str, Any] | None,
    rejected_action: dict[str, Any],
    source_banking_evidence: list[dict[str, Any]] | None = None,
) -> list[str]:
    """List actionable report targets outside a rejected action's targets.

    This is deliberately conservative: generic RAG advice and top-level
    interval alone are not alternatives.  A continuation needs a distinct
    loop with measured II/latency evidence or a distinct array named by a
    measured memory-port action contract.
    """
    targets = rejected_action.get("targets", {})
    rejected_loops = {
        str(value)
        for value in (
            targets.get("loops", []) if isinstance(targets, dict) else []
        )
        if str(value)
    }
    rejected_arrays = {
        str(value)
        for value in (
            targets.get("arrays", []) if isinstance(targets, dict) else []
        )
        if str(value)
    }
    rejected_families = {
        str(value)
        for value in rejected_action.get("families", [])
        if str(value)
    }
    alternatives: set[str] = set()

    if (
        "MEMORY_BANKING" not in rejected_families
        and isinstance(measured_action_contract, dict)
    ):
        contract_targets = measured_action_contract.get("targets", [])
        if isinstance(contract_targets, list):
            for target in contract_targets:
                if not isinstance(target, dict):
                    continue
                array = str(target.get("array") or "")
                if array and array not in rejected_arrays:
                    alternatives.add(f"array:{array}:measured_memory_port")

    if "MEMORY_BANKING" not in rejected_families:
        for item in source_banking_evidence or []:
            if not isinstance(item, dict):
                continue
            array = str(item.get("array") or "")
            if not array or array in rejected_arrays:
                continue
            recommended = item.get("recommended_trial", {})
            alternatives.add(
                f"array:{array}:source_affine_parallel_reads:"
                f"dim={item.get('dimension')}:"
                f"type={recommended.get('partition_type')}:"
                f"factor={recommended.get('factor')}"
            )

    for index, loop in enumerate(
        getattr(report, "loop_metrics", None) or []
    ):
        name = str(loop.get("name") or f"loop_{index}")
        if name in rejected_loops:
            continue
        pipeline_ii = loop.get("pipeline_ii")
        if (
            "PIPELINE" not in rejected_families
            and isinstance(pipeline_ii, int)
            and pipeline_ii > 1
        ):
            alternatives.add(f"loop:{name}:PipelineII={pipeline_ii}")
    return sorted(alternatives)


def inferred_directive_delta(
    baseline_report: Any,
    candidate_report: Any,
) -> dict[str, Any]:
    """Summarize changes to Vitis-selected optimization boundaries."""
    def directives(report: Any) -> set[tuple[str, str]]:
        return {
            (str(item.get("kind") or ""), str(item.get("target") or ""))
            for item in (
                getattr(report, "inferred_directives", None) or []
            )
            if isinstance(item, dict) and item.get("kind") and item.get("target")
        }

    before = directives(baseline_report)
    after = directives(candidate_report)
    added = sorted(after - before)
    removed = sorted(before - after)
    before_pipeline = sorted(
        target for kind, target in before if kind == "pipeline"
    )
    after_pipeline = sorted(
        target for kind, target in after if kind == "pipeline"
    )
    return {
        "changed": bool(added or removed),
        "added": [
            {"kind": kind, "target": target} for kind, target in added
        ],
        "removed": [
            {"kind": kind, "target": target} for kind, target in removed
        ],
        "pipeline_targets_before": before_pipeline,
        "pipeline_targets_after": after_pipeline,
        "pipeline_boundary_changed": before_pipeline != after_pipeline,
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
        directive_families = {
            _canonical_optimization_family(match.group(1))
            for pragma in added_pragmas
            for match in [
                re.search(
                    r"#\s*pragma\s+HLS\s+([A-Za-z_]+)",
                    pragma,
                    re.IGNORECASE,
                )
            ]
            if match is not None
        }
        if not added_pragmas or len(directive_families) != 1:
            return "conservative lane requires exactly one directive family"
        if not directive_families <= {
            "LOOP_UNROLL",
            "MEMORY_BANKING",
            "PIPELINE",
        }:
            return (
                "conservative lane requires loop or source-backed banking evidence"
            )
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
