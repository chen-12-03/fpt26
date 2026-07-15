"""Global toolchain + target constants for the LLM4HLS Track A harness.

All values are overridable via environment variables so the same harness runs
against a different Vitis install or target board without code changes.

Competition targets are pinned here (Vitis 2025.2 + Alveo U55C @ 200 MHz),
mirroring the decisions locked for the LLM4HLS Track A benchmark.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Toolchain -------------------------------------------------------------
# Root of the Vitis install; its settings64.sh is sourced before every
# `vitis-run` invocation so the harness needs nothing on the ambient PATH.
# Vitis 2025.2 dropped the standalone `vitis_hls` binary: HLS now runs via
# `vitis-run --mode hls --tcl <script>` (see vitis.py).
def _default_vitis_root() -> Path:
    override = os.environ.get("LLM4HLS_VITIS_HLS_ROOT")
    if override:
        return Path(override)

    for candidate in (
        Path("/tools/Xilinx/Vitis/2025.2"),
        Path("/tools/Xilinx/2025.2/Vitis"),
        Path("/opt/xilinx/2025.2/Vitis"),
    ):
        if (candidate / "settings64.sh").exists():
            return candidate

    return Path("/opt/xilinx/2025.2/Vitis")


VITIS_HLS_ROOT = _default_vitis_root()
VITIS_SETTINGS = VITIS_HLS_ROOT / "settings64.sh"

# --- Target constraints (pinned for the competition) -----------------------
DEFAULT_PART = os.environ.get("LLM4HLS_PART", "xcu55c-fsvh2892-2L-e")  # Alveo U55C
DEFAULT_CLOCK_NS = float(os.environ.get("LLM4HLS_CLOCK_NS", "5.0"))  # 200 MHz
DEFAULT_FLOW_TARGET = "vivado"  # open_solution -flow_target

# --- Tool timeouts (seconds) ----------------------------------------------
CSIM_TIMEOUT_S = float(os.environ.get("LLM4HLS_CSIM_TIMEOUT_S", "180"))
SYNTH_TIMEOUT_S = float(os.environ.get("LLM4HLS_SYNTH_TIMEOUT_S", "600"))
# cosim runs an RTL simulation; a deadlocked design will hang until this fires.
COSIM_TIMEOUT_S = float(os.environ.get("LLM4HLS_COSIM_TIMEOUT_S", "900"))

# --- Budget: credit cost per tool call ------------------------------------
# Weighted by typical wall-clock cost. cosim is by far the heaviest.
CREDIT_COST = {
    "csim": int(os.environ.get("LLM4HLS_COST_CSIM", "1")),
    "synth": int(os.environ.get("LLM4HLS_COST_SYNTH", "4")),
    "cosim": int(os.environ.get("LLM4HLS_COST_COSIM", "20")),
}

# --- Reference agent LLM backend (OpenRouter, open-source models only) -----
# The contest mandates open-source models. Put your OpenRouter token below, or
# (preferred) export OPENROUTER_API_KEY in the environment.
OPENROUTER_API_KEY = os.environ.get(
    "OPENROUTER_API_KEY", ""
)  # <-- fill in your token here
OPENROUTER_BASE_URL = os.environ.get(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions"
)
# Default to an open-weight coder model; override with LLM4HLS_MODEL.
DEFAULT_LLM_MODEL = os.environ.get("LLM4HLS_MODEL", "qwen/qwen-2.5-coder-32b-instruct")
