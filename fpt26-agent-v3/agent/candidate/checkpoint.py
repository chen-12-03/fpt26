"""Persist and recover the last verified candidate across process restarts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from agent.models import CandidateEvaluation


def save_checkpoint(
    kernel: str,
    evaluation: CandidateEvaluation,
    *,
    checkpoint_dir: str | Path,
    task_id: str,
) -> Path:
    """Atomically save a verified candidate and its evaluation evidence.

    The checkpoint is only written if *evaluation.accepted* is True.
    Returns the path to the checkpoint file.
    """
    if not evaluation.accepted:
        raise ValueError("refusing to checkpoint an unaccepted candidate")

    d = Path(checkpoint_dir)
    d.mkdir(parents=True, exist_ok=True)

    kernel_sha = hashlib.sha256(kernel.encode("utf-8")).hexdigest()
    payload = {
        "schema_version": 1,
        "task_id": task_id,
        "kernel": kernel,
        "kernel_sha256": kernel_sha,
        "evaluation": evaluation.to_dict(),
    }

    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)

    # Atomic write
    fd, tmp = tempfile.mkstemp(dir=str(d), prefix=".checkpoint.")
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        target = d / "verified_checkpoint.json"
        os.rename(tmp, str(target))
        return target
    except Exception:
        os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_checkpoint(
    checkpoint_dir: str | Path,
    *,
    task_id: str | None = None,
) -> tuple[str, CandidateEvaluation] | None:
    """Load the last verified candidate from a checkpoint.

    Returns ``(kernel, evaluation)`` or ``None`` if no valid checkpoint exists.
    If *task_id* is provided, the checkpoint's task_id must match.
    """
    fp = Path(checkpoint_dir) / "verified_checkpoint.json"
    if not fp.is_file():
        return None

    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(data, dict):
        return None

    # Validate schema
    if data.get("schema_version") != 1:
        return None

    stored_task = data.get("task_id", "")
    if task_id and stored_task != task_id:
        return None

    kernel = data.get("kernel")
    stored_sha = data.get("kernel_sha256")
    if not isinstance(kernel, str) or not kernel.strip():
        return None
    if not isinstance(stored_sha, str) or len(stored_sha) != 64:
        return None

    # Verify digest
    actual_sha = hashlib.sha256(kernel.encode("utf-8")).hexdigest()
    if actual_sha != stored_sha:
        return None  # digest mismatch — fail closed

    # Reconstruct evaluation
    eval_data = data.get("evaluation") or {}
    ev = CandidateEvaluation(source_sha256=stored_sha)
    ev.accepted = bool(eval_data.get("accepted", False))
    ev.stage = str(eval_data.get("stage", "checkpoint"))
    ev.failure_reason = str(eval_data.get("failure_reason", ""))
    ev.synth_latency = eval_data.get("synth_latency")
    ev.synth_ii = eval_data.get("synth_ii")
    ev.synth_clock_ns = eval_data.get("synth_clock_ns")
    ev.synth_resources = dict(eval_data.get("synth_resources", {}))

    return kernel, ev


def checkpoint_digest_matches(kernel: str, checkpoint_dir: str | Path) -> bool:
    """Return True if *kernel* matches the checkpoint digest."""
    result = load_checkpoint(checkpoint_dir)
    if result is None:
        return False
    stored_kernel, _ = result
    return stored_kernel == kernel
