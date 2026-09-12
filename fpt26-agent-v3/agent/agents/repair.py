"""RepairAgent — LLM-driven repair loop for C-simulation failures.

Open this file to understand the core repair logic::

    for attempt in 1..max_attempts:
        csim(current_kernel)          → ToolResult  (simulate)
        if pass → done                → read result  (read result)
        if fail:
            normalize log             → clean up output
            classify issue            → what kind of failure?
            build prompt              → pack context + error
            llm.complete(prompt)      → LLM modifies code
            extract_code(response)    → parse new kernel
            loop back to csim         → simulate again (decide: retry or stop)
"""

from __future__ import annotations

import difflib
import hashlib
from typing import Any

from agent.integrations.harness import ToolResult
from agent.integrations.llm.protocol import LLMCallFailed, complete_with_reason

from agent.agents.base import RunState
from agent.analysis.issue_classifier import IssueClassifier
from agent.analysis.log_normalizer import LogNormalizer
from agent.prompts import REPAIR_SYSTEM, build_repair_prompt
from agent.candidate.validator import extract_code  # single authority


class RepairAgent:
    """Iteratively repair a kernel that fails C-simulation.

    The loop::

        1. reuse pipeline failed csim, or csim(current_kernel) → ToolResult
        2. if pass → done (repair succeeded)
        3. if fail → normalize log, classify issue
        4. build prompt with error context
        5. llm.complete(system, prompt) → get LLM response
        6. extract_code(response) → new kernel
        7. goto 1 (up to max_attempts)

    This is intentionally explicit — no hidden abstractions.
    """

    def __init__(
        self,
        llm: Any,
        max_attempts: int = 6,
    ) -> None:
        self.llm = llm
        self.max_attempts = max_attempts
        self.log_normalizer = LogNormalizer()
        self.issue_classifier = IssueClassifier()

    def run(self, state: RunState) -> RunState:
        """Run the repair loop. Returns updated RunState."""
        task = state.task
        server = state.server
        stable_code = state.kernel
        working_code = stable_code
        seen_candidate_hashes = {_source_fingerprint(stable_code)}
        state.metadata.setdefault("repair_duplicate_skips", 0)
        state.metadata.setdefault("repair_no_change_skips", 0)
        state.metadata.setdefault("repair_working_candidate_advances", 0)
        failure = state.results[-1] if state.results else None
        previous_attempt: dict[str, Any] | None = None
        if getattr(failure, "ok", True):
            failure = None

        for attempt in range(1, self.max_attempts + 1):
            if failure is None:
                failure = server.csim(stable_code)
                state.results.append(failure)
                if failure.ok:
                    failure = server.synth(stable_code)
                    state.results.append(failure)
                if failure.ok:
                    state.csim_ok = True
                    state.synth_ok = True
                    state.kernel = stable_code
                    return state
            elif attempt == 1:
                state.log(
                    f"repair: reusing pipeline {getattr(failure, 'kind', 'tool')} failure"
                )

            # ── 3. Read result → normalize log → classify issue ───────────
            log_text = getattr(failure, "log", "") or ""
            phase = getattr(failure, "phase", "unknown") or "unknown"
            kind = getattr(failure, "kind", "csim") or "csim"

            normalized = self.log_normalizer.normalize(kind, phase, log_text)
            issue = self.issue_classifier.classify(failure, normalized)

            # ── 4. Build prompt with error context ────────────────────────
            prompt = build_repair_prompt(
                task=task,
                current_kernel=working_code,
                normalized_log=normalized,
                issue=issue,
                attempt_feedback={
                    "attempt": attempt,
                    "phase": phase,
                    "previous_attempt": previous_attempt,
                },
            )

            # ── 5. LLM modifies code ──────────────────────────────────────
            # The executor never raises; it returns an empty response carrying
            # the reason.  Surfacing that reason stops an API failure from being
            # recorded as the model proposing no change — the pipeline turns it
            # into a named infrastructure error instead.
            response = complete_with_reason(
                self.llm, REPAIR_SYSTEM, prompt
            )
            if response.error is not None:
                raise LLMCallFailed(
                    f"repair attempt {attempt}: {response.error}"
                )
            new_code = extract_code(
                response.text,
                required_token=str(getattr(task, "top", "") or ""),
            )
            if new_code is None or new_code.strip() == working_code.strip():
                state.log(f"repair attempt {attempt}: LLM returned no change")
                state.metadata["repair_no_change_skips"] += 1
                previous_attempt = {
                    "attempt": attempt,
                    "candidate_diff": "",
                    "result": {
                        "stage": kind,
                        "phase": "no_change",
                        "summary": "LLM returned no material source change.",
                    },
                }
                continue

            candidate_hash = _source_fingerprint(new_code)
            if candidate_hash in seen_candidate_hashes:
                state.metadata["repair_duplicate_skips"] += 1
                state.log(
                    f"repair attempt {attempt}: duplicate candidate — skip tools"
                )
                previous_attempt = _repair_attempt_record(
                    attempt,
                    working_code,
                    new_code,
                    ToolResult(
                        kind=kind,
                        ok=False,
                        phase="duplicate_candidate",
                        return_code=-1,
                        log=(
                            "This exact source was already tested. Propose a "
                            "materially different repair hypothesis."
                        ),
                        elapsed_s=0.0,
                    ),
                )
                continue
            seen_candidate_hashes.add(candidate_hash)

            # ── 6. Validate the proposal immediately in this attempt ─────
            from agent.candidate.validator import (
                mark_fully_verified,
                record_synth_gates,
                validate_candidate,
            )

            if not validate_candidate(
                state,
                new_code,
                stage=f"repair_candidate_{attempt}",
                current_best=False,
            ):
                validation = state.metadata.get("interface_validations", [{}])[-1]
                failure = ToolResult(
                    kind="csim",
                    ok=False,
                    phase="compile_error",
                    return_code=-1,
                    log=(
                        "Candidate rejected by deterministic interface gate: "
                        + str(
                            validation.get(
                                "reason", "unknown"
                            )
                        )
                    ),
                    elapsed_s=0.0,
                )
                previous_attempt = _repair_attempt_record(
                    attempt, working_code, new_code, failure
                )
                continue

            cr = server.csim(new_code)
            state.results.append(cr)
            state.log(f"repair attempt {attempt}: {cr.brief()}")
            if not cr.ok:
                failure = cr
                previous_attempt = _repair_attempt_record(
                    attempt, working_code, new_code, failure
                )
                working_code = new_code
                state.metadata["repair_working_candidate_advances"] += 1
                continue

            sr = server.synth(new_code)
            state.results.append(sr)
            state.log(f"repair attempt {attempt}: {sr.brief()}")
            if not sr.ok:
                failure = sr
                previous_attempt = _repair_attempt_record(
                    attempt, working_code, new_code, failure
                )
                working_code = new_code
                state.metadata["repair_working_candidate_advances"] += 1
                continue
            if not record_synth_gates(
                state,
                sr,
                stage=f"repair_candidate_{attempt}",
                current_best=False,
            ):
                failure = ToolResult(
                    kind="synth",
                    ok=False,
                    phase="target_gate_fail",
                    return_code=-1,
                    log=(
                        "Candidate synthesis completed but failed the mandatory "
                        "100 MHz and/or device-capacity gate."
                    ),
                    elapsed_s=0.0,
                    report=sr.report,
                )
                state.log(
                    f"repair attempt {attempt}: target gate failed — discard"
                )
                previous_attempt = _repair_attempt_record(
                    attempt, working_code, new_code, failure
                )
                working_code = new_code
                state.metadata["repair_working_candidate_advances"] += 1
                continue

            state.kernel = new_code
            state.csim_ok = True
            state.synth_ok = True
            state.status = "running"
            state.stop_reason = ""
            record_synth_gates(
                state,
                sr,
                stage=f"repair_candidate_{attempt}_accepted",
            )
            latency = (
                sr.report.latency_worst
                if sr.report and sr.report.latency_worst is not None
                else (sr.report.latency_avg if sr.report else None)
            )
            if latency is not None:
                state.best_latency = latency
            if not task.requires_cosim:
                mark_fully_verified(state)
            state.log(f"repair: succeeded on attempt {attempt}")
            return state

        # Max attempts exhausted
        state.kernel = stable_code
        state.status = "failed"
        state.stop_reason = "repair_failed"
        state.log(f"repair: failed after {self.max_attempts} attempts")
        return state


def _source_fingerprint(source: str) -> str:
    """Hash source deterministically while ignoring newline-style noise."""

    normalized = source.replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _repair_attempt_record(
    attempt: int, base_code: str, candidate: str, result: Any
) -> dict[str, Any]:
    """Build bounded evidence for the next repair attempt without another call."""
    diff = "\n".join(
        difflib.unified_diff(
            base_code.splitlines(),
            candidate.splitlines(),
            fromfile="editable_kernel",
            tofile="failed_candidate",
            n=2,
            lineterm="",
        )
    )
    if len(diff) > 2_000:
        diff = diff[:1_984].rstrip() + "\n... [truncated]"
    log = getattr(result, "log", "") or ""
    if isinstance(log, bytes):
        log = log.decode("utf-8", errors="replace")
    else:
        log = str(log)
    normalized = LogNormalizer(max_summary_chars=500, max_key_lines=12).normalize(
        getattr(result, "kind", "unknown") or "unknown",
        getattr(result, "phase", "unknown") or "unknown",
        log,
    )
    summary = normalized.error_summary or ""
    if len(summary) > 500:
        summary = summary[:484].rstrip() + "... [truncated]"
    return {
        "attempt": attempt,
        "candidate_diff": diff,
        "result": {
            "stage": getattr(result, "kind", "unknown") or "unknown",
            "phase": getattr(result, "phase", "unknown") or "unknown",
            "summary": summary or "candidate validation failed",
        },
    }
