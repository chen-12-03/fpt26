#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

exec "$SCRIPT_DIR/run-hls-in-docker.sh" \
  --task-id vector_add \
  --candidate-prefix baseline \
  --top vector_add \
  --source benchmarks/public/vector_add/kernel.cpp \
  --testbench benchmarks/public/vector_add/host.cpp \
  --clock-period 10
