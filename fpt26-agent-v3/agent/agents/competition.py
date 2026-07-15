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
