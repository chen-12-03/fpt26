"""Path and identifier validation for security-critical boundaries.

All HLS tool invocations receive user-controlled identifiers (task names,
function names, file paths) that are embedded in shell commands, Tcl scripts,
and filesystem operations.  This module provides the single validation point
that must pass before any such value reaches a subprocess.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

from agent.errors import (
    InvalidIdentifierError,
    PathEscapesWorkspaceError,
    SymlinkNotAllowedError,
)
from agent.security.redaction import redact_sensitive_text


# ── Identifier validation ────────────────────────────────────────────────────

# task_id: alphanumeric + underscores + hyphens.  Both single-underscore names
# ("dotProduct_optimize") and double-underscore namespace separators
# ("polybench__gemm") are valid.
_TASK_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:_+[A-Za-z][A-Za-z0-9_-]*)*$")

# HLS identifiers: C identifier + optional template/namespace qualifiers
_HLS_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_:<>]*$")

# Tcl-safe: no backticks, dollar-substitution, brackets, or unquoted semicolons
_TCL_UNSAFE_RE = re.compile(r"[`$\[\]{};]")


def validate_task_id(task_id: str) -> str:
    """Validate *task_id* against the project naming convention.

    Returns the validated string unchanged on success.
    Raises :class:`InvalidIdentifierError` on failure.
    """
    if not isinstance(task_id, str) or not task_id.strip():
        raise InvalidIdentifierError("task_id must be a non-empty string")
    task_id = task_id.strip()
    if not _TASK_ID_RE.match(task_id):
        raise InvalidIdentifierError(
            f"task_id {redact_sensitive_text(task_id)!r} contains disallowed characters"
        )
    if ".." in task_id:
        raise InvalidIdentifierError("task_id must not contain '..'")
    return task_id


def validate_hls_identifier(name: str, *, field: str = "identifier") -> str:
    """Validate an HLS top-name or function identifier.

    Returns the validated string on success.
    Raises :class:`InvalidIdentifierError` on failure.
    """
    if not isinstance(name, str) or not name.strip():
        raise InvalidIdentifierError(f"{field} must be a non-empty string")
    name = name.strip()
    if not _HLS_IDENTIFIER_RE.match(name):
        raise InvalidIdentifierError(
            f"{field} {redact_sensitive_text(name)!r} is not a valid HLS identifier"
        )
    if len(name) > 256:
        raise InvalidIdentifierError(f"{field} exceeds maximum length (256)")
    return name


def validate_tcl_token(token: str, *, field: str = "tcl_token") -> str:
    """Validate a token that will be embedded in a Tcl script.

    Returns the validated string on success.
    Raises :class:`InvalidIdentifierError` on failure.
    """
    if not isinstance(token, str):
        raise InvalidIdentifierError(f"{field} must be a string")
    if _TCL_UNSAFE_RE.search(token):
        raise InvalidIdentifierError(
            f"{field} contains Tcl-unsafe characters"
        )
    if len(token) > 1024:
        raise InvalidIdentifierError(f"{field} exceeds maximum Tcl token length")
    return token


# ── Path validation ──────────────────────────────────────────────────────────

def resolve_safe_path(
    path: str | Path,
    *,
    root: str | Path,
    allow_symlink: bool = False,
    must_exist: bool = True,
) -> Path:
    """Resolve *path* and verify it lies inside *root*.

    Symlinks are checked BEFORE resolution so internal symlinks are caught.
    """
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise FileNotFoundError(f"root directory not found: {root}")

    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root_path / candidate

    # Check symlinks on the raw (pre-resolve) path first
    if not allow_symlink:
        _check_no_symlinks_in_path(candidate)

    resolved = candidate.resolve()

    # Path must be within root
    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise PathEscapesWorkspaceError(
            f"path {str(path)!r} resolves to {str(resolved)!r} "
            f"which is outside root {str(root_path)!r}"
        ) from exc

    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"required path does not exist: {resolved}")

    return resolved


def validate_workspace_path(
    path: str,
    *,
    workspace_root: str | Path,
    artifact_root: str | Path | None = None,
) -> Path:
    """Validate an output/artifact path stays within the permitted roots.

    Args:
        path: The requested output path.
        workspace_root: The primary workspace root.
        artifact_root: An optional secondary permitted root (e.g. a shared output dir).

    Returns:
        The safe resolved path.

    Raises:
        PathEscapesWorkspaceError: path escapes all permitted roots.
    """
    resolved = Path(path).resolve()

    roots: list[Path] = [Path(workspace_root).resolve()]
    if artifact_root is not None:
        roots.append(Path(artifact_root).resolve())

    for root in roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue

    raise PathEscapesWorkspaceError(
        f"workspace path {str(path)!r} resolves to {str(resolved)!r} "
        f"which is outside permitted roots"
    )


def _check_no_symlinks_in_path(path: Path) -> None:
    """Check every component of *path* (parent chain + final).  Raise on any symlink.

    Walks from the filesystem root to *path*, checking each segment before
    resolution.  This catches symlinks before ``Path.resolve()`` collapses them.
    """
    # Collect all path segments from root to leaf
    parts: list[Path] = []
    current = path
    while current != current.parent:
        parts.append(current)
        current = current.parent
    parts.reverse()  # root-first order

    for component in parts:
        if component.is_symlink():
            raise SymlinkNotAllowedError(
                f"symlink not allowed: {component} "
                f"(target={os.readlink(str(component))})"
            )
