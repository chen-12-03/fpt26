"""Execution environment policy for Vitis HLS subprocess invocations.

Every subprocess that runs untrusted code (candidate C/C++ kernels) or embeds
user-controlled identifiers in shell commands must conform to this policy.
The policy is enforced at the point where ``subprocess.run`` / ``subprocess.Popen``
is called — not by scanning source code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


# Environment variables that are safe to forward to subprocesses.
# Everything else is stripped.
_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        # Essential system
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TMP",
        "TEMP",
        # Xilinx / Vitis toolchain
        "XILINX_VITIS",
        "XILINX_XRT",
        "XILINXD_LICENSE_FILE",
        "LM_LICENSE_FILE",
        "VITIS",
        "XRT",
        "PLATFORM",
        "HLS_PART",
        "LLM4HLS_VITIS_HLS_ROOT",
        "LLM4HLS_PART",
        # Python
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUNBUFFERED",
        "VIRTUAL_ENV",
        # Container
        "WORKSPACE",
        "FPT26_REPO_ROOT",
        "FPT26_RUN_OUTPUT_ROOT",
        "FPT26_XRT_SOURCE",
        "FPT26_REAL_VITIS_TESTS",
        # Build
        "LD_LIBRARY_PATH",
        "LIBRARY_PATH",
    }
)

# Environment variable prefixes that indicate secrets and are NEVER forwarded.
_SECRET_PREFIXES: tuple[str, ...] = (
    "FPT26_LLM_",
    "OPENROUTER_",
    "LLM4HLS_LLM_",
    "API_KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
)


def env_allowlist(extra: frozenset[str] | None = None) -> frozenset[str]:
    """Return the current environment allowlist (with optional *extra* entries)."""
    if extra is None:
        return _ENV_ALLOWLIST
    return _ENV_ALLOWLIST | extra


def _is_secret_var(name: str) -> bool:
    """Return True if *name* looks like an API key / token / secret variable."""
    upper = name.upper()
    for prefix in _SECRET_PREFIXES:
        if upper.startswith(prefix):
            return True
    return False


def sanitise_env(
    env: dict[str, str] | None = None,
    *,
    extra_allow: frozenset[str] | None = None,
) -> dict[str, str]:
    """Return a copy of the environment containing only allowlisted variables.

    Args:
        env: Source environment (default: ``os.environ``).
        extra_allow: Additional variable names to permit.

    Returns:
        A new ``dict`` safe to pass as ``env`` to ``subprocess.run``.
    """
    source = env if env is not None else os.environ
    allow = set(env_allowlist(extra_allow))
    clean: dict[str, str] = {}
    for key, value in source.items():
        if key in allow:
            clean[key] = value
        elif _is_secret_var(key):
            # Explicitly skip secret-shaped variables even if they somehow
            # ended up in the allowlist.
            continue
    return clean


@dataclass(frozen=True)
class ExecutionPolicy:
    """Immutable policy governing a subprocess invocation.

    Attributes:
        env_allowlist: Set of environment variable names to forward.
        timeout_seconds: Maximum wall-clock time for the subprocess.
        workspace_root: All file access must be within this tree.
        read_only_inputs: Paths that must not be written to.
        allowed_output_dirs: Outputs may only be written under these trees.
    """

    env_allowlist: frozenset[str] = field(default_factory=env_allowlist)
    timeout_seconds: int = 3600
    workspace_root: str = "/workspace"
    read_only_inputs: tuple[str, ...] = ()
    allowed_output_dirs: tuple[str, ...] = ()

    def sanitised_env(self) -> dict[str, str]:
        """Return a clean environment dict for this policy."""
        return sanitise_env(extra_allow=self.env_allowlist)


# Default policy used for all Vitis tool invocations in the agent.
DEFAULT_POLICY = ExecutionPolicy()
