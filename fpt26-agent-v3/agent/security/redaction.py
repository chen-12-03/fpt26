"""Safe output redaction — remove credential-shaped and endpoint strings.

Used by CLI error reporting, log output, and diagnostic messages to ensure
API keys, bearer tokens, and internal endpoints are never written to stderr,
stdout, log files, or run reports.
"""

from __future__ import annotations

import re
from typing import Any

# Patterns that match credential-shaped strings.  These are deliberately
# aggressive; false positives are acceptable (over-redaction) while false
# negatives are not (leaked credentials).

_ENDPOINT_RE = re.compile(r"https?://[^\s)\]]+")
_BEARER_RE = re.compile(
    r"\b(?:sk-|Bearer\s+)[A-Za-z0-9._~+/=-]{8,}",
    flags=re.IGNORECASE,
)
_API_KEY_PATTERNS = (
    # Environment-variable style leaks
    re.compile(r"(?:FPT26_LLM_API_KEY|OPENROUTER_API_KEY)\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"(?:api[_-]?key|apikey|secret)\s*[:=]\s*\S{8,}", re.IGNORECASE),
)


def redact_sensitive_text(value: object) -> str:
    """Return *value* as a string with credential-shaped substrings removed.

    Args:
        value: Any object; ``str(value)`` is used as the input.

    Returns:
        A redacted string safe for stderr, log files, and public reports.
    """
    text = str(value)

    # Redact full URLs (endpoints may contain tokens in path/query)
    text = _ENDPOINT_RE.sub("<redacted-endpoint>", text)

    # Redact Bearer tokens and API key prefixes
    text = _BEARER_RE.sub("<redacted-secret>", text)

    # Redact key=value style leaks
    for pattern in _API_KEY_PATTERNS:
        text = pattern.sub("<redacted-key-value>", text)

    return text


def redact_data(value: Any) -> Any:
    """Redact string values inside a JSON-like structure recursively.

    Use this for structured payloads that will later be serialised (run
    reports, checkpoints, evidence files).  The patterns in
    :func:`redact_sensitive_text` are greedy about non-whitespace characters
    — ``https?://[^\\s)\\]]+`` happily eats a trailing ``",`` — so applying
    them to *serialised* JSON destroys structural characters and yields a
    document that no longer parses.  Redacting the values first keeps the
    document well-formed: ``json.dumps`` escapes whatever the replacement
    introduces.

    Dict keys are left untouched (they are identifiers, not data).
    """
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {key: redact_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_data(item) for item in value]
    return value


def redact_and_log(text: str) -> str:
    """Convenience: redact then return the same string (for inline use)."""
    return redact_sensitive_text(text)
