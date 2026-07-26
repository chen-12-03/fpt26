from __future__ import annotations

import json
from pathlib import Path

from agent.knowledge import KnowledgeEntry
from tools.offline_agent_triage import (
    analyze_full199_failures,
    analyze_phase2f_objective_status,
    analyze_post_quarantine_failures,
    analyze_qor_rag_ab,
)


def _write_task(
    root: Path,
    task_id: str,
    *,
    top: str = "dotProduct",
    kernel: str | None = None,
    public_tb: str | None = None,
    description: str = "Optimize a dot product reduction.",
) -> None:
    task_dir = root / "generated" / task_id
    task_dir.mkdir(parents=True)
    (task_dir / "task.toml").write_text(
        f'''
task_id = "{task_id}"
task_type = "optimize"
difficulty = 3
top = "{top}"
kernel_file = "kernel.cpp"
header_files = ["kernel.h"]
public_tb = "kernel_tb.cpp"
budget = 60
initial_condition = "Functionally correct public kernel."

[target]
part = "xcu55c-fsvh2892-2L-e"
clock_ns = 5.0

[provenance]
source = "unit"
source_path = "public/examples/{task_id}"
public_only = true
hidden_imported = false
reference_imported = false
generated_testbench = true
'''.lstrip(),
        encoding="utf-8",
    )
    (task_dir / "description.md").write_text(description, encoding="utf-8")
    (task_dir / "kernel.h").write_text(
        f"void {top}(int a[64], int b[64], int *out);\n",
        encoding="utf-8",
    )
    (task_dir / "kernel.cpp").write_text(
        kernel
        or f"""
void {top}(int a[64], int b[64], int *out) {{
  int acc = 0;
  loop_i: for (int i = 0; i < 64; ++i) {{
    acc += a[i] * b[i];
  }}
  *out = acc;
}}
""".lstrip(),
        encoding="utf-8",
    )
    (task_dir / "kernel_tb.cpp").write_text(
        public_tb
        or f"""
#include <iostream>
void {top}(int a[64], int b[64], int *out);
int main() {{
  int a[64] = {{0}};
  int b[64] = {{0}};
  int out = 0;
  {top}(a, b, &out);
  std::cout << "PASS\\n";
  return 0;
}}
""".lstrip(),
        encoding="utf-8",
    )


def _exact_source_case() -> KnowledgeEntry:
    return KnowledgeEntry.from_dict(
        {
            "id": "submission.dotProduct_optimize.unit",
            "kind": "verified_case",
            "family": "unroll",
            "preconditions": ["A bounded II=1 loop dominates latency."],
            "action": "UNROLL factor=2 on the measured loop.",
            "expected_signal": "Q_HW improves.",
            "contraindications": ["Do not use as a task-specific answer."],
            "source": "submission:dotProduct_optimize:unit",
            "confidence": "high",
            "vitis_version": "2025.2",
            "status": "verified_case",
            "tags": ["measured"],
            "evidence": {
                "target_part": "xcu55c-fsvh2892-2L-e",
                "interface_ok": True,
                "csim_ok": True,
                "synth_ok": True,
                "frequency_ok": True,
                "resource_ok": True,
                "cosim_required": False,
                "q_hw_before": 0.75,
                "q_hw_after": 0.80,
            },
        }
    )


def test_qor_triage_replays_default_and_generalized_retrieval(tmp_path: Path) -> None:
    _write_task(tmp_path, "dotProduct_optimize")
    report = {
        "baseline": {
            "tasks": {
                "dotProduct_optimize": {
                    "q_hw": 0.80,
                    "acceleration": 2.0,
                    "tokens": 10_000,
                    "credits": 15,
                    "wasted_attempts": 1,
                }
            }
        },
        "candidate": {
            "tasks": {
                "dotProduct_optimize": {
                    "q_hw": 0.75,
                    "acceleration": 1.0,
                    "tokens": 4_000,
                    "credits": 10,
                    "wasted_attempts": 0,
                }
            }
        },
    }

    result = analyze_qor_rag_ab(
        report,
        task_root=tmp_path,
        entries=[_exact_source_case()],
    )

    replay = result["largest_regressions"][0]["offline_retrieval_replay"]
    assert replay["available"] is True
    assert replay["modes"]["default"]["exact_source_measured_case_count"] == 1
    assert replay["modes"]["generalized"]["exact_source_measured_case_count"] == 0
    assert "low_token_conservative_behavior" in replay["hypothesis_evidence"]["signals"]


def test_full199_triage_static_audits_public_amd_anchor_tasks(tmp_path: Path) -> None:
    task_id = "amd_accel__unit_anchor"
    _write_task(
        tmp_path,
        task_id,
        top="krnl_vadd",
        description="Optimize a public AMD HLS kernel.",
    )
    report = {
        "coverage": {"expected_task_count": 1},
        "tasks": {
            task_id: {
                "official_task": False,
                "outcome": "failed",
                "evaluator": {"stop_reason": "anchor_invalid: starter"},
            }
        },
    }

    result = analyze_full199_failures(report, task_root=tmp_path)

    audit = result["priority_static_audits"][0]
    assert audit["available"] is True
    assert audit["top_in_kernel"] is True
    assert audit["public_tb_calls_top"] is True
    assert audit["generated_public_tb"] is True
    assert "generated_public_tb_has_no_observable_result_check" in audit["issues"]


def test_full199_triage_correlates_public_hls_metric_incomplete_manifest(
    tmp_path: Path,
) -> None:
    task_id = "amd_accel__metric_missing"
    _write_task(
        tmp_path,
        task_id,
        top="krnl_vadd",
        kernel="""
void krnl_vadd(int *a, int n) {
  for (int i = 0; i < n; ++i) {
    a[i] = i;
  }
}
""".lstrip(),
    )
    manifest = {
        "validated_count": 1,
        "validated": [
            {
                "task_id": task_id,
                "source": "amd_accel",
                "csim_ok": True,
                "synth_ok": True,
                "latency_worst": None,
            }
        ],
    }
    (tmp_path / "generated" / "public_hls_validated_tasks_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    report = {
        "coverage": {"expected_task_count": 1},
        "tasks": {
            task_id: {
                "official_task": False,
                "outcome": "failed",
                "evaluator": {"stop_reason": "anchor_invalid: starter"},
            }
        },
    }

    result = analyze_full199_failures(report, task_root=tmp_path)

    completeness = result["public_hls_metric_completeness"]
    assert completeness["available"] is True
    assert completeness["metric_incomplete_count"] == 1
    assert completeness["anchor_invalid_overlap_count"] == 1
    assert completeness["anchor_invalid_overlap_task_ids"] == [task_id]
    assert completeness["tripcount_patch_candidate_count"] == 1
    assert completeness["suggested_tripcount_small_sample_tasks"] == [task_id]


def test_post_quarantine_triage_preserves_gate_evidence() -> None:
    report = {
        "tasks": {
            "amd_accel__metric_missing": {
                "official_task": False,
                "outcome": "failed",
                "evaluator": {"stop_reason": "anchor_invalid: starter"},
            },
            "c2hlsc__des": {
                "official_task": False,
                "outcome": "failed",
                "submission": {
                    "status": "failed",
                    "stop_reason": "interface_failed",
                    "gates": {
                        "interface": {
                            "ok": False,
                            "reason": "markdown_fence_in_candidate",
                            "stage": "optimize_candidate_1",
                        },
                        "frequency_100mhz": {"ok": True, "reason": "passed"},
                    },
                    "token_usage": {
                        "complete": True,
                        "request_count": 1,
                        "total_tokens": 1234,
                    },
                },
            },
            "pp4fpga__parallel_merge_sort": {
                "official_task": False,
                "outcome": "failed",
                "submission": {
                    "status": "failed",
                    "stop_reason": "frequency_failed",
                    "gates": {
                        "frequency_100mhz": {
                            "ok": False,
                            "reason": "below_minimum_frequency",
                            "candidate_clock_ns": 10.607,
                            "frequency_mhz": 94.28,
                            "minimum_frequency_mhz": 100.0,
                        },
                        "resource_capacity": {
                            "ok": True,
                            "reason": "passed",
                            "resources": {"LUT": 42},
                        },
                    },
                    "final_hardware": {
                        "clock_period_ns": 10.607,
                        "frequency_mhz": 94.28,
                        "resources": {"LUT": 42},
                    },
                },
            },
            "chstone__df_extractFloat64Exp": {
                "official_task": False,
                "outcome": "failed",
                "submission": {
                    "status": "failed",
                    "stop_reason": "frequency_failed",
                    "gates": {
                        "frequency_100mhz": {
                            "ok": False,
                            "reason": "candidate_clock_invalid",
                            "candidate_clock_ns": 0.0,
                            "frequency_mhz": None,
                            "minimum_frequency_mhz": 100.0,
                        }
                    },
                    "final_hardware": {
                        "clock_period_ns": 0.0,
                        "frequency_mhz": None,
                        "resources": {"LUT": 0},
                    },
                },
            },
            "machsuite__bfs_bulk": {
                "official_task": False,
                "outcome": "failed",
                "evaluator": {
                    "status": "failed",
                    "stop_reason": "anchor_invalid: starter",
                    "grading": {
                        "source": "hidden",
                        "hidden_available": True,
                        "is_fallback": False,
                    },
                    "gates": {
                        "evaluator_acceptance": {
                            "ok": False,
                            "failures": ["anchor_invalid: starter"],
                            "anchor_source": "starter",
                            "anchor_valid": False,
                            "grading_source": "hidden",
                            "hidden_available": True,
                        }
                    },
                },
            },
            "polybench__gemm": {
                "official_task": False,
                "outcome": "completed",
            },
        }
    }
    quarantine = {"exclude_task_ids": ["amd_accel__metric_missing"]}

    result = analyze_post_quarantine_failures(report, quarantine)

    assert result["excluded_task_count"] == 1
    assert result["excluded_failed_task_count"] == 1
    assert result["remaining_task_count"] == 5
    assert result["completed_count"] == 1
    assert result["remaining_failure_count"] == 4
    assert result["failure_reason_counts"] == {
        "anchor_invalid: starter": 1,
        "frequency_failed": 2,
        "interface_failed": 1,
    }

    c2hlsc = next(
        item
        for item in result["remaining_failures"]
        if item["task_id"] == "c2hlsc__des"
    )
    assert (
        c2hlsc["gate_evidence"]["submission"]["interface"]["reason"]
        == "markdown_fence_in_candidate"
    )
    assert c2hlsc["gate_evidence"]["submission"]["token_usage"]["total_tokens"] == 1234

    assert result["suggested_small_sample_tasks"] == [
        "c2hlsc__des",
        "pp4fpga__parallel_merge_sort",
        "chstone__df_extractFloat64Exp",
    ]
    anchor = next(
        item
        for item in result["remaining_failures"]
        if item["task_id"] == "machsuite__bfs_bulk"
    )
    assert (
        anchor["gate_evidence"]["evaluator"]["evaluator_acceptance"][
            "anchor_valid"
        ]
        is False
    )


def test_phase2f_objective_status_tracks_offline_ready_and_open_evidence() -> None:
    qor_analysis = {
        "largest_regressions": [
            {
                "task_id": "machsuite__aes_aes",
                "q_hw_delta": -0.2,
                "acceleration_delta": -5.0,
                "hypotheses": ["missed_strategy_lane"],
                "offline_retrieval_replay": {
                    "modes": {
                        "generalized": {
                            "retrieved_ids": [
                                "hlsgen.crypto.lookup_round_guard"
                            ],
                            "exact_source_measured_case_count": 0,
                        }
                    }
                },
            },
            {
                "task_id": "polybench__cholesky",
                "q_hw_delta": -0.1,
                "acceleration_delta": -1.0,
                "hypotheses": ["missed_strategy_lane"],
                "offline_retrieval_replay": {
                    "modes": {
                        "generalized": {
                            "retrieved_ids": [
                                "hlsgen.linear_algebra.factorization_dependency_guard"
                            ],
                            "exact_source_measured_case_count": 0,
                        }
                    }
                },
            },
            {
                "task_id": "machsuite__gemm_blocked",
                "q_hw_delta": -0.1,
                "acceleration_delta": -60.0,
                "hypotheses": ["low_token_conservative_behavior"],
                "offline_retrieval_replay": {
                    "modes": {
                        "generalized": {
                            "retrieved_ids": ["hlsgen.gemm.tiled_reuse"],
                            "exact_source_measured_case_count": 0,
                        }
                    }
                },
            },
        ]
    }
    post_quarantine = {
        "estimated_success_rate_after_quarantine": 0.866,
        "remaining_failure_count": 23,
        "suggested_small_sample_tasks": [
            "c2hlsc__des",
            "pp4fpga__parallel_merge_sort",
            "amd_accel__performance_host_global_bandwidth_src_kernel",
        ],
    }

    status = analyze_phase2f_objective_status(qor_analysis, post_quarantine)

    qor = status["qor_rag_generalized_offline"]
    assert qor["priority_task_count"] == 3
    assert qor["exact_source_clean_count"] == 3
    assert qor["offline_prompt_coverage_ready_count"] == 3
    assert qor["measured_qor_repair_proven"] is False
    assert qor["suggested_qor_small_ab_tasks"] == [
        "machsuite__aes_aes",
        "polybench__cholesky",
        "machsuite__gemm_blocked",
    ]
    assert (
        status["failed_task_success_rate_offline"][
            "suggested_failure_small_sample_tasks"
        ]
        == [
            "c2hlsc__des",
            "pp4fpga__parallel_merge_sort",
            "amd_accel__performance_host_global_bandwidth_src_kernel",
        ]
    )
    assert status["completion"]["objective_complete"] is False
