"""Single harness boundary — all llm4hls imports flow through here.

Pipeline, candidate, and agents must NOT import from ``llm4hls`` directly.
Use the adapters exported by this module instead.

At startup the harness source is detected and recorded for audit.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# ── Harness provenance (lazy, detected on first call) ────────────────────────

_provenance: dict[str, str] | None = None


def harness_provenance() -> dict[str, str]:
    """Return ``{source, path}`` for audit logging.  Detected lazily."""
    global _provenance
    if _provenance is not None:
        return dict(_provenance)

    # llm4hls is guaranteed to be in sys.modules after the imports below
    for mod_name in ("llm4hls",):
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        f = getattr(mod, "__file__", None)
        if f:
            path = str(Path(f).resolve())
            source = "fpt26-agent-v3/llm4hls" if "fpt26-agent-v3" in path else path
            _provenance = {"source": source, "path": path}
            return dict(_provenance)

    _provenance = {"source": "unknown", "path": ""}
    return dict(_provenance)


# ── Re-export harness types through a single boundary ────────────────────────

from llm4hls.budget import Budget, BudgetExceeded  # noqa: F401
from llm4hls.task import Task, load_task  # noqa: F401
from llm4hls.tools import (  # noqa: F401
    CoSimTool as HarnessCoSimTool,
    CSimTool as HarnessCSimTool,
    SynthTool as HarnessSynthTool,
    ToolResult,
)
from llm4hls.harness import ToolServer as HarnessToolServer  # noqa: F401
from llm4hls.harness import ToolServer  # noqa: F401 — bare name for compat
from llm4hls.config import (  # noqa: F401
    DEFAULT_PART,
    DEFAULT_CLOCK_NS,
    DEFAULT_FLOW_TARGET,
    CREDIT_COST,
    CSIM_TIMEOUT_S,
    SYNTH_TIMEOUT_S,
    COSIM_TIMEOUT_S,
)
