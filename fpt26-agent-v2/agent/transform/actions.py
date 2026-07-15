from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SUPPORTED_ACTIONS = {"pipeline_loop", "unroll_loop", "array_partition"}


@dataclass(frozen=True)
class TransformAction:
    action_type: str
    target: str
    ii: int | None = None
    factor: int | None = None
    dimension: int | None = None
    partition_mode: str | None = None
    reason: str | None = None
    risk: str = "low"

    def __post_init__(self) -> None:
        if self.action_type not in SUPPORTED_ACTIONS:
            raise ValueError(f"unsupported action_type: {self.action_type}")
        if not self.target:
            raise ValueError("target must be non-empty")
        if self.action_type == "pipeline_loop" and (self.ii is None or self.ii <= 0):
            raise ValueError("pipeline_loop requires a positive ii")
        if self.action_type in {"unroll_loop", "array_partition"} and (
            self.factor is None or self.factor <= 1
        ):
            raise ValueError(f"{self.action_type} requires factor > 1")
        if self.action_type == "array_partition":
            if self.dimension is None or self.dimension <= 0:
                raise ValueError("array_partition requires a positive dimension")
            if self.partition_mode not in {"cyclic", "block", "complete"}:
                raise ValueError("array_partition requires partition_mode cyclic, block, or complete")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "target": self.target,
            "ii": self.ii,
            "factor": self.factor,
            "dimension": self.dimension,
            "partition_mode": self.partition_mode,
            "reason": self.reason,
            "risk": self.risk,
        }

    @property
    def candidate_label(self) -> str:
        return {
            "pipeline_loop": "pipeline",
            "unroll_loop": "unroll",
            "array_partition": "partition",
        }[self.action_type]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TransformAction":
        return cls(
            action_type=data["action_type"],
            target=data["target"],
            ii=data.get("ii"),
            factor=data.get("factor"),
            dimension=data.get("dimension"),
            partition_mode=data.get("partition_mode"),
            reason=data.get("reason"),
            risk=data.get("risk", "low"),
        )
