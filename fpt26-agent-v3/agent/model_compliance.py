"""Auditable open-weight model identity evidence for competition runs."""

from __future__ import annotations

from typing import Any


_PROVEN_MODELS: dict[str, dict[str, Any]] = {
    "qwen3-coder-plus": {
        "open_weight_model": "Qwen/Qwen3-Coder-480B-A35B-Instruct",
        "license": "Apache-2.0",
        "evidence": [
            "Qwen official Qwen3-Coder blog maps the API alias "
            "qwen3-coder-plus to Qwen3-Coder-480B-A35B-Instruct",
            "Official Qwen Hugging Face model card declares apache-2.0",
        ],
    },
    "qwen/qwen-2.5-coder-32b-instruct": {
        "open_weight_model": "Qwen/Qwen2.5-Coder-32B-Instruct",
        "license": "Apache-2.0",
        "evidence": [
            "OpenRouter lists qwen/qwen-2.5-coder-32b-instruct with "
            "model weights for Qwen2.5-Coder-32B-Instruct",
            "Official Qwen Hugging Face model card declares apache-2.0",
        ],
    },
}


def model_compliance_evidence(
    model: str | None,
    *,
    explicit_open_source: bool = False,
    license_evidence: str | None = None,
    source_evidence: str | None = None,
) -> dict[str, Any]:
    """Return proven evidence or an explicit unproven result; never infer."""

    normalized = (model or "").strip().lower()
    registered = _PROVEN_MODELS.get(normalized)
    if registered is not None:
        return {
            "model": model,
            "open_source_claimed": True,
            "compliance_proven": True,
            "compliance_status": "proven",
            **registered,
            "evidence_source": "built_in_audited_registry",
        }

    explicit_proven = bool(
        model
        and explicit_open_source
        and license_evidence
        and source_evidence
    )
    return {
        "model": model,
        "open_source_claimed": explicit_open_source,
        "license": license_evidence,
        "source_evidence": source_evidence,
        "compliance_proven": explicit_proven,
        "compliance_status": "proven" if explicit_proven else "unproven",
        "evidence_source": (
            "explicit_environment_evidence"
            if explicit_proven
            else None
        ),
    }
