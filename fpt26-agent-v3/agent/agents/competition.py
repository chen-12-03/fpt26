"""CompetitionStage — run N agents in parallel, select the best result.

This enables multi-agent competition within a pipeline stage.  Example::

    # 3 optimization agents compete; the lowest-latency result wins
    stage = CompetitionStage(
        n_agents=3,
        agent_factory=lambda i, llm: OptimizeAgent(llm, max_rounds=3),
        selector=lowest_latency_selector,
    )
    state = stage.run(state)
"""

from __future__ import annotations

from typing import Any, Callable

from agent.agents.base import RunState


DIVERSE_OPTIMIZATION_STRATEGIES: tuple[dict[str, Any], ...] = (
    {
        "name": "evidence_backed_directive",
        "objective": "Test one directive action supported by measured report or deterministic source evidence.",
        "required_family": (
            "Preserve source arithmetic and apply one directive family whose exact "
            "target is supported by measured II/port evidence or source banking evidence."
        ),
        "forbidden_changes": [
            "source-level reduction rewrite",
            "ARRAY_PARTITION/RESHAPE without measured port or source banking evidence",
            "UNROLL that overlaps a Vitis inferred pipeline/unroll/flatten hierarchy",
            "function-scope PIPELINE",
        ],
    },
    {
        "name": "task_pipeline_architecture",
        "objective": (
            "Test one coherent task-pipeline architecture when deterministic "
            "source evidence proves connected helper stages."
        ),
        "required_family": (
            "Use TASK_PIPELINE only when source_architecture_evidence names "
            "the top, connected stage calls, and connectors. A coherent trial "
            "may combine DATAFLOW with stage-boundary INLINE OFF and stage-local "
            "PIPELINE/LATENCY directives, but remains one architecture family."
        ),
        "forbidden_changes": [
            "DATAFLOW without source-proven connected stages",
            "ARRAY_PARTITION, ARRAY_RESHAPE, UNROLL, interface changes, or arithmetic changes",
            "changing the top signature or connector semantics",
        ],
    },
    {
        "name": "source_parallel_architecture",
        "objective": (
            "Explore one source-level parallel architecture derived from "
            "deterministic loop/access evidence."
        ),
        "required_family": (
            "Change C/C++ structure while preserving numeric behavior and the "
            "top interface. When source_architecture_evidence exposes a "
            "composite family such as REDUCTION_PARALLELISM, use only its named "
            "loop, arrays, and finite factor candidates; otherwise make a "
            "pragma-free SOURCE_RESTRUCTURE trial."
        ),
        "forbidden_changes": [
            "inventing an unlisted factor, loop, array, or composite family",
            "copying either directive lane",
            "changing numeric types or observable arithmetic semantics",
        ],
    },
)


AgentFactory = Callable[[int, Any], Any]  # (index, llm) -> Agent instance
Selector = Callable[[list[RunState]], RunState]  # pick best from candidates


def lowest_latency_selector(states: list[RunState]) -> RunState:
    """Select the state with the lowest latency."""
    best = states[0]
    for s in states[1:]:
        if s.best_latency is not None and (
            best.best_latency is None or s.best_latency < best.best_latency
        ):
            best = s
    return best


def first_passing_selector(states: list[RunState]) -> RunState:
    """Select the first state that passed correctness (for repair)."""
    for s in states:
        if s.csim_ok:
            return s
    # None passed — return the first one (has error context)
    return states[0]


class CompetitionStage:
    """Run N independent agents and select the best result.

    Each agent gets a copy of the initial state and runs independently.
    After all agents finish, the selector picks the winning result.

    In the future this can be extended to concurrent execution, but for
    now agents run sequentially to be safe with HLS tool licenses.
    """

    def __init__(
        self,
        n_agents: int = 3,
        agent_factory: AgentFactory | None = None,
        selector: Selector | None = None,
    ) -> None:
        self.n_agents = n_agents
        self.agent_factory = agent_factory
        self.selector = selector or lowest_latency_selector

    def run(self, state: RunState) -> RunState:
        """Run all agents and return the selected winner."""
        candidates: list[RunState] = []

        for i in range(self.n_agents):
            # Each agent works on a copy of the state
            agent_state = RunState(
                task=state.task,
                server=state.server,
                llm=state.llm,
                config=state.config,
                kernel=state.kernel,
                best_latency=state.best_latency,
            )

            if self.agent_factory is not None:
                agent = self.agent_factory(i, state.llm)
                agent_state = agent.run(agent_state)
            # (If no factory, just collect baseline copies)

            # Merge results back
            state.results.extend(agent_state.results)
            candidates.append(agent_state)
            state.log(f"competition agent {i + 1}/{self.n_agents}: "
                      f"latency={agent_state.best_latency} csim_ok={agent_state.csim_ok}")

        # Select winner
        winner = self.selector(candidates)
        state.kernel = winner.kernel
        state.best_latency = winner.best_latency
        state.csim_ok = winner.csim_ok
        state.synth_ok = winner.synth_ok
        state.cosim_ok = winner.cosim_ok
        state.log(f"competition: selected agent with latency={winner.best_latency}")
        return state


class DiverseOptimizationStage:
    """Measure independent strategy lanes, refine the winner, and fall back when needed.

    Lanes share only the immutable baseline and a semantic candidate fingerprint
    set.  They run sequentially to avoid Vitis license contention.  After
    selecting the highest-Q_HW lane, a brief unconstrained refinement phase
    polishes the winning kernel.  When no lane improves the baseline, an
    unconstrained fallback pass ensures the search is not prematurely abandoned.
    """

    def __init__(
        self,
        llm: Any,
        *,
        max_candidates: int,
        scoring_profile: str,
    ) -> None:
        self.llm = llm
        self.max_candidates = max(1, max_candidates)
        self.scoring_profile = scoring_profile

    def run(self, state: RunState) -> RunState:
        from agent.agents.optimize import OptimizeAgent, _candidate_fingerprint

        def _newest_synth_report(results: list[Any]) -> Any | None:
            """Return the report from the newest successful synthesis result."""
            for result in reversed(results):
                if (getattr(result, "kind", None) == "synth"
                        and getattr(result, "ok", False)
                        and getattr(result, "report", None) is not None):
                    return result.report
            return None

        strategies = DIVERSE_OPTIMIZATION_STRATEGIES[: self.max_candidates]
        baseline_kernel = state.kernel
        baseline_fingerprint = _candidate_fingerprint(baseline_kernel)
        baseline_results = list(state.results)
        baseline_result_count = len(baseline_results)
        shared_fingerprints: set[str] = set()
        accumulated_failures: list[dict[str, Any]] = []
        children: list[RunState] = []
        strategy_results: list[dict[str, Any]] = []

        for index, strategy in enumerate(strategies):
            child = RunState(
                task=state.task,
                server=state.server,
                llm=state.llm,
                config=state.config,
                kernel=baseline_kernel,
                results=list(baseline_results),
                csim_ok=state.csim_ok,
                synth_ok=state.synth_ok,
                cosim_ok=state.cosim_ok,
                interface_ok=state.interface_ok,
                frequency_ok=state.frequency_ok,
                resource_ok=state.resource_ok,
                best_latency=state.best_latency,
                best_synth_result=state.best_synth_result,
                last_verified_kernel=state.last_verified_kernel,
                safe_fallback_kernel=state.safe_fallback_kernel,
                metadata={},
            )
            # Seed each child with prior-lane synthesis failures so later
            # lanes avoid repeating the same unsupported constructs.
            if accumulated_failures:
                child.metadata["prior_lane_optimization_failures"] = list(
                    accumulated_failures
                )
            agent = OptimizeAgent(
                self.llm,
                max_rounds=4,
                scoring_profile=self.scoring_profile,
                search_strategy=strategy,
                shared_candidate_fingerprints=shared_fingerprints,
                stop_after_first_measured=True,
                early_stop_on_qhw_improvement=False,
                generalized_qor_rag=True,
            )
            child = agent.run(child)
            new_results = child.results[baseline_result_count:]
            state.results.extend(new_results)
            children.append(child)

            lane_failures = child.metadata.get("optimization_failures", [])
            if lane_failures:
                accumulated_failures.extend(lane_failures)

            changed = (
                _candidate_fingerprint(child.kernel) != baseline_fingerprint
            )
            measured_entries = [
                entry
                for entry in child.metadata.get("synth_candidates", [])
                if not entry.get("is_baseline") and entry.get("round") != 0
            ]
            proposal = measured_entries[-1] if measured_entries else {}
            result = {
                "index": index,
                "strategy": strategy["name"],
                "changed": changed,
                "improved_baseline": changed,
                "measured_candidate": bool(measured_entries),
                "proposal_q_hw": proposal.get("q_hw_after"),
                "proposal_latency": proposal.get("latency"),
                "proposal_decision": proposal.get("decision"),
                "best_q_hw": child.metadata.get("best_q_hw"),
                "best_latency": child.best_latency,
                "candidate_tool_calls": len(new_results),
                "semantic_duplicate_skips": child.metadata.get(
                    "cross_strategy_duplicate_skips", 0
                ),
                "strategy_contract_rejections": child.metadata.get(
                    "strategy_contract_rejections", 0
                ),
                "strategy_contract_rejection_reasons": child.metadata.get(
                    "strategy_contract_rejection_reasons", []
                ),
                "selected": False,
            }
            strategy_results.append(result)
            state.log(
                f"strategy {index + 1}/{len(strategies)} "
                f"{strategy['name']}: changed={changed} "
                f"Q_HW={result['best_q_hw']} tools={len(new_results)}"
            )

        def _quality(index: int) -> float:
            value = children[index].metadata.get("best_q_hw")
            return float(value) if value is not None else -1.0

        winner_index = max(range(len(children)), key=_quality)
        winner = children[winner_index]
        strategy_results[winner_index]["selected"] = True
        any_lane_improved = any(
            _candidate_fingerprint(child.kernel) != baseline_fingerprint
            for child in children
        )

        # ── Post-competition refinement ────────────────────────────────
        # When a lane found an improvement, polish it with 2–3
        # unconstrained rounds.  Otherwise run a fallback pass from the
        # baseline so the search is not abandoned when no strategy matched.
        refinement_starter = (
            winner.kernel if any_lane_improved else baseline_kernel
        )
        refinement_phase = (
            "post_competition_refinement"
            if any_lane_improved
            else "post_competition_fallback"
        )
        state.log(
            f"strategy competition: {refinement_phase} "
            f"(any_improvement={any_lane_improved})"
        )
        refinement_kernel_before = _candidate_fingerprint(refinement_starter)
        # Build refinement results: baseline results (for anchor) + winner's
        # best synth result (so the prompt shows the actual current synthesis).
        refinement_results = list(baseline_results)
        winner_best = (
            winner.best_synth_result
            if any_lane_improved
            else state.best_synth_result
        )
        if winner_best is not None and getattr(winner_best, "report", None) is not None:
            refinement_results.append(winner_best)
        # Extract the baseline anchor report from baseline results so the
        # controller can pin scoring against the starter regardless of which
        # synth result is reused for the prompt.
        baseline_anchor = _newest_synth_report(baseline_results)
        refine_child = RunState(
            task=state.task,
            server=state.server,
            llm=state.llm,
            config=state.config,
            kernel=refinement_starter,
            results=refinement_results,
            csim_ok=state.csim_ok,
            synth_ok=state.synth_ok,
            cosim_ok=state.cosim_ok,
            interface_ok=state.interface_ok,
            frequency_ok=state.frequency_ok,
            resource_ok=state.resource_ok,
            best_latency=(
                winner.best_latency
                if any_lane_improved
                else state.best_latency
            ),
            best_synth_result=winner_best,
            last_verified_kernel=state.last_verified_kernel,
            safe_fallback_kernel=state.safe_fallback_kernel,
            metadata={},
        )
        if baseline_anchor is not None:
            refine_child.metadata["baseline_anchor_report"] = baseline_anchor
        if accumulated_failures:
            refine_child.metadata["prior_lane_optimization_failures"] = list(
                accumulated_failures
            )
        refine_agent = OptimizeAgent(
            self.llm,
            max_rounds=4,
            scoring_profile=self.scoring_profile,
            search_strategy=None,  # unconstrained
            shared_candidate_fingerprints=None,
            stop_after_first_measured=False,
            early_stop_on_qhw_improvement=False,
            generalized_qor_rag=True,
        )
        refine_child = refine_agent.run(refine_child)
        refine_initial_count = len(refinement_results)
        refine_results = refine_child.results[refine_initial_count:]
        state.results.extend(refine_results)
        refinement_changed = (
            _candidate_fingerprint(refine_child.kernel)
            != refinement_kernel_before
        )
        refinement_q_hw = refine_child.metadata.get("best_q_hw")
        refinement_improved = (
            refinement_changed
            and refinement_q_hw is not None
            and (
                winner.metadata.get("best_q_hw") is None
                or refinement_q_hw > winner.metadata.get("best_q_hw", -1.0)
            )
        )
        state.log(
            f"refinement: changed={refinement_changed} "
            f"Q_HW={refinement_q_hw} improved={refinement_improved}"
        )
        if refinement_improved or (
            not any_lane_improved and refinement_changed
        ):
            winner = refine_child
            strategy_results.append({
                "strategy": refinement_phase,
                "changed": refinement_changed,
                "improved_baseline": refinement_changed,
                "best_q_hw": refinement_q_hw,
                "best_latency": refine_child.best_latency,
                "selected": True,
            })

        combined_candidates: list[dict[str, Any]] = []
        for index, child in enumerate(children):
            entries = child.metadata.get("synth_candidates", [])
            for entry in entries:
                if entry.get("is_baseline") or entry.get("round") == 0:
                    if not combined_candidates:
                        combined_candidates.append(dict(entry))
                    continue
                combined = dict(entry)
                combined["strategy"] = strategies[index]["name"]
                if combined.get("decision") == "ACCEPTED":
                    combined["decision"] = (
                        "SELECTED"
                        if (
                            index == winner_index
                            and not refinement_improved
                        )
                        else "VALID_NOT_SELECTED"
                    )
                combined_candidates.append(combined)
        # Append refinement-phase candidates
        for entry in refine_child.metadata.get("synth_candidates", []):
            if entry.get("is_baseline") or entry.get("round") == 0:
                continue
            combined = dict(entry)
            combined["strategy"] = refinement_phase
            if combined.get("decision") == "ACCEPTED":
                combined["decision"] = (
                    "SELECTED" if refinement_improved else "VALID_NOT_SELECTED"
                )
            combined_candidates.append(combined)

        state.kernel = winner.kernel
        state.best_latency = winner.best_latency
        state.csim_ok = winner.csim_ok
        state.synth_ok = winner.synth_ok
        state.cosim_ok = winner.cosim_ok
        state.interface_ok = winner.interface_ok
        state.frequency_ok = winner.frequency_ok
        state.resource_ok = winner.resource_ok
        state.best_synth_result = winner.best_synth_result
        state.last_verified_kernel = winner.last_verified_kernel
        for key in (
            "interface_contract",
            "interface_gate",
            "interface_validations",
            "frequency_gate",
            "resource_gate",
            "synth_gate_history",
            "best_synth_metrics",
            "cosim_gate",
            "cosim_gate_history",
            "last_verified_kernel_stage",
        ):
            if key in winner.metadata:
                state.metadata[key] = winner.metadata[key]
        state.metadata["best_q_hw"] = winner.metadata.get("best_q_hw")
        state.metadata["synth_candidates"] = combined_candidates
        state.metadata["optimization_search"] = {
            "kind": "independent_strategy_competition_with_refinement",
            "selector": "highest_measured_q_hw",
            "scoring_profile": self.scoring_profile,
            "sequential_vitis": True,
            "qor_rag_generalized": True,
            "qor_rag_policy": (
                "competition lanes force generalized QoR-RAG so legacy "
                "specialist fallback and exact-source measured-case boosts "
                "cannot influence formal strategy selection"
            ),
            "strategies": strategy_results,
            "winner": (
                refinement_phase
                if refinement_improved
                else strategies[winner_index]["name"]
            ),
            "refinement": {
                "phase": refinement_phase,
                "changed": refinement_changed,
                "q_hw": refinement_q_hw,
                "improved_over_winner": refinement_improved,
                "any_lane_improved": any_lane_improved,
            },
        }
        state.metadata["semantic_duplicate_skips"] = sum(
            child.metadata.get("semantic_duplicate_skips", 0)
            for child in children
        )
        state.metadata["cross_strategy_duplicate_skips"] = sum(
            child.metadata.get("cross_strategy_duplicate_skips", 0)
            for child in children
        )
        state.metadata["ii_resource_intent_rejections"] = sum(
            child.metadata.get("ii_resource_intent_rejections", 0)
            for child in children
        )
        state.metadata["strategy_contract_rejections"] = sum(
            child.metadata.get("strategy_contract_rejections", 0)
            for child in children
        )
        state.log(
            f"strategy competition final: "
            f"Q_HW={state.metadata['best_q_hw']} "
            f"winner={state.metadata['optimization_search']['winner']}"
        )
        return state
