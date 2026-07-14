from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    label: str
    kernel_sha256: str
    task_context_sha256: str
    parent_candidate_id: str | None
    action: dict[str, Any] | None
    lineage: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "label": self.label,
            "kernel_sha256": self.kernel_sha256,
            "task_context_sha256": self.task_context_sha256,
            "parent_candidate_id": self.parent_candidate_id,
            "action": self.action,
            "lineage": list(self.lineage),
        }


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(data: dict[str, Any]) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_text(payload)
