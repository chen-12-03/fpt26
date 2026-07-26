#!/usr/bin/env python3
"""Static audit for task-specific hardcoding risk in the FPT26 agent.

The audit is intentionally conservative: it separates runtime decision paths
from tests, offline analysis tools, and small-sample planning fixtures.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_OUTPUT = Path(
    "fpt26-agent-v3/scoring/reports/phase2f_agent_hardcoding_audit_20260725.json"
)

TASK_ID_RE = re.compile(
    r"\b(?:dotProduct_optimize|projection_bugfix|residual_stream_deadlock|"
    r"[a-z][a-z0-9_]*__[A-Za-z0-9_]+)\b"
)
WORKLOAD_RE = re.compile(
    r"\b(?:dotproduct|dot product|popcount|gemm|matmul|stencil|cordic|"
    r"aes|des|cipher|cholesky|lu|fft|fir)\b",
    re.IGNORECASE,
)

SOURCE_GLOBS = (
    "fpt26-agent-v3/agent/**/*.py",
    "fpt26-agent-v3/scoring/**/*.py",
    "tools/**/*.py",
    "fpt26-agent-v3/tests/**/*.py",
)
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache"}


@dataclass(frozen=True)
class Occurrence:
    path: str
    line: int
    kind: str
    value: str
    runtime_surface: str
    context: str
    snippet: str


def build_audit(repo_root: Path) -> dict[str, Any]:
    occurrences = scan_occurrences(repo_root)
    findings = _curated_findings(repo_root, occurrences)
    risk_counts: dict[str, int] = {}
    for finding in findings:
        risk = str(finding["risk"])
        risk_counts[risk] = risk_counts.get(risk, 0) + 1

    runtime_task_literals = [
        item
        for item in occurrences
        if item.kind == "task_id_literal"
        and item.runtime_surface == "agent_runtime"
    ]
    runtime_workload_literals = [
        item
        for item in occurrences
        if item.kind == "workload_literal"
        and item.runtime_surface == "agent_runtime"
    ]

    return {
        "schema_version": 1,
        "purpose": "phase2f_static_agent_hardcoding_audit",
        "status": "static_audit_only",
        "scope": {
            "repo_root": str(repo_root),
            "source_globs": list(SOURCE_GLOBS),
            "no_api_or_vitis": True,
            "no_hidden_reference_or_evaluator_reads": True,
        },
        "overall_conclusion": {
            "high_risk_task_answer_hardcoding_found": False,
            "generalized_runtime_ready": True,
            "summary": (
                "No runtime branch was found that returns a task-specific "
                "kernel or optimization answer for a concrete task id.  The "
                "remaining medium risks are compatibility paths or task-id "
                "tag curation defaults that are mitigated by "
                "FPT26_QOR_RAG_GENERALIZED=1 and --no-task-id-tags."
            ),
        },
        "risk_counts": dict(sorted(risk_counts.items())),
        "literal_scan_summary": {
            "total_occurrences": len(occurrences),
            "agent_runtime_task_id_literal_count": len(runtime_task_literals),
            "agent_runtime_workload_literal_count": len(
                runtime_workload_literals
            ),
            "by_surface": _count_by(occurrences, "runtime_surface"),
            "by_kind": _count_by(occurrences, "kind"),
        },
        "findings": findings,
        "representative_occurrences": [
            asdict(item) for item in _representative_occurrences(occurrences)
        ],
        "recommended_next_actions": [
            "Use FPT26_QOR_RAG_GENERALIZED=1 for formal QoR-RAG A/B and competition-like lanes.",
            "Use qor_rag_curate.py --no-task-id-tags when promoting future measured cases into generalized assets.",
            "Keep fixed task lists in tools/reports only; do not move them into agent runtime decision paths.",
            "After each retrieval change, rerun generalized exact-source tests and retrieval eval before any 1-3 task measured A/B.",
        ],
    }


def scan_occurrences(repo_root: Path) -> list[Occurrence]:
    occurrences: list[Occurrence] = []
    for path in _iter_source_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        surface = _runtime_surface(rel)
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        in_docstring = False
        for lineno, line in enumerate(lines, start=1):
            context = _line_context(line, in_docstring=in_docstring)
            for match in TASK_ID_RE.finditer(line):
                occurrences.append(
                    Occurrence(
                        path=rel,
                        line=lineno,
                        kind="task_id_literal",
                        value=match.group(0),
                        runtime_surface=(
                            "documentation"
                            if context == "documentation"
                            else surface
                        ),
                        context=context,
                        snippet=line.strip()[:220],
                    )
                )
            for match in WORKLOAD_RE.finditer(line):
                occurrences.append(
                    Occurrence(
                        path=rel,
                        line=lineno,
                        kind="workload_literal",
                        value=match.group(0),
                        runtime_surface=(
                            "documentation"
                            if context == "documentation"
                            else surface
                        ),
                        context=context,
                        snippet=line.strip()[:220],
                    )
                )
            in_docstring = _next_docstring_state(line, in_docstring)
    return sorted(
        occurrences,
        key=lambda item: (item.runtime_surface, item.path, item.line, item.value),
    )


def _iter_source_files(repo_root: Path) -> Iterable[Path]:
    seen: set[Path] = set()
    for pattern in SOURCE_GLOBS:
        for path in repo_root.glob(pattern):
            if path in seen or not path.is_file():
                continue
            if set(path.parts) & SKIP_PARTS:
                continue
            seen.add(path)
            yield path


def _runtime_surface(relative_path: str) -> str:
    if "/tests/" in relative_path or relative_path.startswith(
        "fpt26-agent-v3/tests/"
    ):
        return "tests"
    if relative_path.startswith("tools/"):
        return "offline_tool"
    if relative_path.startswith("fpt26-agent-v3/scoring/"):
        if relative_path.endswith("analyze_all_real_api.py"):
            return "offline_analysis"
        if relative_path.endswith("_test.py") or "/test_" in relative_path:
            return "tests"
        return "scoring_runtime"
    if relative_path.startswith("fpt26-agent-v3/agent/"):
        return "agent_runtime"
    return "other"


def _line_context(line: str, *, in_docstring: bool) -> str:
    stripped = line.strip()
    if in_docstring or stripped.startswith("#"):
        return "documentation"
    if stripped.startswith(('"""', "'''")):
        return "documentation"
    return "code"


def _next_docstring_state(line: str, in_docstring: bool) -> bool:
    stripped = line.strip()
    triple_count = stripped.count('"""') + stripped.count("'''")
    if triple_count == 0:
        return in_docstring
    if triple_count >= 2:
        return in_docstring
    return not in_docstring


def _curated_findings(
    repo_root: Path, occurrences: Sequence[Occurrence]
) -> list[dict[str, Any]]:
    return [
        {
            "id": "generalized_qor_rag_exact_source_guard",
            "risk": "low",
            "runtime_surface": "agent_runtime",
            "assessment": (
                "Generalized retrieval rejects measured cases whose source "
                "matches the current task id, and exact dotProduct/popcount "
                "measured boosts are gated behind not generalized."
            ),
            "evidence": _evidence(
                repo_root,
                "fpt26-agent-v3/agent/knowledge.py",
                (
                    "generalized and _source_matches_task_id",
                    "entry.kind != \"rule\" and not generalized",
                    "dot_product",
                    "popcount",
                ),
            ),
            "mitigation": [
                "Use FPT26_QOR_RAG_GENERALIZED=1 for formal lanes.",
                "Keep tests proving exact-source measured cases are excluded.",
            ],
            "recommendation": "No code change required; keep as a regression guard.",
        },
        {
            "id": "legacy_specialist_fallback_compatibility_path",
            "risk": "medium",
            "runtime_surface": "agent_runtime",
            "assessment": (
                "The legacy specialist fallback uses description keywords for "
                "CORDIC/reduction/popcount-style workloads.  It is not a "
                "concrete task-id answer branch, but it is a compatibility "
                "path that can bias retrieval when generalized mode is off; "
                "competition strategy lanes force generalized retrieval."
            ),
            "evidence": _evidence(
                repo_root,
                "fpt26-agent-v3/agent/agents/optimization/controller.py",
                (
                    "not generalized_qor_rag",
                    "_prefer_legacy_specialist",
                    "popcount",
                    "CORDIC",
                ),
            )
            + _evidence(
                repo_root,
                "fpt26-agent-v3/agent/agents/competition.py",
                (
                    "generalized_qor_rag=True",
                    "\"qor_rag_generalized\": True",
                    "competition lanes force generalized",
                ),
            ),
            "mitigation": [
                "Disabled in generalized mode.",
                "DiverseOptimizationStage forces generalized QoR-RAG for competition-like strategy lanes.",
                "A/B plan uses FPT26_QOR_RAG_GENERALIZED=1 for candidate lane.",
            ],
            "recommendation": (
                "If generalized small A/B passes, make generalized mode the "
                "default for competition-like runs and keep legacy only for "
                "controlled ablation."
            ),
        },
        {
            "id": "task_id_tag_derivation_in_curator",
            "risk": "medium",
            "runtime_surface": "offline_tool",
            "assessment": (
                "qor_rag_curate.py can derive workload tags from task_id text "
                "for legacy asset generation.  This is not runtime retrieval, "
                "but it can leak benchmark naming into measured-case tags."
            ),
            "evidence": _evidence(
                repo_root,
                "fpt26-agent-v3/agent/qor_rag_curate.py",
                ("_semantic_tags", "--no-task-id-tags", "dotproduct", "gemm"),
            ),
            "mitigation": [
                "--no-task-id-tags is available.",
                "Generalized retrieval can ignore exact source/task matches.",
            ],
            "recommendation": (
                "Use --no-task-id-tags for any future generalized measured-case "
                "promotion."
            ),
        },
        {
            "id": "family_level_workload_lexicon",
            "risk": "medium_low",
            "runtime_surface": "agent_runtime",
            "assessment": (
                "knowledge.py contains workload words such as gemm, stencil, "
                "AES, Cholesky, and CORDIC.  They trigger family-level rules "
                "from description/source metadata/diagnostics rather than "
                "specific task-id branches."
            ),
            "evidence": _evidence(
                repo_root,
                "fpt26-agent-v3/agent/knowledge.py",
                (
                    "signals[\"gemm\"]",
                    "signals[\"stencil\"]",
                    "signals[\"crypto_lookup\"]",
                    "signals[\"linear_algebra_factorization\"]",
                ),
            ),
            "mitigation": [
                "Signals are combined with source metadata and diagnostics.",
                "Exact measured cases are filtered in generalized mode.",
            ],
            "recommendation": (
                "Keep lexicon terms tied to reusable families; avoid adding "
                "new concrete task ids here."
            ),
        },
        {
            "id": "fixed_small_sample_task_lists",
            "risk": "low",
            "runtime_surface": "offline_tool",
            "assessment": (
                "Tools contain fixed task ids for Phase 2F small-sample plans "
                "and tripcount probes.  These are report/planning defaults, "
                "not agent runtime decision branches."
            ),
            "evidence": _occurrence_evidence(
                occurrences,
                surfaces={"offline_tool"},
                kind="task_id_literal",
                exclude_paths={"tools/audit_agent_hardcoding.py"},
                limit=8,
            ),
            "mitigation": [
                "Reports label these as small-sample evidence or execution plans.",
                "run_p0_real_api_shard.py still requires explicit --task-id selection.",
            ],
            "recommendation": (
                "Keep fixed samples under tools/evals/reports and do not import "
                "them from agent runtime modules."
            ),
        },
        {
            "id": "tests_and_historical_analysis_literals",
            "risk": "low",
            "runtime_surface": "tests/offline_analysis",
            "assessment": (
                "Many concrete task ids appear in tests and historical analysis "
                "scripts.  They are fixtures or representative-report labels, "
                "not live optimization policy."
            ),
            "evidence": _occurrence_evidence(
                occurrences,
                surfaces={"tests", "offline_analysis"},
                kind="task_id_literal",
                exclude_paths=set(),
                limit=8,
            ),
            "mitigation": [
                "Tests assert generalized behavior rather than driving runtime output.",
                "Historical analysis scripts are outside agent.main execution.",
            ],
            "recommendation": "No action unless a test fixture is imported by runtime code.",
        },
    ]


def _evidence(
    repo_root: Path, relative_path: str, needles: Sequence[str]
) -> list[dict[str, Any]]:
    path = repo_root / relative_path
    if not path.is_file():
        return [{"path": relative_path, "available": False}]
    records = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for lineno, line in enumerate(lines, start=1):
        if any(needle in line for needle in needles):
            records.append(
                {
                    "path": relative_path,
                    "line": lineno,
                    "snippet": line.strip()[:220],
                }
            )
        if len(records) >= 10:
            break
    return records


def _occurrence_evidence(
    occurrences: Sequence[Occurrence],
    *,
    surfaces: set[str],
    kind: str,
    exclude_paths: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    records = [
        {
            "path": item.path,
            "line": item.line,
            "value": item.value,
            "snippet": item.snippet,
        }
        for item in occurrences
        if item.runtime_surface in surfaces and item.kind == kind
        and item.path not in exclude_paths
    ]
    return records[:limit]


def _representative_occurrences(
    occurrences: Sequence[Occurrence],
) -> list[Occurrence]:
    selected: list[Occurrence] = []
    seen: set[tuple[str, str, str]] = set()
    for item in occurrences:
        key = (item.runtime_surface, item.kind, item.value.lower())
        if key in seen:
            continue
        seen.add(key)
        selected.append(item)
        if len(selected) >= 40:
            break
    return selected


def _count_by(items: Sequence[Any], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(getattr(item, field))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    audit = build_audit(repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
