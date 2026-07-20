"""Small output-safety helpers shared by CLI and workflow reporting.

Delegates to ``agent.security.redaction`` for the canonical implementation.
"""

from __future__ import annotations

from agent.security.redaction import redact_sensitive_text  # noqa: F401 — re-export
