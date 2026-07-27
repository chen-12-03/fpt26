"""Reporting package — run reports, console output, cross-run aggregation.

Re-exports the legacy ``_legacy.py`` module for full backward compatibility
and adds new V3-aware modules alongside it.
"""

# ── Legacy API (backward compatible) ─────────────────────────────────────
from agent.reporting._legacy import (  # noqa: F401
    print_evaluation,
    print_transcript,
    write_failure_report,
    write_run_report,
    # Semi-private exports used by tests
    _attempts_to_pass,
    _compute_derived,
    _final_synth_info,
    _grading_synth_info,
    _reported_cosim_status,
)

# ── New V3 modules ───────────────────────────────────────────────────────
from agent.reporting.aggregate import (  # noqa: F401
    collect_reports,
    RunSummary,
    TaskAggregate,
)
from agent.reporting.schema import (  # noqa: F401
    REPORT_SCHEMA_VERSION,
    RESOURCE_KEYS,
    SCORING_FIELDS_V3,
    STATUS_VOCABULARY,
)
from agent.reporting.writer import (  # noqa: F401
    final_kernel_digest,
    write_json_report,
)
from agent.reporting.console import (  # noqa: F401
    print_candidate_table,
    print_comparison_table,
    print_scorecard,
)

# CLI-oriented compact renderer.  Imported last to replace the legacy fixed-width
# report while keeping the legacy report writer and metric helpers intact.
from agent.reporting.pretty import print_evaluation, print_transcript  # noqa: F401, E402
