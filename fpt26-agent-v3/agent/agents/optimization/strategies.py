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
    if name in {"DATAFLOW", "INLINE", "STREAM"}:
        return "TASK_PIPELINE"
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
    """Return a parameter-sensitive signature for an optimization action."""
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
            "added_pragmas="
            + ",".join(
                sorted(
                    re.sub(r"\s+", " ", str(value)).strip().lower()
                    for value in action.get("added_pragmas", [])
                    if str(value)
                )
            ),
            "removed_pragmas="
            + ",".join(
                sorted(
                    re.sub(r"\s+", " ", str(value)).strip().lower()
                    for value in action.get("removed_pragmas", [])
                    if str(value)
                )
            ),
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
    if "TASK_PIPELINE" in families and set(families) <= {
        "TASK_PIPELINE",
        "PIPELINE",
        "LATENCY",
    }:
        # DATAFLOW task overlap often needs explicit stage boundaries and
        # stage-local scheduling directives.  Treat that coherent region edit
        # as one architecture family instead of rejecting it as an unrelated
        # multi-pragma mixture.
        families = ["TASK_PIPELINE"]
    source_changed = (
        _without_hls_pragmas_fingerprint(best)
        != _without_hls_pragmas_fingerprint(candidate)
    )
    if source_changed:
        families = sorted({*families, "SOURCE_RESTRUCTURE"})

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
    """Reject only an exact measured action signature."""
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
    effective_families = (
        _effective_contract_families(families, measured_action_contract)
        if isinstance(measured_action_contract, dict)
        else set(families)
    )
    coherent_source_composite = bool(
        effective_families & {"TASK_PIPELINE", "REDUCTION_PARALLELISM"}
    )
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
    contract_target = (
        measured_action_contract.get("target", {})
        if isinstance(measured_action_contract, dict)
        else {}
    )
    diagnosed_loop = (
        str(contract_target.get("loop") or "")
        if isinstance(contract_target, dict)
        else ""
    )
    if (
        diagnosed_loop
        and families & {"LOOP_UNROLL", "PIPELINE"}
        and not coherent_source_composite
        and not target_loops
        and action.get("added_pragmas")
    ):
        return (
            "loop directive could not be mapped to the diagnosed loop; place "
            "the pragma in a source-recognized loop scope before running tools"
        )
    if (
        isinstance(measured_action_contract, dict)
        and measured_action_contract.get("actionable") is True
        and measured_action_contract.get("candidate_families")
    ):
        allowed_families = {
            str(value)
            for value in measured_action_contract.get(
                "candidate_families", []
            )
            if str(value)
        }
        if source_banking_evidence:
            allowed_families.add("MEMORY_BANKING")
        # LOOP_TRIPCOUNT describes the model and is not itself a hardware
        # optimization family. All other source/directive changes must select
        # exactly one family from the diagnosis contract.
        selected_families = effective_families - {"LOOP_TRIPCOUNT"}
        unsupported = sorted(selected_families - allowed_families)
        if unsupported:
            return (
                "candidate uses family outside the diagnosis contract: "
                + ", ".join(unsupported)
            )
        if len(selected_families) > 1:
            return (
                "candidate combines multiple optimization families; select "
                "exactly one diagnosis-supported family"
            )
    loop_metrics = list(getattr(report, "loop_metrics", None) or [])
    all_loops_measured_at_ii_one = bool(loop_metrics) and all(
        loop.get("pipeline_ii") == 1 for loop in loop_metrics
    )
    if "PIPELINE" in families and not coherent_source_composite:
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
    banking_contract = (
        isinstance(measured_action_contract, dict)
        and (
            measured_action_contract.get("kind") == "measured_memory_port_ii"
            or measured_action_contract.get("original_contract_kind")
            == "measured_memory_port_ii"
        )
    )
    if "MEMORY_BANKING" in families and not banking_contract:
        reduction_supported, banking_violation = (
            _source_reduction_banking_violation(
                action,
                measured_action_contract,
            )
        )
        if not reduction_supported:
            banking_violation = _source_banking_action_violation(
                action, source_banking_evidence or []
            )
        if banking_violation is not None:
            return banking_violation
    return None


def _effective_contract_families(
    families: set[str],
    contract: dict[str, Any],
) -> set[str]:
    """Collapse evidence-declared coherent member edits to one family."""

    effective = set(families)
    for item in contract.get("source_architecture_evidence", []):
        if not isinstance(item, dict):
            continue
        composite = str(item.get("composite_family") or "")
        members = {
            str(value)
            for value in item.get("composite_family_members", [])
            if str(value)
        }
        if (
            composite
            and len(effective) > 1
            and effective <= members
            and "SOURCE_RESTRUCTURE" in effective
        ):
            return {composite}
    return effective


def _source_reduction_banking_violation(
    action: dict[str, Any],
    contract: dict[str, Any] | None,
) -> tuple[bool, str | None]:
    """Validate top-array banking against affine reduction evidence."""

    if not isinstance(contract, dict):
        return False, None
    evidence = [
        item
        for item in contract.get("source_architecture_evidence", [])
        if isinstance(item, dict)
        and item.get("kind") == "source_affine_reduction_parallelism"
    ]
    if not evidence:
        return False, None
    allowed_arrays = {
        str(array)
        for item in evidence
        for array in item.get("input_arrays", [])
        if str(array)
    }
    allowed_factor_names = {
        str(factor.get("name") or "")
        for item in evidence
        for factor in item.get("factor_candidates", [])
        if isinstance(factor, dict) and factor.get("name")
    }
    allowed_factor_values = {
        int(factor["value"])
        for item in evidence
        for factor in item.get("factor_candidates", [])
        if isinstance(factor, dict)
        and isinstance(factor.get("value"), int)
    }
    targets = action.get("targets", {})
    arrays = {
        str(value)
        for value in (
            targets.get("arrays", [])
            if isinstance(targets, dict)
            and isinstance(targets.get("arrays", []), list)
            else []
        )
        if str(value)
    }
    if not arrays or not arrays <= allowed_arrays:
        return True, (
            "reduction banking must target only source-proven affine input "
            f"arrays {sorted(allowed_arrays)}"
        )
    pragmas = [
        pragma
        for pragma in action.get("added_pragmas", [])
        if re.search(r"\bARRAY_(?:PARTITION|RESHAPE)\b", pragma, re.IGNORECASE)
    ]
    if len(pragmas) != len(arrays):
        return True, (
            "reduction banking requires exactly one storage directive per "
            "selected input array"
        )
    for pragma in pragmas:
        variable = re.search(
            r"\bvariable\s*=\s*([A-Za-z_]\w*)",
            pragma,
            re.IGNORECASE,
        )
        factor = re.search(
            r"\bfactor\s*=\s*([A-Za-z_]\w*|\d+)",
            pragma,
            re.IGNORECASE,
        )
        kind = re.search(r"\b(cyclic|block|complete)\b", pragma, re.IGNORECASE)
        if variable is None or variable.group(1) not in allowed_arrays:
            return True, "reduction storage directive variable is not source-proven"
        if kind is None or kind.group(1).lower() != "cyclic":
            return True, (
                "affine lane reduction banking requires explicit cyclic mapping"
            )
        if factor is None:
            return True, "reduction banking requires an evidence-listed factor"
        token = factor.group(1)
        if token.isdigit():
            supported_factor = int(token) in allowed_factor_values
        else:
            supported_factor = token in allowed_factor_names
        if not supported_factor:
            return True, (
                "reduction banking factor is outside the finite "
                f"source-evidence set names={sorted(allowed_factor_names)} "
                f"values={sorted(allowed_factor_values)}"
            )
    return True, None


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
    source_architecture_evidence: list[dict[str, Any]] | None = None,
) -> list[str]:
    """List report/source-supported hypothesis spaces after one rejection.

    This is deliberately evidence-restricted: generic RAG advice and top-level
    interval alone is not an alternative. A continuation needs a measured
    loop/array target and a parameter-sensitive action different from the
    rejected signature.
    """
    alternatives: set[str] = set()

    if isinstance(measured_action_contract, dict):
        if (
            measured_action_contract.get("kind")
            == "diagnosis_guided_optimization"
            and measured_action_contract.get("actionable") is True
        ):
            target = measured_action_contract.get("target", {})
            loop = (
                str(target.get("loop") or "")
                if isinstance(target, dict)
                else ""
            )
            for family in measured_action_contract.get(
                "candidate_families", []
            ):
                if loop and str(family):
                    alternatives.add(
                        f"loop:{loop}:{family}:new_evidence_backed_signature"
                    )
        contract_targets = measured_action_contract.get("targets", [])
        if isinstance(contract_targets, list):
            for target in contract_targets:
                if not isinstance(target, dict):
                    continue
                array = str(target.get("array") or "")
                if array:
                    alternatives.add(
                        f"array:{array}:measured_memory_port_parameter_space"
                    )

    for item in source_banking_evidence or []:
        if not isinstance(item, dict):
            continue
        array = str(item.get("array") or "")
        if not array:
            continue
        option_space = item.get("banking_option_space", {})
        alternatives.add(
            f"array:{array}:source_affine_parallel_reads:"
            f"dim={item.get('dimension')}:"
            f"types={option_space.get('partition_types')}:"
            f"factor_range={option_space.get('factor_min')}.."
            f"{option_space.get('factor_max')}"
        )

    for item in source_architecture_evidence or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        top = str(item.get("top_function") or "")
        families = ",".join(
            sorted(str(value) for value in item.get("candidate_families", []))
        )
        if kind and top and families:
            alternatives.add(
                f"function:{top}:{kind}:families={families}"
            )

    for index, loop in enumerate(
        getattr(report, "loop_metrics", None) or []
    ):
        name = str(loop.get("name") or f"loop_{index}")
        pipeline_ii = loop.get("pipeline_ii")
        if (
            isinstance(pipeline_ii, int)
            and pipeline_ii > 1
        ):
            alternatives.add(
                f"loop:{name}:PipelineII={pipeline_ii}:parameter_space"
            )
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

    if name == "evidence_backed_directive":
        if source_changed:
            return "directive lane must preserve non-pragma source"
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
            return "directive lane requires exactly one directive family"
        if not directive_families <= {
            "LOOP_UNROLL",
            "MEMORY_BANKING",
            "PIPELINE",
        }:
            return (
                "directive lane requires loop or source-backed banking evidence"
            )
        return None

    if name == "task_pipeline_architecture":
        if source_changed:
            return "task-pipeline lane must preserve non-pragma source"
        directive_names = {
            match.group(1).upper()
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
        if "DATAFLOW" not in directive_names:
            return "task-pipeline lane requires one DATAFLOW region"
        unsupported = directive_names - {
            "DATAFLOW",
            "INLINE",
            "PIPELINE",
            "LATENCY",
            "STREAM",
        }
        if unsupported:
            return (
                "task-pipeline lane contains unrelated directive families: "
                + ", ".join(sorted(unsupported))
            )
        return None

    if name == "source_parallel_architecture":
        if not source_changed:
            return "source-parallel lane must change the non-pragma architecture"
        directive_names = {
            match.group(1).upper()
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
        unsupported = directive_names - {
            "ARRAY_PARTITION",
            "ARRAY_RESHAPE",
            "PIPELINE",
            "UNROLL",
            "LATENCY",
        }
        if unsupported:
            return (
                "source-parallel lane contains unsupported directive families: "
                + ", ".join(sorted(unsupported))
            )
        return None

    if name == "independent_alternative":
        if not source_changed and not added_pragmas:
            return "alternative lane requires a material source or directive change"
        return None

    return f"unknown strategy contract: {name}"
