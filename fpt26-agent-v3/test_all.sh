#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
IMAGE=${FPT26_AGENT_IMAGE:-fpt26-agent-v3:latest}
VITIS_MOUNT_ROOT=${VITIS_MOUNT_ROOT:-/tools/Xilinx}
VITIS_ROOT=${VITIS:-/tools/Xilinx/2025.2/Vitis}

test -f "$VITIS_ROOT/settings64.sh" || {
  echo "test_all: Vitis settings64.sh not found under $VITIS_ROOT" >&2
  exit 2
}

docker run --rm \
  -e FPT26_REAL_VITIS_TESTS=1 \
  -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$REPO_ROOT:/workspace" \
  -v "$VITIS_MOUNT_ROOT:$VITIS_MOUNT_ROOT:ro" \
  -w /workspace/fpt26-agent-v3 \
  "$IMAGE" \
  bash -lc \
  "source '$VITIS_ROOT/settings64.sh' && python3 -m pytest -q tests scoring -rs"
