from __future__ import annotations

import re
from dataclasses import dataclass


_II_RESOURCE_PREFIX_RE = re.compile(
    r"\[HLS 200-448\]\s+Lower bound of II is\s+(?P<ii>\d+)\s+"
    r"due to multiple\s+(?:'(?P<quoted_operation>[^']+)'|"
    r"(?P<plain_operation>bus\s+(?:read|write)))\s+operation",
    re.IGNORECASE,
)
_ARRAY_RE = re.compile(r"\bon array '([^']+)'")
_PORT_RE = re.compile(r"\bon port '([^']+)'")
_SOURCE_RE = re.compile(
    r"\('[^']+',\s*([^)]+)\)\s+on\s+(?:array|port)"
)
_CORE_RE = re.compile(r"\baccessing core:([^\s]+)")
_MAXI_RE = re.compile(r"\baccessing '([^']+)'\s+m_axi\s+(read|write)\b")


@dataclass(frozen=True)
class IIResourceLimit:
    """Structured evidence from Vitis HLS message 200-448."""

    lower_bound: int
    operation: str
    array: str | None
    source: str | None
    core: str | None
    port: str | None = None
    storage_kind: str = "unknown"

    def summary(self) -> str:
        target = (
            f"array '{self.array}'"
            if self.array
            else f"port '{self.port}'"
            if self.port
            else "an unresolved storage target"
        )
        location = f" at {self.source}" if self.source else ""
        core = f" ({self.core})" if self.core else ""
        return (
            f"Vitis HLS 200-448 reports a memory-port resource limit on "
            f"{target}{location}{core}: multiple {self.operation} operations "
            f"impose II lower bound={self.lower_bound} "
            f"(storage_kind={self.storage_kind}). Match the optimization "
            "to this array/port bottleneck; another PIPELINE directive alone "
            "cannot lower II."
        )


def extract_ii_resource_limits(log_text: str) -> list[IIResourceLimit]:
    """Extract bounded, deduplicated II resource-limit evidence from a synth log.

    Vitis can emit an extremely long 200-448 line when many accesses share one
    memory.  Only stable leading fields and the first source/array are retained;
    the full operation list is deliberately excluded from prompts.
    """
    limits: list[IIResourceLimit] = []
    seen: set[tuple] = set()
    for line in (log_text or "").splitlines():
        prefix = _II_RESOURCE_PREFIX_RE.search(line)
        if prefix is None:
            continue
        array_match = _ARRAY_RE.search(line)
        port_match = _PORT_RE.search(line)
        source_match = _SOURCE_RE.search(line)
        core_match = _CORE_RE.search(line)
        maxi_match = _MAXI_RE.search(line)
        operation = (
            prefix.group("quoted_operation")
            or prefix.group("plain_operation")
            or "unknown"
        ).lower()
        array = array_match.group(1) if array_match else None
        port = port_match.group(1) if port_match else None
        storage_kind = (
            "local_memory"
            if array
            else "external_interface"
            if maxi_match or operation.startswith("bus ")
            else "unknown"
        )
        limit = IIResourceLimit(
            lower_bound=int(prefix.group("ii")),
            operation=operation,
            array=array,
            source=source_match.group(1).strip() if source_match else None,
            core=core_match.group(1) if core_match else None,
            port=(
                port
                or (maxi_match.group(1) if maxi_match else None)
            ),
            storage_kind=storage_kind,
        )
        fingerprint = (
            limit.lower_bound,
            limit.operation,
            limit.array,
            limit.source,
            limit.core,
            limit.port,
            limit.storage_kind,
        )
        if fingerprint not in seen:
            seen.add(fingerprint)
            limits.append(limit)
    return limits
