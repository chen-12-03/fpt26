#!/usr/bin/env python3
"""Offline labeled retrieval gate for the Phase 2A QoR-RAG."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent.knowledge import (
    MAX_KNOWLEDGE_PROMPT_TOKENS,
    KnowledgeQuery,
    format_for_prompt,
    load_knowledge_entries,
    prompt_token_upper_bound,
    retrieve_knowledge,
)


def evaluate_labels(labels_path: Path) -> dict[str, Any]:
    raw = json.loads(labels_path.read_text(encoding="utf-8"))
    cases = raw.get("cases", []) if isinstance(raw, dict) else []
    entries = load_knowledge_entries()
    results: list[dict[str, Any]] = []
    deterministic = True
    max_prompt_tokens = 0

    for case in cases:
        query_raw = case["query"]
        query = KnowledgeQuery(
            source_metadata=query_raw["source_metadata"],
            baseline_qor=query_raw["baseline_qor"],
            synth_diagnostics=query_raw["synth_diagnostics"],
            resource_headroom=query_raw["resource_headroom"],
            history=query_raw["history"],
            description=query_raw.get("description", ""),
            target_part=query_raw.get("target_part", ""),
            vitis_version=query_raw.get("vitis_version", ""),
        )
        first = retrieve_knowledge(query, entries=entries)
        second = retrieve_knowledge(query, entries=entries)
        first_ids = [entry.id for entry in first]
        second_ids = [entry.id for entry in second]
        is_deterministic = first_ids == second_ids
        deterministic = deterministic and is_deterministic
        prompt_tokens = prompt_token_upper_bound(format_for_prompt(first))
        max_prompt_tokens = max(max_prompt_tokens, prompt_tokens)
        results.append(
            {
                "id": case["id"],
                "expected_id": case["expected_id"],
                "retrieved_ids": first_ids,
                "hit_at_3": case["expected_id"] in first_ids[:3],
                "deterministic": is_deterministic,
                "prompt_token_upper_bound": prompt_tokens,
            }
        )

    hits = sum(1 for result in results if result["hit_at_3"])
    total = len(results)
    recall = hits / total if total else 0.0
    gate = {
        "minimum_cases": total >= 30,
        "recall_at_3": recall >= 0.85,
        "deterministic": deterministic,
        "prompt_budget": max_prompt_tokens <= MAX_KNOWLEDGE_PROMPT_TOKENS,
    }
    return {
        "schema_version": 1,
        "labels_path": str(labels_path),
        "case_count": total,
        "hits_at_3": hits,
        "recall_at_3": round(recall, 6),
        "deterministic": deterministic,
        "max_prompt_token_upper_bound": max_prompt_tokens,
        "gate": gate,
        "passed": all(gate.values()),
        "results": results,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--labels",
        type=Path,
        default=Path("fpt26-agent-v3/evals/qor_rag_retrieval_labels.json"),
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = evaluate_labels(args.labels)
    rendered = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
