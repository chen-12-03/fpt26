"""OptimizeAgent — thin compatibility façade.

The full optimization loop lives in ``agent.agents.optimization.controller``.
Diagnostics, feedback, strategies, scoring, and intent are in sibling modules.
"""

from __future__ import annotations

from typing import Any
from agent.agents.base import RunState
from scoring.profiles import DEFAULT_SCORING_PROFILE

# ── Re-exports for backward compatibility ───────────────────────────────
from agent.agents.optimization.diagnostics import (  # noqa: F401
    _diagnose, _latency, _report, _report_latency, _resource_delta,
)
from agent.agents.optimization.feedback import (  # noqa: F401
    _candidate_diff, _csim_failure_feedback, _rejection_feedback,
)
from agent.agents.optimization.strategies import (  # noqa: F401
    _anti_repeat_action_violation, _candidate_fingerprint, _hls_pragmas,
    _report_supported_action_violation,
    _source_array_rank, _strategy_contract_violation,
    _top_function_inline_noop,
    _without_hls_pragmas_fingerprint,
    candidate_action_summary,
    distinct_report_supported_alternatives,
    inferred_directive_delta,
)
from agent.agents.optimization.intent import (  # noqa: F401
    ii_resource_intent_feedback as _ii_resource_intent_feedback,
)
from agent.agents.optimization.scoring import (  # noqa: F401
    score_candidate as _score_candidate,
    latest_successful_cosim_latency as _latest_successful_cosim_latency,
    latest_successful_synth as _latest_successful_synth,
)


class SimpleToolResult:
    """Minimal adapter allowing synthesis-report formatting without a tool call."""

    def __init__(self, report: Any) -> None:
        self.report = report


class OptimizeAgent:
    """Resource-aware optimization using scoring_v3 QoR selection.

    Delegates to ``agent.agents.optimization.controller.run_optimization_loop``.
    """

    def __init__(
        self,
        llm: Any,
        max_rounds: int = 5,
        scoring_profile: str = DEFAULT_SCORING_PROFILE,
        search_strategy: dict[str, Any] | None = None,
        shared_candidate_fingerprints: set[str] | None = None,
        stop_after_first_measured: bool = False,
        early_stop_on_qhw_improvement: bool | None = None,
        generalized_qor_rag: bool | None = None,
    ) -> None:
        self.llm = llm
        self.max_rounds = max_rounds
        self.scoring_profile = scoring_profile
        self.search_strategy = search_strategy
        self.shared_candidate_fingerprints = shared_candidate_fingerprints
        self.stop_after_first_measured = stop_after_first_measured
        self.early_stop_on_qhw_improvement = early_stop_on_qhw_improvement
        self.generalized_qor_rag = generalized_qor_rag
        self.max_stag = 3

    def run(self, state: RunState) -> RunState:
        from agent.agents.optimization.controller import run_optimization_loop
        return run_optimization_loop(
            state=state, llm=self.llm, max_rounds=self.max_rounds,
            scoring_profile=self.scoring_profile,
            search_strategy=self.search_strategy,
            shared_candidate_fingerprints=self.shared_candidate_fingerprints,
            stop_after_first_measured=self.stop_after_first_measured,
            early_stop_on_qhw_improvement=self.early_stop_on_qhw_improvement,
            generalized_qor_rag=self.generalized_qor_rag,
            max_stag=self.max_stag,
        )
