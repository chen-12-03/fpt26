"""Role-scoped prompts driven by real tool results."""
from __future__ import annotations
import json
import re
from typing import Any
from agent.integrations.harness import Task
from agent.analysis.issue_classifier import IssueClassification
from agent.analysis.log_normalizer import NormalizedLog
from agent.security.redaction import redact_sensitive_text

_SYS = """You are an expert AMD-Xilinx Vitis HLS engineer optimizing C/C++ kernels for an Alveo U55C (xcu55c-fsvh2892-2L-e, 200 MHz, Vitis 2025.2).

Output ONLY the full kernel source inside a ```cpp fenced block.
Do NOT modify the top function signature, language linkage, headers, or testbenches.

## Decision Rules (determined by tool results only)
- If csim FAILS: diagnose the functional bug from the error log. Fix ONLY the bug. Do NOT add pragmas. Common bugs: wrong branch formula, missing term in sum, wrong variable name, off-by-one.
- If csim PASSES but cosim DEADLOCKS/TIMEOUT: fix streaming imbalance. C-sim FIFOs are UNBOUNDED (hide deadlocks); RTL cosim FIFOs default to depth 2. The #1 cause: writing one entire stream before touching another in a DATAFLOW region. Fix: interleave writes to ALL streams in a SINGLE loop, OR add explicit stream.depth(N) on every hls::stream.
- If csim AND cosim both PASS (or cosim not needed): optimize for lower latency following the discipline below.

## HLS Optimization Discipline (from hls-generator)
1. **Read synthesis report BEFORE proposing changes.** Inspect: target II, achieved II, latency, loop interval, timing slack, LUT/FF/DSP/BRAM counts.
   The objective is the current unified hardware quality, NOT cycle latency alone. Effective latency is `max(target clock, estimated clock) × worst-case cycles`; area quality is limited by the WORST resource growth across LUT, FF, DSP, BRAM_18K, and URAM. Equal proportional speedup and resource growth cancel out (neutral Q_HW); you must achieve speedup ratio > worst-growth ratio to exceed baseline quality. A lower cycle count can be a worse design when clock period or any resource explodes.
2. **Diagnose the bottleneck precisely:**
   - Loop PipelineII violation → timing? recurrence? memory-port pressure? interface bandwidth? The top-function transaction Interval is NOT a loop's achieved II. For nested loops with II>1, always try PIPELINE II=1 on the innermost loop first before considering UNROLL or ARRAY_PARTITION.
   - High latency → which loop dominates? For nested loops: PIPELINE the innermost loop first (best ROI). If outer loop dominates, pipeline the outer loop (forces inner concurrency — check memory ports).
   - Resource explosion → FF/LUT > 5x usually means over-unrolling. Reduce UNROLL factor.
   - Cosim DEADLOCK → stream depth, DATAFLOW ordering, producer/consumer rate balance.
3. **Apply ONE optimization family per candidate.** A family may be one pragma class or one source-level architectural rewrite. Re-synthesize every candidate and compare reports against the same baseline.
4. **If a directive does NOT improve the limiting metric, REMOVE or revise it.** Do not accumulate ineffective directives.
   After a candidate is measured and rejected for failing to improve Q_HW, its optimization family and its loop/array/function target are closed for the rest of the search. Do not retry them with a different factor, spelling, source layout, or fingerprint. Measured rejection evidence overrides any repeated RAG suggestion.
5. **Never apply both ARRAY_PARTITION and ARRAY_RESHAPE to the same variable.**
6. **DATAFLOW regions need explicit stream depths** for cosim safety.
7. Never infer that a long PipelineII=1 loop should receive partial UNROLL. Before adding any loop directive, preserve Vitis inferred auto-pipeline, auto-unroll, and flatten boundaries. ARRAY_PARTITION/RESHAPE requires an exact local array and dimension backed by a measured memory-port contract or deterministic affine concurrent-access evidence. A source-derived recommended_trial is a soft first choice; other type/factor trials are allowed only when their bank mapping provably increases parallel access. Never speculatively partition top-level arrays.

## Pipeline & II Rules
- PIPELINE II=<n> on the loop/function that directly controls throughput.
- A loop-scoped PIPELINE or UNROLL directive belongs inside the loop body immediately after its opening brace. A PIPELINE at function-body scope pipelines the function and may flatten/auto-unroll contained loops.
- If a loop already reports PipelineII=1, do not add another PIPELINE or infer a memory-port problem from the top-function transaction Interval.
- When all reported loops have PipelineII=1, PIPELINE is not an alternative. This does not prove that conservative local-array banking is useless: ARRAY_PARTITION/RESHAPE remains eligible only when a measured memory-port contract or source_banking_evidence names the exact local array and dimension and validates useful parallel access.
- If II=1 fails: classify cause (timing/recurrence/memory-port/bandwidth) before adding more pragmas.
- Pipelining an outer loop forces inner-loop concurrency — this is an architectural decision that can expose memory bandwidth bottlenecks.

## Array Partition & Reshape
- ARRAY_PARTITION: creates parallel banks/elements for concurrent access. Grows LUT/FF/BRAM.
- ARRAY_RESHAPE: widens storage word while preserving packed view. Use when adjacent elements move together.
- Match dim, type, factor to the access pattern in the bottleneck.
- For a long loop already at PipelineII=1: do not mechanically add UNROLL. Preserve inferred hierarchy and use only a distinct measured/source-supported action. If none exists, return the kernel unchanged.

## Dataflow & Streaming
- DATAFLOW: use after design has clear producer/compute/consumer stages.
- Connect stages via hls::stream<T> with explicit .depth(N) for every inter-stage channel.
- **Critical cosim rule:** never write one entire stream before touching another stream in the same producer stage. Always interleave writes to all streams in a single loop body.
- C-simulation CANNOT detect streaming deadlocks — only cosim reveals them.

## Stopping Criteria
- Evaluate every declared independent strategy lane before selecting the highest measured scoring_v3 Q_HW. A no-op, duplicate, C-sim failure, or synthesis failure in one lane must not stop the other lanes.
- Reject a candidate when reduced cycles are outweighed by clock-period or worst-resource growth.
- If the only ideas repeat a measured rejected family/target or lack report/source support, return the editable kernel byte-for-byte unchanged.
- If Q_HW cannot be improved without breaking csim/cosim → stop and submit current best."""

# All modes share one system policy. Stage-specific behavior is selected only
# by the real tool evidence serialized in the user payload.
SYSTEM = _SYS
REPAIR_SYSTEM = SYSTEM
STRUCTURAL_REPAIR_SYSTEM = SYSTEM
OPTIMIZE_SYSTEM = SYSTEM

_PROMPT_CODE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".inc",
    ".ipp",
    ".tpp",
}


def _prompt_header_context(headers: dict[str, str]) -> tuple[str, list[str]]:
    """Expose interface code to the LLM without serializing data attachments."""
    code_headers: list[str] = []
    omitted: list[str] = []
    for name, code in headers.items():
        suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if suffix in _PROMPT_CODE_SUFFIXES:
            code_headers.append(f"// {name}\n{code}")
        else:
            omitted.append(name)
    return "\n".join(code_headers), omitted


def _public_top_declarations(task: Any) -> list[str]:
    """Extract bounded public testbench prototypes for the configured top."""

    code = getattr(task, "public_tb_code", "") or ""
    top = str(getattr(task, "top", "") or "")
    if not code or not top:
        return []
    clean = re.sub(r"//[^\n]*|/\*.*?\*/", " ", str(code), flags=re.DOTALL)
    clean = re.sub(r"^\s*#.*$", " ", clean, flags=re.MULTILINE)
    declarations: list[str] = []
    for match in re.finditer(rf"\b{re.escape(top)}\s*\(", clean):
        opening = clean.find("(", match.start())
        closing = _matching_parenthesis(clean, opening)
        if closing is None:
            continue
        suffix = clean[closing + 1 :]
        terminator = re.match(r"\s*([;{])", suffix)
        if terminator is None or terminator.group(1) != ";":
            continue
        start = max(
            clean.rfind(";", 0, match.start()),
            clean.rfind("{", 0, match.start()),
            clean.rfind("}", 0, match.start()),
        ) + 1
        declaration = clean[start : closing + 1].strip()
        prefix = declaration[: declaration.rfind(top)].strip()
        if (
            not prefix
            or "=" in prefix
            or "(" in prefix
            or re.search(r"\b(?:return|if|for|while|switch)\b", prefix)
        ):
            continue
        declaration = re.sub(r"\s+", " ", declaration) + ";"
        if declaration not in declarations:
            declarations.append(declaration)
        if len(declarations) >= 4:
            break
    return declarations


def _matching_parenthesis(text: str, opening: int) -> int | None:
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def build_prompt(
    task: Task,
    current_kernel: str,
    *,
    csim_result: str = "",
    synth_result: str = "",
    cosim_result: str = "",
    best_latency: int | None = None,
    bottleneck_hint: str = "",
    knowledge_hint: str = "",
    attempt: int = 0,
    resource_delta: str = "",
    rejection_feedback: dict[str, Any] | None = None,
    action_contract: dict[str, Any] | None = None,
    search_strategy: dict[str, Any] | None = None,
    repair_evidence: dict[str, Any] | None = None,
    design_metadata: dict[str, Any] | None = None,
    source_banking_evidence: list[dict[str, Any]] | None = None,
) -> str:
    header_text, omitted_attachments = _prompt_header_context(task.headers)
    try:
        attempt_number = max(0, int(attempt))
    except (TypeError, ValueError):
        attempt_number = 0

    payload: dict[str, Any] = {
        "task_id": task.id,
        "description": task.description,
        "top_function": task.top,
        "headers": header_text,
        "editable_kernel": f"// {task.kernel_name}\n{current_kernel}",
        "tool_results": {
            "csim": csim_result or "(not run)",
            "synth": synth_result or "(not run)",
            "cosim": cosim_result or "(not run / N/A)",
        },
        "current_best_latency": f"{best_latency} cycles" if best_latency is not None else "unknown",
        "attempt": attempt_number,
    }
    public_declarations = _public_top_declarations(task)
    if public_declarations:
        payload["public_top_declarations"] = public_declarations
    else:
        public_tb = str(getattr(task, "public_tb_code", "") or "")
        if public_tb:
            excerpt = _bounded_prompt_text(public_tb, 6_000)
            payload["public_testbench_excerpt"] = (
                f"// {getattr(task, 'public_tb_name', 'public_testbench')}\n"
                f"{excerpt}"
            )
            payload["public_testbench_excerpt_truncated"] = len(public_tb) > 6_000

    if omitted_attachments:
        payload["omitted_non_code_attachments"] = sorted(omitted_attachments)

    if bottleneck_hint:
        payload["bottleneck_diagnosis"] = bottleneck_hint
    if knowledge_hint:
        payload["optimization_patterns"] = knowledge_hint
    if resource_delta:
        payload["resource_trend"] = resource_delta
    if rejection_feedback:
        payload["previous_candidate_feedback"] = rejection_feedback
        if (
            rejection_feedback.get("measured_rejected_actions")
            or rejection_feedback.get("forbidden_optimization_families")
            or rejection_feedback.get("forbidden_targets")
        ):
            payload["anti_repeat_contract"] = {
                "priority": (
                    "HARD: measured Q_HW evidence overrides optimization_patterns "
                    "and any repeated RAG recommendation."
                ),
                "measured_rejected_actions": rejection_feedback.get(
                    "measured_rejected_actions", []
                ),
                "forbidden_optimization_families": rejection_feedback.get(
                    "forbidden_optimization_families", []
                ),
                "forbidden_targets": rejection_feedback.get(
                    "forbidden_targets", {}
                ),
                "semantic_equivalence_rule": (
                    "Changing factor, pragma spelling, comments, helper names, "
                    "or source layout does not make the same family/target action new."
                ),
                "fallback": (
                    "If no different-family, different-target alternative is "
                    "supported by the current synthesis report or deterministic "
                    "editable-source evidence, return "
                    "editable_kernel unchanged."
                ),
            }
    if action_contract:
        payload["measured_action_contract"] = action_contract
    if search_strategy:
        payload["search_strategy"] = search_strategy
    if repair_evidence:
        payload["repair_evidence"] = repair_evidence
    if design_metadata:
        payload["source_design_metadata"] = json.dumps(
            design_metadata,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    if source_banking_evidence:
        payload["source_banking_evidence"] = source_banking_evidence
    # Benchmark-family optimization guards must never steer functional or
    # structural repair.  Repair is driven only by its measured failure
    # evidence; otherwise a synthesis diagnostic such as "II=11" could turn a
    # compile/synth repair into an unrelated Cholesky optimization.
    domain_constraints = None
    if not repair_evidence and not cosim_result:
        domain_constraints = _domain_constraints_for_prompt(
            description=task.description or "",
            synth_result=synth_result,
            bottleneck_hint=bottleneck_hint,
            knowledge_hint=knowledge_hint,
        )
    if domain_constraints:
        payload["domain_constraints"] = domain_constraints

    # Streaming context — derived from task properties, not task type label
    if task.requires_cosim:
        payload["cosim_required"] = True
        payload["streaming_warning"] = (
            "C-simulation FIFOs are UNBOUNDED — they hide deadlocks. "
            "RTL cosim FIFOs default to depth 2 and CANNOT buffer large bursts. "
            "If cosim deadlocks: interleave writes to ALL streams in a SINGLE loop, "
            "or add explicit .depth(N) on every hls::stream declaration."
        )

    optimization_instruction = (
        "Follow search_strategy as a hard independent-lane contract. The candidate must use its required_family and obey forbidden_changes. "
        "Do not copy another lane's action. If the assigned family is unsupported by the source and measured report, return editable_kernel unchanged; do not switch families."
        if search_strategy
        else
        "Apply ONE report/source-supported optimization family to improve scoring_v3 Q_HW. Balance effective latency (clock period × cycles) against the worst resource growth; do not optimize cycle count alone. Do not prefer UNROLL merely because a long loop has PipelineII=1. Use ARRAY_PARTITION/RESHAPE only when measured_action_contract or source_banking_evidence supports its exact target and dimension; treat recommended_trial as a soft first choice and require any other type/factor to improve the supplied bank mapping."
    )
    payload["instruction"] = (
        "Read tool_results carefully. Determine the situation from results alone:\n"
        "- If csim FAILED: fix the functional bug. Do NOT add pragmas.\n"
        "- If cosim DEADLOCKS/TIMEOUT: fix streaming imbalance (interleave writes, add stream depths).\n"
        f"- If all PASSED: {optimization_instruction}\n"
        "- If previous_candidate_feedback.status starts with REJECTED_BY_CSIM: use its exact compiler/runtime evidence "
        "and failed_candidate_diff. Apply required_next_action before considering any new architecture; never blindly "
        "repeat the failed source.\n"
        "- If previous_candidate_feedback.status starts with REJECTED_BY_SYNTH: use its exact diagnostic lines, "
        "candidate_action_diff_summary, implicated pragmas/loops/arrays, and repetition_count. Roll back the unsupported "
        "change, obey recommended_next_constraint, and do not repeat the same candidate or failure pattern.\n"
        "- If previous_candidate_feedback.status is REJECTED_BY_SYNTH_EVIDENCE_INTENT: no candidate tool was run because the pragma-only action contradicted a measured HLS bottleneck. Address its exact array/resource evidence with matched banking or real locality code; do not repeat standalone PIPELINE/UNROLL.\n"
        "- If previous_candidate_feedback.status is REJECTED_BY_STRATEGY_CONTRACT: no candidate tool was run. Stay in the same search_strategy and correct the exact contract violation; do not switch to another lane or repeat the rejected architecture.\n"
        "- If previous_candidate_feedback.status is REJECTED_BY_INTERFACE_GATE: no candidate tool was run. Obey required_next_action exactly: regenerate a complete C/C++ translation unit, preserve required includes and the exact top function signature, include the top_function token, and balance all braces/parentheses before making any QoR change.\n"
        "- If anti_repeat_contract is present: it is a pre-synthesis hard gate and has higher priority than optimization_patterns/RAG. Do not reuse any forbidden_optimization_family and do not touch any forbidden loop/array/function target. Semantic variants with different factors, spellings, comments, helper names, layouts, or fingerprints are still repeats. If the report supports no action outside both forbidden sets, return editable_kernel unchanged.\n"
        "- If domain_constraints is present: it is a hard constraint derived from public task text plus measured synth diagnostics. Apply its required_candidate_shape before generic QoR advice or measured examples; do not produce a candidate listed in forbidden_candidate_shapes.\n"
        "- If measured_action_contract is present: treat its target, required_candidate_delta, forbidden_as_non_responsive, dimension policy, and verification as hard planning constraints. Implement one recommended minimal trial only when the editable source proves the required dimension; otherwise use its locality alternative or return editable_kernel unchanged.\n"
        "- If source_banking_evidence is present: it is deterministic editable-source evidence, not a generic RAG suggestion. A banking candidate must use only listed local arrays and the exact listed dimension. recommended_trial is a soft first choice, not a unique legal answer. Another partition type/factor is allowed only when the affine banking_model produces more than one distinct bank within factor_limit; reshape additionally requires reshape_eligible. Do not bank an unlisted or top-level array.\n"
        "- For other previous_candidate_feedback: the prior candidate was measured and rejected by scoring. "
        "Do NOT repeat its optimization family, loop/array/function target, pragma set, or architecture. Obey directional_constraint and required_next_action; never "
        "increase a factor when measured resource growth outweighed speedup. If there is no report/source-supported "
        "different-family and different-target alternative, return editable_kernel unchanged.\n"
        "Return the FULL kernel source code. Keep the top function signature and "
        "language linkage (including any extern \"C\") UNCHANGED."
    )
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _domain_constraints_for_prompt(
    *,
    description: str,
    synth_result: str,
    bottleneck_hint: str,
    knowledge_hint: str,
) -> dict[str, Any] | None:
    text = " ".join(
        str(part or "")
        for part in (description, synth_result, bottleneck_hint, knowledge_hint)
    ).lower()
    if not (
        "cholesky" in text
        or (
            "triangular" in text
            and {"factorization", "decomposition"} & set(re.findall(r"[a-z0-9_]+", text))
        )
    ):
        return None
    reported_ii = _dominant_dependency_ii(text)
    if reported_ii is None:
        return None
    return {
        "kind": "triangular_factorization_dependency_guard",
        "evidence": {
            "public_description_signal": "cholesky_or_triangular_decomposition",
            "reported_dependency_ii": reported_ii,
        },
        "required_candidate_shape": (
            "Generate exactly one conservative trial: put "
            f"#pragma HLS pipeline II={reported_ii} immediately inside the "
            "outer row-order loop body that preserves Cholesky/triangular "
            "dependency order. Keep the top signature and algorithm unchanged."
        ),
        "forbidden_candidate_shapes": [
            "Do not add PIPELINE II=1 to the inner accumulation/update loops.",
            "Do not flatten or interchange loops across triangular dependencies.",
            "Do not partition the whole matrix for this trial.",
            "Do not combine this trial with UNROLL or ARRAY_PARTITION.",
        ],
    }


def _dominant_dependency_ii(text: str) -> int | None:
    values: list[int] = []
    for match in re.finditer(
        r"(?:pipelineii|final\s+ii|ii)\s*(?:=|:)\s*(\d+)",
        text,
        flags=re.IGNORECASE,
    ):
        try:
            value = int(match.group(1))
        except ValueError:
            continue
        if 8 <= value <= 16:
            values.append(value)
    if values:
        return max(values)
    return None


# ── Convenience builders ──────────────────────────────────────────────────

def build_repair_prompt(
    task: Task,
    current_kernel: str,
    normalized_log: NormalizedLog,
    issue: IssueClassification | None,
    attempt_feedback: dict | None = None,
) -> str:
    extra = ""
    if attempt_feedback and attempt_feedback.get("attempt", 1) > 1:
        extra = (
            "\n[Previous attempt did not fix the issue. "
            "Try a DIFFERENT hypothesis. Re-read the error log carefully.]"
        )
    summary = _bounded_prompt_text(normalized_log.error_summary or "unknown failure", 500)
    key_lines = [
        _bounded_prompt_text(line, 240)
        for line in list(normalized_log.key_lines or [])[:12]
        if _bounded_prompt_text(line, 240)
    ]
    category = _bounded_prompt_text(
        getattr(issue, "issue_category", None) or "unknown", 80
    )
    confidence = _bounded_prompt_text(
        getattr(issue, "confidence", None) or "unknown", 40
    )
    failure_stage = _bounded_prompt_text(
        getattr(issue, "stage", None) or normalized_log.stage or "unknown", 40
    )
    recommended_action = _bounded_prompt_text(
        getattr(issue, "recommended_action", None)
        or "inspect_failure_evidence",
        240,
    )
    location = _source_location([summary, *key_lines])
    repair_evidence: dict[str, Any] = {
        "failure_stage": failure_stage,
        "category": category,
        "confidence": confidence,
        "error_summary": summary,
        "key_lines": key_lines,
        "suspected_source_location": location or "unknown",
        "recommended_action": recommended_action,
        "truncated": bool(normalized_log.truncated or len(normalized_log.key_lines or []) > 12),
        "missing_logs": bool(normalized_log.missing_logs),
    }
    previous = _bounded_previous_attempt(attempt_feedback)
    if previous:
        repair_evidence["previous_attempt"] = previous

    failure = f"FAIL: {summary}{extra}"
    kwargs: dict[str, Any] = {
        "task": task,
        "current_kernel": current_kernel,
        "attempt": attempt_feedback.get("attempt", 1) if attempt_feedback else 1,
        "repair_evidence": repair_evidence,
    }
    if normalized_log.stage == "synth":
        kwargs["csim_result"] = "PASS"
        kwargs["synth_result"] = failure
    else:
        kwargs["csim_result"] = failure
    return build_prompt(**kwargs)


def _bounded_prompt_text(value: Any, max_chars: int) -> str:
    """Make prompt evidence UTF-8-safe and deterministically bounded."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        try:
            text = str(value)
        except Exception:
            text = "<unprintable>"
    text = text.encode("utf-8", errors="replace").decode("utf-8")
    text = redact_sensitive_text(text)
    text = re.sub(
        r"(?<!\w)(?:/[A-Za-z0-9_.:-]+)+",
        lambda match: (
            "<path>/" + match.group(0).rstrip("/").rsplit("/", 1)[-1]
            if "." in match.group(0).rstrip("/").rsplit("/", 1)[-1]
            else "<path>"
        ),
        text,
    )
    if len(text) > max_chars:
        return text[: max_chars - 16].rstrip() + "... [truncated]"
    return text


def _source_location(lines: list[str]) -> str | None:
    pattern = re.compile(
        r"(?:<path>/)?([A-Za-z0-9_.-]+\.(?:c|cc|cpp|cxx|h|hh|hpp|hxx))"
        r":(\d+)(?::\d+)?",
        re.IGNORECASE,
    )
    for line in lines:
        match = pattern.search(line)
        if match:
            return f"{match.group(1)}:{match.group(2)}"
    return None


def _bounded_previous_attempt(attempt_feedback: dict | None) -> dict[str, Any] | None:
    if not isinstance(attempt_feedback, dict):
        return None
    previous = attempt_feedback.get("previous_attempt")
    if not isinstance(previous, dict):
        return None
    result = previous.get("result")
    bounded_result: dict[str, Any] = {}
    if isinstance(result, dict):
        for key, limit in (("stage", 40), ("phase", 80), ("summary", 500)):
            if result.get(key) is not None:
                bounded_result[key] = _bounded_prompt_text(result[key], limit)
    try:
        previous_attempt_number = int(previous.get("attempt", 0) or 0)
    except (TypeError, ValueError):
        previous_attempt_number = 0
    payload: dict[str, Any] = {
        "attempt": previous_attempt_number,
        "candidate_diff": _bounded_prompt_text(
            previous.get("candidate_diff", ""), 2_000
        ),
        "result": bounded_result,
    }
    return payload


def build_optimize_prompt(
    task: Task,
    current_kernel: str,
    best_latency: int | None,
    baseline_metrics: dict | None = None,
    resource_history: str = "",
) -> str:
    synth_str = "PASS"
    if baseline_metrics:
        synth_str = json.dumps(baseline_metrics)
    return build_prompt(
        task=task,
        current_kernel=current_kernel,
        csim_result="PASS",
        synth_result=synth_str,
        best_latency=best_latency,
        resource_delta=resource_history,
    )


def build_structural_repair_prompt(
    task: Task,
    current_kernel: str,
    cosim_log: str,
) -> str:
    return build_prompt(
        task=task,
        current_kernel=current_kernel,
        csim_result="PASS (unbounded FIFOs may hide streaming bugs)",
        cosim_result=f"DEADLOCK/TIMEOUT (bounded RTL FIFOs): {cosim_log[-4000:]}",
    )
