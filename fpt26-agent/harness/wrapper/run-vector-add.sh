#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
AGENT_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)

cd "$AGENT_ROOT"
exec ./run-vitis.sh bash harness/wrapper/run-vector-add-in-docker.sh
