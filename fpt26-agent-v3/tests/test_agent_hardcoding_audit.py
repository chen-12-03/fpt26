from __future__ import annotations

from pathlib import Path

from tools.audit_agent_hardcoding import build_audit, scan_occurrences


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_hardcoding_audit_separates_runtime_from_tools_and_tests(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "fpt26-agent-v3/agent/knowledge.py",
        """
def f(query, entry, generalized):
    if generalized and _source_matches_task_id(entry.source, query.task_id):
        return False
    if entry.kind != "rule" and not generalized:
        if "dot_product" in entry.tags and "dotproduct" in query.description:
            return 36.0
    if {"gemm", "matmul"}:
        signals["gemm"] = 1.0
    if {"stencil"}:
        signals["stencil"] = 1.0
    signals["crypto_lookup"] = 1.0
    signals["linear_algebra_factorization"] = 1.0
""",
    )
    _write(
        tmp_path
        / "fpt26-agent-v3/agent/agents/optimization/controller.py",
        """
if not generalized_qor_rag and _prefer_legacy_specialist(matches, desc):
    pass
def _prefer_legacy_specialist(matches, description):
    return "popcount" in description or "CORDIC" in description
""",
    )
    _write(
        tmp_path / "fpt26-agent-v3/agent/qor_rag_curate.py",
        """
def _semantic_tags(task_id):
    return ["dotproduct", "gemm"]
parser.add_argument("--no-task-id-tags")
""",
    )
    _write(
        tmp_path / "tools/prepare_tripcount_patch_sample.py",
        'DEFAULT_TASKS = ["amd_accel__host_xrt_src_krnl_vadd"]\n',
    )
    _write(
        tmp_path / "fpt26-agent-v3/tests/test_qor_rag.py",
        'TASK = "machsuite__gemm_blocked"\n',
    )

    audit = build_audit(tmp_path)

    assert audit["overall_conclusion"]["high_risk_task_answer_hardcoding_found"] is False
    assert audit["overall_conclusion"]["generalized_runtime_ready"] is True
    assert audit["risk_counts"]["medium"] == 2
    assert audit["risk_counts"]["medium_low"] == 1
    assert audit["literal_scan_summary"]["by_surface"]["agent_runtime"] >= 1
    assert audit["literal_scan_summary"]["by_surface"]["offline_tool"] == 1
    assert audit["literal_scan_summary"]["by_surface"]["tests"] == 1


def test_scan_occurrences_classifies_task_ids_and_workload_literals(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "fpt26-agent-v3/agent/example.py",
        'TASK = "machsuite__aes_aes"; WORD = "stencil"\n',
    )

    occurrences = scan_occurrences(tmp_path)

    assert {
        (item.kind, item.value, item.runtime_surface) for item in occurrences
    } == {
        ("task_id_literal", "machsuite__aes_aes", "agent_runtime"),
        ("workload_literal", "stencil", "agent_runtime"),
    }
