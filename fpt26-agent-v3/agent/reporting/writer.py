"""Atomic report and artifact writing.

All writes to the output tree go through this module so that:
- Atomicity (write-then-rename for critical files) is enforced
- Sensitive data is redacted before persistence
- Schema versions are stamped on every file
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from agent.security.redaction import redact_sensitive_text


def _atomic_write(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write *content* to *path* via a temp file + rename for atomicity."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".")
    try:
        os.write(fd, content.encode(encoding))
        os.fsync(fd)
        os.close(fd)
        os.rename(tmp, str(path))
    except Exception:
        os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json_report(
    report: dict[str, Any],
    output_dir: str | Path,
    *,
    filename: str = "run_report.json",
    redact: bool = True,
) -> Path:
    """Persist a JSON report to *output_dir* with atomic write.

    Args:
        report: The report dictionary to serialise.
        output_dir: Target directory (will be created if needed).
        filename: Output file name.
        redact: If True, also write a redacted copy of any string fields.

    Returns:
        Path to the written file.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Serialise
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    # Redact sensitive content before writing to disk
    if redact:
        text = redact_sensitive_text(text)

    target = out / filename
    _atomic_write(target, text)
    return target


def write_failure_report(
    *,
    output_dir: str | Path,
    task_id: str,
    run_role: str,
    status: str,
    stop_reason: str,
    error_type: str,
    error_message: str,
    redact: bool = True,
) -> Path:
    """Persist a truthful bootstrap/infrastructure failure report.

    This can be called **without** a :class:`RunState`, e.g. when the pipeline
    never started.
    """
    if redact:
        error_message = redact_sensitive_text(error_message)

    report: dict[str, Any] = {
        "schema_version": 1,
        "task_id": task_id,
        "run_role": run_role,
        "status": status,
        "stop_reason": stop_reason,
        "error": {
            "type": error_type,
            "message": error_message,
        },
        "scoring": None,
        "execution_trace": {
            "transcript": [],
            "metered_results": [],
            "grading_results": [],
        },
    }
    return write_json_report(report, output_dir, redact=False)


def final_kernel_digest(kernel_path: str | Path) -> dict[str, Any]:
    """Return ``{path, sha256, size}`` for the final kernel artifact."""
    fp = Path(kernel_path)
    if not fp.is_file():
        return {"path": str(fp), "sha256": "", "size": 0, "missing": True}
    data = fp.read_bytes()
    return {
        "path": str(fp),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "missing": False,
    }
