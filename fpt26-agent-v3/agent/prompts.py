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
   The objective is the current unified hardware quality, NOT cycle latency alone. Effective latency is `max(target clock, estimated clock) × worst-case cycles`. Resource pressure is `U=Σ(resource_count/device_capacity)` across LUT, FF, DSP, BRAM_18K, and URAM, and area ratio is `U_baseline/U_candidate`. A lower cycle count can be a worse design when clock period or total capacity-normalized resource pressure explodes.
2. **Diagnose the bottleneck precisely:**
   - Prefer the supplied structured bottleneck diagnosis and its exact evidence. If confidence is unknown, inspect source/report context and keep the root cause unknown until a tool result distinguishes timing, recurrence, memory-port pressure, interface bandwidth, or structure.
   - High latency is a symptom, not a cause. Use named loop/message evidence; do not infer a directive from an absolute latency threshold or resource ratio.
   - You may revise the technical route after each measured result. Explain the change through one evidence-matched candidate, then let CSim/Synth/required CoSim and Q_HW decide.
   - Cosim DEADLOCK → stream depth, DATAFLOW ordering, producer/consumer rate balance.
3. **Apply ONE optimization family per candidate.** A family may be one pragma class or one source-level architectural rewrite. Re-synthesize every candidate and compare reports against the same baseline.
4. **If a candidate does NOT improve the objective, roll it back.** Do not accumulate ineffective directives. Reject only the measured action signature; a different parameterization or architecture is a new hypothesis and requires fresh report/source justification and measurement.
5. **Never apply both ARRAY_PARTITION and ARRAY_RESHAPE to the same variable.**
6. **DATAFLOW regions need explicit stream depths** for cosim safety.
7. Never infer a directive from loop length or PipelineII=1 alone. Before adding any loop directive, preserve Vitis inferred auto-pipeline, auto-unroll, and flatten boundaries. ARRAY_PARTITION/RESHAPE requires an exact local array and dimension backed by a measured memory-port contract or deterministic affine concurrent-access evidence. Select type and factor from the reported access/bank model; there is no default factor. Never speculatively partition top-level arrays.

## Pipeline & II Rules
- PIPELINE II=<n> on the loop/function that directly controls throughput.
- A loop-scoped PIPELINE or UNROLL directive belongs inside the loop body immediately after its opening brace. A PIPELINE at function-body scope pipelines the function and may flatten/auto-unroll contained loops.
- If a loop already reports PipelineII=1, do not add another PIPELINE or infer a memory-port problem from the top-function transaction Interval.
- When all reported loops have PipelineII=1, PIPELINE is not an alternative. ARRAY_PARTITION/RESHAPE remains eligible only when a measured memory-port contract or source_banking_evidence names the exact local array and dimension and validates useful parallel access.
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
- Reject a candidate when reduced cycles are outweighed by clock-period or aggregate capacity-normalized resource growth.
- If the only ideas repeat an exact measured rejected action or lack report/source support, return the editable kernel byte-for-byte unchanged.
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
    bottleneck_hint: Any = "",
    knowledge_hint: str = "",
    attempt: int = 0,
    resource_delta: str = "",
    rejection_feedback: dict[str, Any] | None = None,
    action_contract: dict[str, Any] | None = None,
    search_strategy: dict[str, Any] | None = None,
    repair_evidence: dict[str, Any] | None = None,
    design_metadata: dict[str, Any] | None = None,
    source_banking_evidence: list[dict[str, Any]] | None = None,
    source_architecture_evidence: list[dict[str, Any]] | None = None,
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
            or rejection_feedback.get("rejected_action_signatures")
        ):
            payload["anti_repeat_contract"] = {
                "priority": (
                    "HARD: measured Q_HW evidence overrides optimization_patterns "
                    "and any repeated RAG recommendation."
                ),
                "measured_rejected_actions": rejection_feedback.get(
                    "measured_rejected_actions", []
                ),
                "rejected_action_signatures": rejection_feedback.get(
                    "rejected_action_signatures", []
                ),
                "semantic_equivalence_rule": (
                    "Whitespace, comments, and equivalent spelling do not create "
                    "a new action. A changed factor, target, or architecture is a "
                    "new action only when report/source evidence motivates it."
                ),
                "fallback": (
                    "If no new evidence-supported hypothesis exists, return the "
                    "editable kernel unchanged."
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
    if source_architecture_evidence:
        payload["source_architecture_evidence"] = (
            source_architecture_evidence[:4]
        )
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
        "Use the structured diagnosis as evidence, not as a fixed recipe: inspect the editable source, choose ONE allowed evidence-matched family, and revise the route after measured feedback. If the diagnosis is unknown or a precondition is unproven, keep the cause unknown and return the kernel unchanged. Improve scoring_v3 Q_HW by balancing effective latency (clock period × cycles) against total capacity-normalized resource pressure. Do not prefer UNROLL merely because a loop has PipelineII=1 unless the diagnosis also proves that loop dominates measured latency and the source proves independence/reduction legality. For a LOOP_UNROLL or PIPELINE trial, preserve non-pragma source and place exactly one selected directive as the first statement inside the diagnosed loop body. TASK_PIPELINE is one coherent family and is permitted only with source_architecture_evidence; it may use DATAFLOW plus the minimum stage-boundary and stage-local scheduling directives needed to realize those exact connected stages. For a SOURCE_RESTRUCTURE trial, add no optimization pragma. Use ARRAY_PARTITION/RESHAPE only when measured_action_contract or source_banking_evidence supports its exact target and dimension."
    )

    # Build a prioritised situation summary so the LLM can quickly orient
    # before reading the detailed rules.
    situation_parts: list[str] = []
    if rejection_feedback:
        fb_status = str(rejection_feedback.get("status", ""))
        if fb_status == "REJECTED_BY_SYNTH_EVIDENCE_INTENT":
            situation_parts.append("PRIORITY: No candidate tool was run. The last pragma-only action contradicted a measured HLS bottleneck. Address the named array with matched banking or real code-locality before any other directive.")
        elif fb_status == "REJECTED_BY_STRATEGY_CONTRACT":
            situation_parts.append("PRIORITY: Stay in the assigned strategy lane. Correct only the specific contract violation listed in previous_candidate_feedback.")
        elif fb_status == "REJECTED_BY_INTERFACE_GATE":
            situation_parts.append("PRIORITY: Regenerate a complete, balanced C/C++ translation unit with the correct top function before any QoR change.")
        elif fb_status.startswith("REJECTED_BY_CSIM"):
            situation_parts.append("PRIORITY: Fix the CSim compile/runtime error using the exact evidence in previous_candidate_feedback before any new architecture.")
        elif fb_status.startswith("REJECTED_BY_SYNTH"):
            situation_parts.append("PRIORITY: Roll back the exact failed synthesis candidate. Use its diagnostic lines to choose a different legal construct; do not repeat the unsupported change.")
        elif fb_status == "REJECTED_BY_SCORING_V3_Q_HW":
            situation_parts.append("PRIORITY: The last measured candidate did not improve Q_HW. Do not repeat its exact action signature. A different factor/target/architecture is a new hypothesis only with fresh evidence support.")
        elif fb_status.startswith("REJECTED_BY_"):
            situation_parts.append("PRIORITY: The prior candidate was rejected. Address the specific feedback reason before exploring new architectures.")
    if action_contract and isinstance(action_contract, dict):
        if action_contract.get("actionable") is True:
            families = action_contract.get("candidate_families", [])
            target = action_contract.get("target", {})
            target_desc = (
                target.get("loop") or target.get("array") or ""
            ) if isinstance(target, dict) else ""
            if families and target_desc:
                situation_parts.append(
                    f"CONTRACT: Diagnosis supports {sorted(set(families))} "
                    f"on target '{target_desc}'. Select exactly one."
                )
        elif action_contract.get("actionable") is False:
            situation_parts.append(
                "CONTRACT: Diagnosis found no actionable target. Return "
                "the kernel unchanged unless source_banking_evidence proves "
                "an exact target and dimension."
            )
    if source_banking_evidence:
        arrays = sorted(
            {str(item.get("array") or "") for item in source_banking_evidence if item.get("array")}
        )
        if arrays:
            situation_parts.append(
                f"EVIDENCE: Source-backed banking targets available for: {', '.join(arrays)}. "
                "Use only the listed local arrays and exact proven dimensions."
            )
    if source_architecture_evidence:
        kinds = sorted(
            {str(item.get("kind") or "") for item in source_architecture_evidence}
        )
        if kinds:
            situation_parts.append(
                f"EVIDENCE: Source architecture opportunities: {', '.join(kinds)}. "
                "Use only the named functions, stages, loops, and factors listed."
            )
    # When the primary bottleneck is resolved but the kernel has room for
    # secondary improvement, encourage complementary optimization families
    # that are often effective after the first architecture change.
    if (not situation_parts
            and action_contract
            and isinstance(action_contract, dict)
            and action_contract.get("actionable") is False):
        # No actionable primary bottleneck — suggest inspecting the source
        # directly for secondary opportunities (e.g. stage-local PIPELINE
        # after DATAFLOW, ARRAY_PARTITION for local buffers).
        situation_parts.append(
            "The primary bottleneck has been addressed. Inspect the editable "
            "source for complementary optimizations: stage-local PIPELINE or "
            "UNROLL within parallel regions, ARRAY_PARTITION for local arrays "
            "with concurrent access, or stream depth tuning. Propose exactly "
            "one measured candidate."
        )
    situation = (
        " | ".join(situation_parts)
        if situation_parts
        else "Propose ONE evidence-matched optimization candidate. "
        "Prefer the structured bottleneck diagnosis as primary evidence."
    )

    payload["instruction"] = (
        f"SITUATION: {situation}\n\n"
        "Detailed rules (in priority order):\n"
        "- If csim FAILED: fix the functional bug. Do NOT add pragmas.\n"
        "- If cosim DEADLOCKS/TIMEOUT: fix streaming imbalance (interleave writes, add stream depths).\n"
        f"- If all PASSED: {optimization_instruction}\n"
        "- If previous_candidate_feedback.status starts with REJECTED_BY_CSIM: use its exact compiler/runtime evidence "
        "and failed_candidate_diff. Apply required_next_action before considering any new architecture.\n"
        "- If previous_candidate_feedback.status starts with REJECTED_BY_SYNTH: use its exact diagnostic lines, "
        "candidate_action_diff_summary, implicated pragmas/loops/arrays, and repetition_count. Roll back the unsupported "
        "change and obey recommended_next_constraint.\n"
        "- REJECTED_BY_SYNTH_EVIDENCE_INTENT: the action contradicted a measured HLS bottleneck. Address its exact array/resource evidence with matched banking or real locality code; do not repeat standalone PIPELINE/UNROLL.\n"
        "- REJECTED_BY_STRATEGY_CONTRACT: stay in the same search_strategy and correct the exact contract violation.\n"
        "- REJECTED_BY_INTERFACE_GATE: regenerate a complete C/C++ translation unit with the required top function, includes, and balanced delimiters.\n"
        "- anti_repeat_contract present: do not repeat an exact rejected action signature. A changed factor/target/architecture is a new hypothesis only with current report/source justification.\n"
        "- measured_action_contract present: if actionable=false, return unchanged (unless source_banking_evidence proves a target). If actionable=true, select at most one candidate_families entry; never invent a missing target or precondition.\n"
        "- source_banking_evidence present: use only listed local arrays, exact proven dimensions, and banking_option_space. Do not bank unlisted or top-level arrays.\n"
        "- source_architecture_evidence present: use only the named top function, stages, connectors, and listed factor candidates. Never use a composite family when its matching evidence kind is absent.\n"
        "- Other previous_candidate_feedback: obey directional_constraint and required_next_action. A new hypothesis must be justified by current evidence and measured independently.\n"
        "\nReturn the FULL kernel source code inside a ```cpp fence. Keep the top function "
        "signature and language linkage (including any extern \"C\") UNCHANGED."
    )
    return json.dumps(payload, indent=2, ensure_ascii=False)


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
