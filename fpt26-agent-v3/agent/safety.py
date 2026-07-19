"""Small output-safety helpers shared by CLI and workflow reporting."""

from __future__ import annotations

import re


def redact_sensitive_text(value: object) -> str:
    """Redact API endpoint and credential-shaped strings from diagnostics."""

    text = str(value)
    text = re.sub(r"https?://\S+", "<redacted-endpoint>", text)
    text = re.sub(
        r"\b(?:sk-|Bearer\s+)[A-Za-z0-9._~+/=-]{8,}",
        "<redacted-secret>",
        text,
        flags=re.IGNORECASE,
    )
    return text
