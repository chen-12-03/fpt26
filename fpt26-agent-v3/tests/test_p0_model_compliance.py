from agent.model_compliance import model_compliance_evidence


def test_known_qwen_api_alias_has_audited_open_weight_evidence() -> None:
    evidence = model_compliance_evidence("qwen3-coder-plus")

    assert evidence["compliance_proven"] is True
    assert evidence["license"] == "Apache-2.0"
    assert (
        evidence["open_weight_model"]
        == "Qwen/Qwen3-Coder-480B-A35B-Instruct"
    )


def test_openrouter_default_qwen_coder_has_audited_open_weight_evidence() -> None:
    evidence = model_compliance_evidence("qwen/qwen-2.5-coder-32b-instruct")

    assert evidence["compliance_proven"] is True
    assert evidence["license"] == "Apache-2.0"
    assert (
        evidence["open_weight_model"]
        == "Qwen/Qwen2.5-Coder-32B-Instruct"
    )


def test_unknown_model_is_not_claimed_compliant_without_full_evidence() -> None:
    evidence = model_compliance_evidence("unknown-provider-model")

    assert evidence["compliance_proven"] is False
    assert evidence["compliance_status"] == "unproven"


def test_unknown_model_requires_explicit_license_and_source_evidence() -> None:
    evidence = model_compliance_evidence(
        "self-hosted-open-model",
        explicit_open_source=True,
        license_evidence="Apache-2.0",
        source_evidence="organization/model-checkpoint",
    )

    assert evidence["compliance_proven"] is True
    assert evidence["evidence_source"] == "explicit_environment_evidence"
