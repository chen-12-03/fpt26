"""Safe output redaction — remove credential-shaped and endpoint strings.

Used by CLI error reporting, log output, and diagnostic messages to ensure
API keys, bearer tokens, and internal endpoints are never written to stderr,
stdout, log files, or run reports.
"""

from __future__ import annotations

import re

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


def redact_and_log(text: str) -> str:
    """Convenience: redact then return the same string (for inline use)."""
    return redact_sensitive_text(text)
