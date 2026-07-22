"""Backward-compatibility re-exports for reporting.

All business logic has been migrated to:
- ``metrics.py``     — derived metrics, toolchain evidence, execution trace,
                       synth info, display helpers
- ``builder.py``     — report construction
- ``writer.py``      — atomic file I/O
- ``console.py``     — console display (``print_evaluation``, ``print_transcript``)

This module is a **thin re-export layer**.  New code MUST import from the
canonical modules directly.  Tests MUST NOT import private helpers from here.
"""

from __future__ import annotations

# ── Re-exports from metrics (the single derived-metrics implementation) ──
from agent.reporting.metrics import (  # noqa: F401
    _attempts_to_pass,
    _compute_derived,
    _execution_trace,
    _final_synth_info,
    _grading_synth_info,
    _llm_summary,
    _reported_cosim_status,
    _resource_growth,
    _synth_info,
    _tool_breakdown,
    _tool_result_record,
    _toolchain_evidence,
    _wall_time,
)

# ── Re-exports from builder ───────────────────────────────────────────────
from agent.reporting.builder import build_report  # noqa: F401

# ── Re-exports from writer ────────────────────────────────────────────────
from agent.reporting.writer import (  # noqa: F401
    write_failure_report,
    write_json_report,
    final_kernel_digest,
)

# ── Re-exports from console ───────────────────────────────────────────────
from agent.reporting.console import (  # noqa: F401
    print_candidate_table,
    print_comparison_table,
    print_evaluation,
    print_scorecard,
    print_transcript,
)

# ── Public API — delegates to canonical modules ───────────────────────────
from agent.reporting.console import print_evaluation, print_transcript  # noqa: F401, F811


def write_run_report(state: "RunState") -> "Path":  # noqa: F821
    """Write a JSON run report via ``builder.build_report`` + ``writer.write_json_report``."""
    from pathlib import Path
    from agent.reporting.builder import build_report
    from agent.reporting.writer import write_json_report

    report = build_report(state)
    out_dir = Path(state.config.output_root) / state.task.id
    return write_json_report(report, out_dir)
