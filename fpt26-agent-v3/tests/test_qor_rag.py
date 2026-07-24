from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.agents.optimization.controller import (
    _prefer_legacy_specialist,
    _task_preflight_vitis_version,
    run_optimization_loop,
)
from agent.knowledge import (
    MAX_KNOWLEDGE_PROMPT_TOKENS,
    KnowledgeEntry,
    KnowledgeQuery,
    KnowledgeValidationError,
    format_for_prompt,
    load_knowledge_entries,
    prompt_token_upper_bound,
    retrieve_knowledge,
)
from agent.qor_rag_retrieval_eval import evaluate_labels
from agent.qor_rag_curate import curate_submission_report, write_case_file
from agent.qor_rag_ab import compare_runs
from agent.pipeline.submission import run_submission


def _query(**overrides) -> KnowledgeQuery:
    values = {
        "source_metadata": {
            "loops": [{"trip_count": 128, "pipeline_ii": 1}],
            "arrays": [{"name": "a", "rank": 1}],
        },
        "baseline_qor": {
            "latency_worst": 130,
            "clock_period_ns": 5.0,
            "q_hw": 0.75,
        },
        "synth_diagnostics": {
            "summary": "Long II=1 loop is trip-count dominated."
        },
        "resource_headroom": {"LUT": 0.9, "FF": 0.9, "DSP": 0.9},
        "history": [],
        "description": "Optimize a correct vector loop.",
    }
    values.update(overrides)
    return KnowledgeQuery(**values)


def _case_entry(kind: str) -> KnowledgeEntry:
    if kind == "verified_case":
        return KnowledgeEntry.from_dict(
            {
                "id": "submission.good.unroll2",
                "kind": "verified_case",
                "family": "unroll",
                "preconditions": ["A bounded II=1 loop dominates latency."],
                "action": "UNROLL factor=2 on the measured loop.",
                "expected_signal": "Q_HW improves.",
                "contraindications": ["Do not increase a rejected factor."],
                "source": "submission:public_run/task_a",
                "confidence": "high",
                "vitis_version": "2025.2",
                "status": "verified_case",
                "tags": ["unroll", "ii_1", "loop"],
                "evidence": {
                    "interface_ok": True,
                    "csim_ok": True,
                    "synth_ok": True,
                    "frequency_ok": True,
                    "resource_ok": True,
                    "cosim_required": False,
                    "q_hw_before": 0.75,
                    "q_hw_after": 0.77,
                },
            }
        )
    return KnowledgeEntry.from_dict(
        {
            "id": "submission.bad.unroll8",
            "kind": "failure_case",
            "family": "unroll",
            "preconditions": ["A large factor was attempted."],
            "action": "Avoid repeating UNROLL factor=8.",
            "expected_signal": "The repeated synthesis failure is avoided.",
            "contraindications": ["Do not treat this as a successful case."],
            "source": "submission:public_run/task_b",
            "confidence": "high",
            "vitis_version": "2025.2",
            "status": "verified_failure",
            "tags": ["unroll", "factor_8", "failure"],
            "evidence": {
                "observed_failure": True,
                "stage": "synth",
                "failure_category": "resource_capacity",
            },
        }
    )


def test_seed_schema_and_status_are_auditable() -> None:
    entries = load_knowledge_entries()
    rules = [entry for entry in entries if entry.kind == "rule"]

    assert len(entries) >= 12
    assert len(rules) >= 12
    assert all(entry.status == "unverified_seed" for entry in rules)
    assert all(entry.source.startswith("third_party/hls-generator/") for entry in rules)
    assert {
        "pipeline",
        "unroll",
        "array_partition",
        "array_reshape",
        "reduction",
        "gemm",
        "stencil",
        "dataflow",
        "report_driven",
    } <= {entry.family for entry in rules}


def test_default_measured_cases_fill_success_and_failure_slots() -> None:
    matches = retrieve_knowledge(
        _query(
            history=[{"action": "UNROLL factor=4", "status": "REJECTED"}],
            description="Optimize a correct dot product reduction.",
            target_part="xcu55c-fsvh2892-2L-e",
            vitis_version="2025.2",
        )
    )

    assert {entry.kind for entry in matches} == {
        "rule",
        "verified_case",
        "failure_case",
    }
    assert any(entry.id == "submission.dotProduct_optimize.r1.2a7e144732e0" for entry in matches)
    assert any(
        entry.id == "submission.dotProduct_optimize.r2.negative.fa93b6af6eb0"
        for entry in matches
    )


def test_measured_case_requires_compatible_target_part() -> None:
    matches = retrieve_knowledge(
        _query(
            description="Optimize a correct dot product reduction.",
            target_part="xcvu9p-flga2104-2-i",
            vitis_version="2025.2",
        )
    )

    assert all(entry.kind == "rule" for entry in matches)


def test_dot_product_case_is_not_injected_into_unrelated_ii_loop() -> None:
    matches = retrieve_knowledge(
        _query(
            description="Optimize an AES encryption round loop.",
            target_part="xcu55c-fsvh2892-2L-e",
            vitis_version="2025.2",
        )
    )

    assert all(entry.kind == "rule" for entry in matches)


def test_popcount_cases_are_structure_limited() -> None:
    compatible = retrieve_knowledge(
        _query(
            description="Optimize a correct 256-bit popcount reduction.",
            target_part="xcu55c-fsvh2892-2L-e",
            vitis_version="2025.2",
        )
    )
    unrelated = retrieve_knowledge(
        _query(
            description="Optimize an AES encryption round loop.",
            target_part="xcu55c-fsvh2892-2L-e",
            vitis_version="2025.2",
        )
    )

    assert {entry.kind for entry in compatible} == {
        "rule",
        "verified_case",
        "failure_case",
    }
    assert any("popcount" in entry.tags for entry in compatible)
    assert all("popcount" not in entry.tags for entry in unrelated)


def test_legacy_specialist_is_incremental_fallback_not_dot_override() -> None:
    reduction = [{"family": "Reduction / Single-Loop Pipeline"}]
    cordic = [{"family": "CORDIC / Trigonometric Optimization"}]

    assert _prefer_legacy_specialist(reduction, "Compute a popcount reduction.")
    assert not _prefer_legacy_specialist(
        reduction, "Optimize a vector loop."
    )
    assert not _prefer_legacy_specialist(
        reduction, "Compute a dot product reduction."
    )
    assert _prefer_legacy_specialist(
        cordic, "Compute sine and cosine using CORDIC."
    )
    assert not _prefer_legacy_specialist(
        cordic, "A cipher contains a bit rotation."
    )


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Optimize blocked GEMM matrix multiplication.", "hlsgen.gemm.tiled_reuse"),
        ("Optimize a 2D stencil neighborhood window.", "hlsgen.stencil.line_buffer"),
    ],
)
def test_explicit_architecture_outranks_generic_ii_triage(
    description: str, expected: str
) -> None:
    matches = retrieve_knowledge(
        _query(
            source_metadata={
                "loops": [
                    {"nesting_depth": 0, "pipeline_ii": 3},
                    {"nesting_depth": 1, "pipeline_ii": 3},
                    {"nesting_depth": 2, "pipeline_ii": 3},
                ],
                "arrays": [{"rank": 2}, {"rank": 2}],
            },
            baseline_qor={
                "latency_worst": 10_000,
                "loop_metrics": [{"pipeline_ii": 3}],
            },
            synth_diagnostics={
                "summary": "Achieved II is above target due to timing."
            },
            description=description,
        )
    )

    assert matches[0].id == expected


def test_description_only_retrieval_cannot_bypass_structured_inputs() -> None:
    query = KnowledgeQuery(
        source_metadata=None,  # type: ignore[arg-type]
        baseline_qor=None,  # type: ignore[arg-type]
        synth_diagnostics=None,
        resource_headroom=None,  # type: ignore[arg-type]
        history=None,  # type: ignore[arg-type]
        description="matrix multiply",
    )

    with pytest.raises(KnowledgeValidationError, match="structured retrieval"):
        retrieve_knowledge(query)


def test_top3_has_at_most_one_entry_per_role_and_is_deterministic() -> None:
    entries = (*load_knowledge_entries(), _case_entry("verified_case"), _case_entry("failure_case"))
    query = _query(
        history=[
            {
                "status": "REJECTED_BY_SYNTH_RESOURCE",
                "action": "UNROLL factor=8",
            }
        ],
        vitis_version="2025.2",
    )

    first = retrieve_knowledge(query, entries=entries)
    second = retrieve_knowledge(query, entries=entries)

    assert [entry.id for entry in first] == [entry.id for entry in second]
    assert len(first) <= 3
    assert len({entry.kind for entry in first}) == len(first)
    assert {entry.kind for entry in first} == {
        "rule",
        "verified_case",
        "failure_case",
    }


def test_verified_case_requires_all_public_validation_gates() -> None:
    raw = {
        "id": "submission.invalid",
        "kind": "verified_case",
        "family": "pipeline",
        "preconditions": ["Measured loop."],
        "action": "PIPELINE II=1.",
        "expected_signal": "Q_HW improves.",
        "contraindications": ["Do not guess."],
        "source": "submission:public/task",
        "confidence": "high",
        "vitis_version": "2025.2",
        "status": "verified_case",
        "evidence": {
            "interface_ok": True,
            "csim_ok": True,
            "synth_ok": True,
            "frequency_ok": True,
            "resource_ok": True,
            "cosim_required": True,
            "cosim_ok": False,
            "q_hw_before": 0.75,
            "q_hw_after": 0.76,
        },
    }

    with pytest.raises(KnowledgeValidationError, match="cosim_ok"):
        KnowledgeEntry.from_dict(raw)


def test_qhw_failure_case_requires_public_validation_gates() -> None:
    raw = {
        "id": "submission.invalid_negative",
        "kind": "failure_case",
        "family": "unroll",
        "preconditions": ["Measured loop."],
        "action": "Avoid measured action.",
        "expected_signal": "Q_HW does not regress.",
        "contraindications": ["Do not generalize."],
        "source": "submission:public/task",
        "confidence": "high",
        "vitis_version": "2025.2",
        "status": "verified_failure",
        "evidence": {
            "observed_failure": True,
            "stage": "q_hw_selection",
            "q_hw_before": 0.75,
            "q_hw_after": 0.74,
        },
    }

    with pytest.raises(KnowledgeValidationError, match="frequency_ok"):
        KnowledgeEntry.from_dict(raw)


@pytest.mark.parametrize("component", ["hidden", "reference", "evaluator"])
def test_runtime_case_path_rejects_private_components(
    tmp_path: Path, component: str
) -> None:
    path = tmp_path / component / "cases.json"

    with pytest.raises(KnowledgeValidationError, match="forbidden component"):
        load_knowledge_entries(case_paths=[path])


def test_prompt_injection_is_bounded_and_marks_seed_as_advisory() -> None:
    matches = retrieve_knowledge(_query())
    prompt = format_for_prompt(matches)
    payload = json.loads(prompt)

    assert prompt_token_upper_bound(prompt) <= MAX_KNOWLEDGE_PROMPT_TOKENS
    assert payload["entries"][0]["status"] == "unverified_seed"
    assert any("advisory" in line for line in payload["policy"])


def test_report_loop_metrics_override_missing_source_ii_for_retrieval() -> None:
    query = _query(
        source_metadata={
            "loops": [{"trip_count": "unknown", "pipeline_ii": "none"}],
            "arrays": [{"name": "a", "rank": 1}],
        },
        baseline_qor={
            "latency_worst": 1_027,
            "loop_metrics": [
                {"trip_count": 1_024, "pipeline_ii": 1, "latency": 1_025}
            ],
        },
        synth_diagnostics={
            "summary": "Long loop is II=1 and trip-count dominated."
        },
        description="Optimize a correct dot product loop.",
    )

    matches = retrieve_knowledge(query)

    assert matches[0].id == "hlsgen.unroll.conservative_partial"


def test_labeled_retrieval_gate_has_30_cases_and_recall_at_least_85_percent() -> None:
    labels = (
        Path(__file__).parents[1]
        / "evals"
        / "qor_rag_retrieval_labels.json"
    )

    result = evaluate_labels(labels)

    assert result["case_count"] >= 30
    assert result["recall_at_3"] >= 0.85
    assert result["deterministic"] is True
    assert result["max_prompt_token_upper_bound"] <= 1_800
    assert result["passed"] is True


def test_optimizer_uses_structured_qor_rag_without_an_extra_llm_call() -> None:
    starter = (
        "void top(int a[128]) {\n"
        "  for (int i = 0; i < 128; ++i) {\n"
        "    #pragma HLS PIPELINE II=1\n"
        "    a[i] += 1;\n"
        "  }\n"
        "}\n"
    )
    report = SimpleNamespace(
        latency_worst=130,
        latency_avg=130,
        interval_max=129,
        clock_period_ns=5.0,
        resources={
            "LUT": 100,
            "FF": 100,
            "DSP": 0,
            "BRAM_18K": 0,
            "URAM": 0,
        },
        available={
            "LUT": 100_000,
            "FF": 200_000,
            "DSP": 1_000,
            "BRAM_18K": 1_000,
            "URAM": 100,
        },
        loop_metrics=[
            {
                "name": "VITIS_LOOP_2_1",
                "trip_count": 128,
                "latency": 128,
                "pipeline_ii": 1,
            }
        ],
        pipeline_type="loop",
    )

    class Llm:
        def __init__(self) -> None:
            self.calls = 0
            self.prompt = ""

        def complete(self, system: str, prompt: str) -> str:
            self.calls += 1
            self.prompt = prompt
            return starter

    llm = Llm()
    state = SimpleNamespace(
        task=SimpleNamespace(
            id="qor_rag_probe",
            description="Optimize a correct long vector loop.",
            top="top",
            part="xcu55c-fsvh2892-2L-e",
            requires_cosim=False,
            clock_ns=5.0,
            budget=40,
            difficulty=1,
            type="optimize",
            headers={},
            kernel_name="top.cpp",
        ),
        server=SimpleNamespace(),
        kernel=starter,
        best_latency=130,
        results=[
            SimpleNamespace(
                kind="synth",
                ok=True,
                report=report,
                log="",
            )
        ],
        metadata={"task_preflight": {"observed_vitis_version": "2025.2"}},
        log=lambda message: None,
    )

    result = run_optimization_loop(state, llm, max_rounds=1)
    prompt = json.loads(llm.prompt)
    retrieved = json.loads(prompt["optimization_patterns"])

    assert llm.calls == 1
    assert prompt["source_design_metadata"]
    assert retrieved["entries"][0]["status"] == "unverified_seed"
    assert result.metadata["knowledge_retrievals"][0]["entry_ids"]
    assert (
        result.metadata["knowledge_retrievals"][0][
            "prompt_token_upper_bound"
        ]
        <= 1_800
    )


def test_real_preflight_vitis_version_keys_drive_runtime_query() -> None:
    assert (
        _task_preflight_vitis_version(
            SimpleNamespace(
                metadata={"task_preflight": {"observed_vitis_version": "2025.2"}}
            )
        )
        == "2025.2"
    )


def test_submission_pipeline_exposes_preflight_before_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, str] = {}

    def fake_pipeline(state, config, task, server, llm) -> None:
        observed["vitis"] = state.metadata["task_preflight"][
            "observed_vitis_version"
        ]
        state.status = "completed"
        state.metadata["finalized"] = True

    monkeypatch.setattr(
        "agent.pipeline.submission._run_pipeline",
        fake_pipeline,
    )
    state = run_submission(
        task=SimpleNamespace(
            id="preflight_probe",
            budget=10,
            top="top",
            kernel_code="int top(){return 0;}",
        ),
        config=SimpleNamespace(output_root="/tmp/preflight_probe"),
        server=SimpleNamespace(),
        llm=None,
        run_root=Path("/tmp/preflight_probe/agent"),
        total_budget=10,
        preflight_metadata={"observed_vitis_version": "2025.2"},
    )

    assert observed == {"vitis": "2025.2"}
    assert state.metadata["task_preflight"]["observed_vitis_version"] == "2025.2"


def test_qor_rag_early_stops_after_verified_improvement_with_preflight() -> None:
    starter = (
        "int top(int a[128]) {\n"
        "  int sum = 0;\n"
        "  for (int i = 0; i < 128; ++i) {\n"
        "    sum += a[i];\n"
        "  }\n"
        "  return sum;\n"
        "}\n"
    )
    candidate = starter.replace(
        "    sum += a[i];",
        "    #pragma HLS UNROLL factor=2\n    sum += a[i];",
    )
    baseline_report = SimpleNamespace(
        latency_worst=130,
        latency_avg=130,
        interval_max=129,
        clock_period_ns=5.0,
        resources={
            "LUT": 100,
            "FF": 100,
            "DSP": 0,
            "BRAM_18K": 0,
            "URAM": 0,
        },
        available={
            "LUT": 100_000,
            "FF": 200_000,
            "DSP": 1_000,
            "BRAM_18K": 1_000,
            "URAM": 100,
        },
        loop_metrics=[
            {
                "name": "VITIS_LOOP_3_1",
                "trip_count": 128,
                "latency": 128,
                "pipeline_ii": 1,
            }
        ],
        pipeline_type="loop",
    )
    improved_report = SimpleNamespace(
        latency_worst=66,
        latency_avg=66,
        interval_max=65,
        clock_period_ns=5.0,
        resources={
            "LUT": 140,
            "FF": 130,
            "DSP": 0,
            "BRAM_18K": 0,
            "URAM": 0,
        },
        available=baseline_report.available,
        loop_metrics=[
            {
                "name": "VITIS_LOOP_3_1",
                "trip_count": 64,
                "latency": 64,
                "pipeline_ii": 1,
            }
        ],
        pipeline_type="loop",
    )

    class Llm:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system: str, prompt: str) -> str:
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("verified improvement should early-stop")
            return candidate

    class Server:
        def __init__(self) -> None:
            self.csim_calls = 0
            self.synth_calls = 0

        def csim(self, kernel: str) -> SimpleNamespace:
            self.csim_calls += 1
            return SimpleNamespace(kind="csim", ok=True, report=None, log="")

        def synth(self, kernel: str) -> SimpleNamespace:
            self.synth_calls += 1
            return SimpleNamespace(
                kind="synth", ok=True, report=improved_report, log=""
            )

    llm = Llm()
    server = Server()
    state = SimpleNamespace(
        task=SimpleNamespace(
            id="qor_rag_early_stop",
            description="Optimize a correct long vector reduction.",
            top="top",
            part="xcu55c-fsvh2892-2L-e",
            requires_cosim=False,
            clock_ns=5.0,
            budget=40,
            difficulty=1,
            type="optimize",
            headers={},
            kernel_name="top.cpp",
        ),
        server=server,
        kernel=starter,
        best_latency=130,
        results=[
            SimpleNamespace(
                kind="synth", ok=True, report=baseline_report, log=""
            )
        ],
        metadata={"task_preflight": {"observed_vitis_version": "2025.2"}},
        log=lambda message: None,
    )

    result = run_optimization_loop(state, llm, max_rounds=5)

    assert result.kernel == candidate
    assert llm.calls == 1
    assert server.csim_calls == 1
    assert server.synth_calls == 1
    assert result.metadata["qor_rag_early_success_stop"]["round"] == 1
    assert (
        result.metadata["knowledge_retrievals"][0][
            "prompt_token_upper_bound"
        ]
        <= MAX_KNOWLEDGE_PROMPT_TOKENS
    )
    assert (
        _task_preflight_vitis_version(
            SimpleNamespace(
                metadata={"task_preflight": {"required_vitis_version": "2025.2"}}
            )
        )
        == "2025.2"
    )


def test_curator_promotes_only_fully_verified_public_submission_cases(
    tmp_path: Path,
) -> None:
    report_path = (
        tmp_path / "runs" / "submission" / "task_a" / "run_report.json"
    )
    report_path.parent.mkdir(parents=True)
    candidate = {
        "round": 1,
        "strategy": "sequential_default",
        "action": {
            "families": ["UNROLL"],
            "added_pragmas": ["#pragma HLS UNROLL factor=2"],
            "removed_pragmas": [],
            "source_changed": False,
        },
        "source_metadata": {
            "loop_count": 1,
            "array_count": 1,
            "loops": [{"trip_count": 128, "pipeline_ii": 1}],
        },
        "latency": 70,
        "clock_ns": 5.0,
        "resources": {"LUT": 120},
        "loop_metrics": [{"trip_count": 128, "pipeline_ii": 1}],
        "q_hw_before": 0.75,
        "q_hw_after": 0.77,
        "decision": "ACCEPTED",
        "validation": {
            "interface_ok": True,
            "csim_ok": True,
            "synth_ok": True,
            "frequency_ok": True,
            "resource_ok": True,
            "cosim_required": False,
            "cosim_ok": None,
        },
    }
    report = {
        "task_id": "task_a",
        "run_role": "submission",
        "status": "completed",
        "gates": {"public_acceptance": {"ok": True}},
        "final_artifact": {
            "fully_verified": True,
            "sha256": "a" * 64,
        },
        "target": {"part": "xcu55c-fsvh2892-2L-e"},
        "toolchain": {"preflight_vitis_version": "2025.2"},
        "optimization_metrics": {
            "synth_candidates": [
                {"round": 0, "is_baseline": True},
                candidate,
                {
                    **candidate,
                    "round": 2,
                    "q_hw_before": 0.77,
                    "q_hw_after": 0.76,
                    "decision": "REJECTED",
                },
            ]
        },
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")

    entries = curate_submission_report(report_path)
    output = tmp_path / "curated_cases.json"
    write_case_file(entries, output, replace=False)
    loaded = load_knowledge_entries(case_paths=[output])

    cases = [entry for entry in loaded if entry.kind != "rule"]
    assert [entry.kind for entry in cases] == [
        "verified_case",
        "failure_case",
    ]
    assert cases[0].status == "verified_case"
    assert cases[1].status == "verified_failure"
    assert all(entry.vitis_version == "2025.2" for entry in cases)
    assert all(entry.source.startswith("submission:task_a:") for entry in cases)


def test_curator_adds_structure_tag_from_public_task_id(
    tmp_path: Path,
) -> None:
    report_path = (
        tmp_path
        / "runs"
        / "submission"
        / "rosetta__popcount"
        / "run_report.json"
    )
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "task_id": "rosetta__popcount",
                "run_role": "submission",
                "status": "completed",
                "gates": {"public_acceptance": {"ok": True}},
                "final_artifact": {
                    "fully_verified": True,
                    "sha256": "b" * 64,
                },
                "target": {"part": "xcu55c-fsvh2892-2L-e"},
                "toolchain": {"preflight_vitis_version": "2025.2"},
                "optimization_metrics": {
                    "synth_candidates": [
                        {
                            "round": 1,
                            "action": {
                                "families": ["UNROLL"],
                                "added_pragmas": [
                                    "#pragma HLS UNROLL factor=4"
                                ],
                            },
                            "source_metadata": {
                                "loop_count": 1,
                                "array_count": 0,
                            },
                            "q_hw_before": 0.75,
                            "q_hw_after": 0.85,
                            "decision": "ACCEPTED",
                            "validation": {
                                "interface_ok": True,
                                "csim_ok": True,
                                "synth_ok": True,
                                "frequency_ok": True,
                                "resource_ok": True,
                                "cosim_required": False,
                            },
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    entries = curate_submission_report(report_path)

    assert entries[0].tags[-1] == "unroll"
    assert "popcount" in entries[0].tags


def test_curator_rejects_evaluator_report_path(tmp_path: Path) -> None:
    report = (
        tmp_path / "runs" / "evaluator" / "task_a" / "run_report.json"
    )
    report.parent.mkdir(parents=True)
    report.write_text("{}", encoding="utf-8")

    with pytest.raises(KnowledgeValidationError, match="forbidden private"):
        curate_submission_report(report)


def test_curator_accepts_only_submission_run_report_json(
    tmp_path: Path,
) -> None:
    report = tmp_path / "runs" / "submission" / "task_a" / "summary.json"
    report.parent.mkdir(parents=True)
    report.write_text("{}", encoding="utf-8")

    with pytest.raises(KnowledgeValidationError, match="run_report.json"):
        curate_submission_report(report)


def test_ab_gate_computes_fixed_set_acceptance_metrics(tmp_path: Path) -> None:
    task_ids = [f"task_{index:02d}" for index in range(12)]
    task_list = tmp_path / "tasks.txt"
    task_list.write_text("\n".join(task_ids) + "\n", encoding="utf-8")

    def write_run(root: Path, task_id: str, *, candidate: bool) -> None:
        submission = (
            root
            / "tasks"
            / task_id
            / "attempt_001"
            / "submission"
            / task_id
            / "run_report.json"
        )
        evaluator = (
            root
            / "tasks"
            / task_id
            / "attempt_001"
            / "evaluator"
            / task_id
            / "run_report.json"
        )
        submission.parent.mkdir(parents=True)
        evaluator.parent.mkdir(parents=True)
        submission.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "run_role": "submission",
                    "llm": {
                        "token_usage": {
                            "total_tokens": 105 if candidate else 100
                        }
                    },
                    "budget": {"spent": 10},
                    "optimization_metrics": {
                        "semantic_duplicate_skips": 8 if candidate else 10,
                        "semantic_current_best_skips": 0,
                        "cross_strategy_duplicate_skips": 0,
                        "strategy_contract_rejections": 0,
                        "ii_resource_intent_rejections": 0,
                        "optimization_failures": [],
                    },
                }
            ),
            encoding="utf-8",
        )
        evaluator.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "run_role": "evaluator",
                    "scoring": {
                        "valid": True,
                        "q_hw": 0.765 if candidate else 0.75,
                        "latency_ratio": 1.06 if candidate else 1.0,
                    },
                }
            ),
            encoding="utf-8",
        )

    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    for task_id in task_ids:
        write_run(baseline, task_id, candidate=False)
        write_run(candidate, task_id, candidate=True)

    result = compare_runs([baseline], [candidate], task_list)

    assert result["passed"] is True
    assert result["provenance"]["baseline_roots"] == [str(baseline)]
    assert result["provenance"]["candidate_roots"] == [str(candidate)]
    assert "later roots replace earlier reports" in result["provenance"][
        "overlay_semantics"
    ]
    assert result["comparison"]["correctness_preservation_rate"] == 1.0
    assert result["comparison"]["q_hw_geomean_relative_change"] >= 0.01
    assert result["comparison"]["acceleration_geomean_relative_change"] >= 0.05
    assert result["comparison"]["wasted_attempts_relative_change"] <= -0.20
    assert result["comparison"]["mean_tokens_relative_change"] <= 0.10


def test_ab_later_root_overlays_paired_retry(tmp_path: Path) -> None:
    task_ids = [f"task_{index:02d}" for index in range(12)]
    task_list = tmp_path / "tasks.txt"
    task_list.write_text("\n".join(task_ids) + "\n", encoding="utf-8")

    def write_pair(root: Path, task_id: str, q_hw: float) -> None:
        for role in ("submission", "evaluator"):
            path = root / role / task_id / "run_report.json"
            path.parent.mkdir(parents=True)
            payload = {
                "task_id": task_id,
                "run_role": role,
            }
            if role == "submission":
                payload.update(
                    {
                        "llm": {"token_usage": {"total_tokens": 100}},
                        "budget": {"spent": 10},
                        "optimization_metrics": {},
                    }
                )
            else:
                payload["scoring"] = {
                    "valid": True,
                    "q_hw": q_hw,
                    "latency_ratio": q_hw / 0.75,
                }
            path.write_text(json.dumps(payload), encoding="utf-8")

    full = tmp_path / "full"
    retry = tmp_path / "retry"
    for task_id in task_ids:
        write_pair(full, task_id, 0.75)
    write_pair(retry, task_ids[0], 0.90)

    result = compare_runs(
        [full],
        [full, retry],
        task_list,
    )

    assert result["candidate"]["tasks"][task_ids[0]]["q_hw"] == 0.90
    assert result["candidate"]["tasks"][task_ids[0]][
        "evaluator_report"
    ].startswith(str(retry))
    assert result["candidate"]["tasks"][task_ids[1]][
        "evaluator_report"
    ].startswith(str(full))
