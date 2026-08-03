from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent.analysis.action_contract import (
    build_bottleneck_action_contract,
    build_ii_resource_action_contract,
)
from agent.analysis.bottleneck_diagnostics import (
    LoadedSynthesisLog,
    assess_action_alignment,
    diagnose_synthesis,
    load_synthesis_log,
)
from agent.analysis.synth_diagnostics import extract_ii_resource_limits


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "bottleneck_diagnostics"
    / "observed_hls_messages.txt"
)


def _diagnose(text: str, report=None):
    return diagnose_synthesis(
        SimpleNamespace(report=report, log=text),
        LoadedSynthesisLog(text, "test_fixture", True),
    )


def test_observed_message_fixture_covers_only_evidence_backed_families():
    diagnosis = _diagnose(FIXTURE.read_text(encoding="utf-8"))
    causes = {finding.cause for finding in diagnosis.findings}
    assert causes == {
        "memory_port",
        "carried_dependency",
        "shared_resource_conflict",
        "timing_critical_path",
        "pipeline_structure",
        "variable_trip_count",
        "dataflow_noncanonical",
        "stream_depth_risk",
        "rewind_dependency",
    }
    assert diagnosis.primary.cause == "carried_dependency"
    assert diagnosis.evidence_complete is True


def test_hls_200_448_distinguishes_local_memory_from_m_axi():
    limits = extract_ii_resource_limits(FIXTURE.read_text(encoding="utf-8"))
    assert [(item.storage_kind, item.array, item.port) for item in limits] == [
        ("external_interface", None, "gmem"),
        ("local_memory", "mem", None),
    ]
    contract = build_ii_resource_action_contract(
        FIXTURE.read_text(encoding="utf-8")
    )
    assert [target["array"] for target in contract["targets"]] == ["mem"]


def test_unknown_does_not_infer_cause_from_high_latency_or_resource_ratio():
    report = SimpleNamespace(
        latency_worst=100_000,
        latency_avg=None,
        resources={"LUT": 100, "FF": 10_000, "DSP": 90},
        loop_metrics=[
            {"name": "LOOP", "pipeline_ii": 4, "latency": 99_000}
        ],
    )
    diagnosis = _diagnose("Synthesis completed without a scheduler cause", report)
    assert diagnosis.primary.cause == "unknown"
    assert diagnosis.primary.confidence == "unknown"
    assert diagnosis.diagnostic_state == "unresolved_bottleneck_cause"
    assert "direct scheduler cause" in diagnosis.primary.missing_evidence[0]


def test_success_without_bottleneck_evidence_is_distinct_from_missing_report():
    report = SimpleNamespace(
        latency_worst=100,
        latency_avg=None,
        loop_metrics=[],
        burst_accesses=[],
    )
    complete = _diagnose("Synthesis completed successfully", report)
    missing = _diagnose("Synthesis completed successfully", None)

    assert complete.primary.cause == "unknown"
    assert complete.diagnostic_state == "no_confirmed_bottleneck"
    assert missing.diagnostic_state == "insufficient_artifacts"


def test_diagnosis_contract_links_category_to_bounded_scheme():
    report = SimpleNamespace(
        latency_worst=1027,
        latency_avg=None,
        loop_metrics=[
            {
                "name": "VITIS_LOOP_7_1",
                "trip_count": 1024,
                "latency": 1025,
                "pipeline_ii": 1,
            }
        ],
        burst_accesses=[],
    )
    diagnosis = _diagnose("Synthesis completed successfully", report)
    contract = build_bottleneck_action_contract(diagnosis)

    assert contract["actionable"] is True
    assert contract["cause"] == "serial_loop_latency"
    assert contract["target"]["loop"] == "VITIS_LOOP_7_1"
    assert contract["candidate_families"] == [
        "LOOP_UNROLL",
        "SOURCE_RESTRUCTURE",
    ]
    assert "source proof" in contract["required_preconditions"][0]
    assert contract["verification"]


def test_unknown_category_contract_requests_evidence_not_an_edit():
    diagnosis = _diagnose("Synthesis completed successfully", None)
    contract = build_bottleneck_action_contract(diagnosis)

    assert contract["diagnostic_state"] == "insufficient_artifacts"
    assert contract["actionable"] is False
    assert contract["candidate_families"] == []
    assert contract["candidate_schemes"] == []
    assert "Do not propose" in contract["selection_rule"]


def test_synthesis_failure_never_receives_an_optimization_contract():
    line = next(
        line
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if "[HLS 200-448]" in line and "on array 'mem'" in line
    )
    result = SimpleNamespace(ok=False, report=None, log=line)
    diagnosis = diagnose_synthesis(
        result,
        LoadedSynthesisLog(line, "test_fixture", True),
    )
    contract = build_bottleneck_action_contract(diagnosis)

    assert diagnosis.primary.cause == "memory_port"
    assert diagnosis.diagnostic_state == "synthesis_failed"
    assert contract["actionable"] is False
    assert contract["candidate_schemes"] == []


def test_ratio_correlated_ii_one_loop_is_serial_latency_not_recurrence_claim():
    report = SimpleNamespace(
        latency_worst=1027,
        latency_avg=None,
        resources={"LUT": 156, "FF": 93, "DSP": 2},
        loop_metrics=[
            {
                "name": "VITIS_LOOP_7_1",
                "trip_count": 1024,
                "latency": 1025,
                "pipeline_ii": 1,
            }
        ],
    )
    rewind = (
        "INFO: [HLS 200-2250] Rewind delay = 1 for the pipelined loop "
        "'VITIS_LOOP_7_1' due to a write-after-read dependence on variable "
        "'result (dotProduct.cpp:6)'."
    )
    diagnosis = _diagnose(rewind, report)
    assert diagnosis.primary.cause == "serial_loop_latency"
    assert diagnosis.primary.confidence == "probable"
    assert diagnosis.primary.observations["top_latency_fraction"] > 0.99
    assert "source proof" in diagnosis.primary.missing_evidence[0]


def test_missed_burst_summary_remains_unknown_without_per_port_detail():
    text = next(
        line
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if "[HLS 200-1603]" in line
    )
    diagnosis = _diagnose(text)
    assert diagnosis.primary.cause == "unknown"
    assert "missed-burst detail" in " ".join(
        diagnosis.primary.missing_evidence
    )


def test_report_burst_details_classify_observed_failure_families():
    report = SimpleNamespace(
        burst_accesses=[
            {
                "hw_interface": "m_axi_gmem",
                "variable": "a",
                "access_location": "example.cpp:40:5",
                "direction": "read",
                "burst_status": "Widen Fail",
                "loop": "read_loop",
                "loop_location": "example.cpp:40:5",
                "resolution": "214-353",
                "problem": "Could not widen due to the max_widen_bitwidth threshold of 0",
            },
            {
                "hw_interface": "m_axi_gmem",
                "variable": "b",
                "direction": "read",
                "burst_status": "Fail",
                "resolution": "214-232",
                "problem": "Access call is in the conditional branch",
            },
            {
                "hw_interface": "m_axi_gmem",
                "variable": "c",
                "direction": "read",
                "burst_status": "Widen Fail",
                "resolution": "214-307",
                "problem": "Could not widen since type i32 size is greater than or equal to alignment 1(bytes)",
            },
            {
                "hw_interface": "m_axi_gmem",
                "variable": "d",
                "direction": "write",
                "burst_status": "Fail",
                "resolution": "",
                "problem": "Inferred burst reverted due to burst accesses data width is different from m_axi port width",
            },
            {
                "hw_interface": "m_axi_gmem",
                "variable": "e",
                "direction": "write",
                "burst_status": "Fail",
                "resolution": "214-224",
                "problem": "Could not burst due to multiple potential writes to the same bundle in the same region.",
            },
        ]
    )
    diagnosis = _diagnose(
        "INFO: [HLS 200-1603] Design has inferred MAXI bursts and missed bursts",
        report,
    )

    assert {finding.cause for finding in diagnosis.findings} == {
        "m_axi_widening_limit",
        "m_axi_conditional_access",
        "m_axi_alignment_limit",
        "m_axi_width_mismatch",
        "m_axi_bundle_write_conflict",
    }
    assert diagnosis.primary.cause == "m_axi_widening_limit"
    assert diagnosis.primary.confidence == "confirmed"
    assert diagnosis.primary.target["interface"] == "m_axi_gmem"
    assert "measured latency" in diagnosis.primary.missing_evidence[0]


def test_unexplained_report_burst_failure_remains_unknown():
    report = SimpleNamespace(
        burst_accesses=[
            {
                "hw_interface": "m_axi_gmem",
                "burst_status": "Fail",
                "resolution": "",
                "problem": "",
            }
        ]
    )
    diagnosis = _diagnose(
        "INFO: [HLS 200-1603] Design has inferred MAXI bursts and missed bursts",
        report,
    )

    assert diagnosis.primary.cause == "unknown"


def test_complete_artifact_log_wins_over_truncated_tool_excerpt(tmp_path):
    artifact = tmp_path / "synth_1"
    log_dir = artifact / "logs"
    log_dir.mkdir(parents=True)
    full_line = next(
        line
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if "[HLS 200-880]" in line
    )
    (log_dir / "hls_run_tcl.log").write_text(full_line, encoding="utf-8")
    result = SimpleNamespace(
        report=None,
        log="truncated excerpt without diagnostic",
        _artifact_dir=str(artifact),
    )
    loaded = load_synthesis_log(result)
    diagnosis = diagnose_synthesis(result, loaded)
    assert loaded.source == "full_hls_run_tcl_log"
    assert loaded.complete is True
    assert diagnosis.primary.cause == "carried_dependency"


def test_action_alignment_is_auditable_and_does_not_upgrade_unknown():
    local_line = next(
        line
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if "[HLS 200-448]" in line and "on array 'mem'" in line
    )
    diagnosis = _diagnose(local_line)
    aligned = assess_action_alignment(
        diagnosis,
        {
            "families": ["MEMORY_BANKING"],
            "targets": {"arrays": ["mem"], "loops": [], "functions": []},
            "source_changed": False,
        },
    )
    contradicted = assess_action_alignment(
        diagnosis,
        {
            "families": ["PIPELINE"],
            "targets": {"arrays": [], "loops": ["OTHER"], "functions": []},
            "source_changed": False,
        },
    )
    unknown = assess_action_alignment(
        _diagnose("no supported messages"),
        {
            "families": ["PIPELINE"],
            "targets": {"arrays": [], "loops": ["LOOP"], "functions": []},
            "source_changed": False,
        },
    )
    assert aligned["status"] == "aligned"
    assert contradicted["status"] == "contradicted"
    assert unknown["status"] == "unknown"


def test_prompt_projection_is_bounded_but_full_report_retains_findings():
    diagnosis = _diagnose(FIXTURE.read_text(encoding="utf-8"))
    assert len(diagnosis.to_dict()["findings"]) > 4
    assert len(diagnosis.to_prompt_dict()["findings"]) == 4
    assert diagnosis.to_prompt_dict()["prompt_findings_truncated"] is True


def test_observed_message_variants_are_preserved_without_invented_locations():
    text = "\n".join(
        [
            "WARNING: [SCHED 204-65] Unable to satisfy pipeline directive for function 'krnl_vadd': contains subloop(s) that are not unrolled.",
            "WARNING: [HLS 200-805] An internal stream 'cmd' with default size can result in deadlock. Please consider resizing the stream using the directive 'set_directive_stream' or the 'HLS stream' pragma.",
            "INFO: [HLS 200-2250] Rewind delay = 1 for the pipelined loop 'READ' due to a read-after-write dependence on variable 'i (dut.cpp:26)'.",
            "INFO: [HLS 200-2250] Rewind delay = 1 for the pipelined loop 'RESET' to synchronize the writting of port 'reset_value (no source info)' with ap_done.",
        ]
    )
    diagnosis = _diagnose(text)
    by_cause = {finding.cause: finding for finding in diagnosis.findings}
    assert by_cause["pipeline_structure"].target == {"function": "krnl_vadd"}
    assert by_cause["stream_depth_risk"].target == {
        "stream": "cmd",
        "source": None,
    }
    assert by_cause["rewind_dependency"].observations["dependence_kind"] == (
        "read-after-write"
    )
    assert by_cause["rewind_synchronization"].target["port"].startswith(
        "reset_value"
    )
