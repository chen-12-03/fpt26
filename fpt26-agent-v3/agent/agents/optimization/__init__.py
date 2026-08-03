"""OptimizeAgent split — diagnostics, feedback, and strategies are pure functions."""
from agent.agents.optimization.diagnostics import _diagnose, _report, _latency, _report_latency, _resource_delta
from agent.agents.optimization.feedback import _rejection_feedback, _csim_failure_feedback, _candidate_diff
from agent.agents.optimization.strategies import (
    _strategy_contract_violation,
    _candidate_fingerprint, _without_hls_pragmas_fingerprint, _hls_pragmas,
)
