#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
DEFAULT_XRT=/opt/xilinx/xrt
DEFAULT_HLS_PART=xcu55c-fsvh2892-2L-e
DEFAULT_VITIS=/tools/Xilinx/2025.2/Vitis

fail() {
  echo "run-agent: error: $*" >&2
  exit 2
}

export VITIS=${VITIS:-$DEFAULT_VITIS}
[ -f "$VITIS/settings64.sh" ] || fail "VITIS settings64.sh does not exist: $VITIS/settings64.sh"
VITIS_RESOLVED=$(cd "$VITIS" && pwd -P)
export VITIS_MOUNT_ROOT=${VITIS_MOUNT_ROOT:-$(dirname "$(dirname "$VITIS_RESOLVED")")}
[ -d "$VITIS_MOUNT_ROOT" ] || fail "VITIS_MOUNT_ROOT path does not exist: $VITIS_MOUNT_ROOT"

if [ -n "${XRT:-}" ]; then
  [ -f "$XRT/setup.sh" ] || fail "XRT setup.sh does not exist: $XRT/setup.sh"
  export XILINX_XRT="$XRT"
  export FPT26_XRT_SOURCE=host-override
else
  export XRT="$DEFAULT_XRT"
  export XILINX_XRT="$DEFAULT_XRT"
  export FPT26_XRT_SOURCE=image-default
fi

export HLS_PART=${HLS_PART:-$DEFAULT_HLS_PART}
[ -n "$HLS_PART" ] || fail "HLS_PART must not be empty"

if [ "${FPT26_REQUIRE_PLATFORM:-0}" = "1" ]; then
  [ -n "${PLATFORM:-}" ] || fail "PLATFORM is required when FPT26_REQUIRE_PLATFORM=1"
  [ -f "$PLATFORM" ] || fail "PLATFORM file does not exist: $PLATFORM"
fi

export FPT26_REPO_ROOT="$REPO_ROOT"
export HOST_UID=${HOST_UID:-$(id -u)}
export HOST_GID=${HOST_GID:-$(id -g)}
export USER=${USER:-$(id -un)}
export LOGNAME=${LOGNAME:-$USER}
export XILINX_VITIS="$VITIS"
export LLM4HLS_VITIS_HLS_ROOT="$VITIS"
export LLM4HLS_PART="$HLS_PART"
export FPT26_AGENT_IMAGE=${FPT26_AGENT_IMAGE:-fpt26-agent-v3:latest}
export FPT26_AGENT_BASE_IMAGE=${FPT26_AGENT_BASE_IMAGE:-xilinx/xilinx_runtime_base:alveo-2023.2-ubuntu-22.04}

if [ "$#" -eq 0 ]; then
  set -- bash
fi

if [ "${FPT26_DRY_RUN:-0}" = "1" ]; then
  echo "FPT26_DRY_RUN=1"
  echo "VITIS=$VITIS"
  echo "VITIS_MOUNT_ROOT=$VITIS_MOUNT_ROOT"
  echo "XRT=$XRT"
  echo "XILINX_XRT=$XILINX_XRT"
  echo "FPT26_XRT_SOURCE=$FPT26_XRT_SOURCE"
  echo "PLATFORM=${PLATFORM:-}"
  echo "HLS_PART=$HLS_PART"
  echo "FPT26_REQUIRE_PLATFORM=${FPT26_REQUIRE_PLATFORM:-0}"
  index=0
  for arg in "$@"; do
    echo "ARGV_$index=$arg"
    index=$((index + 1))
  done
  exit "${FPT26_DRY_RUN_EXIT_CODE:-0}"
fi

command -v docker >/dev/null 2>&1 || fail "docker is not available on PATH"
docker compose version >/dev/null 2>&1 || fail "docker compose is not available"
if ! docker image inspect "$FPT26_AGENT_IMAGE" >/dev/null 2>&1; then
  echo "run-agent: image $FPT26_AGENT_IMAGE not found; building it..." >&2
  docker compose \
    --file "$COMPOSE_FILE" \
    --project-directory "$REPO_ROOT" \
    build agent
fi

printf -v INNER_COMMAND "%q " "$@"
TOOLCHAIN_PREAMBLE='
set -euo pipefail
cd /workspace
if [ "${FPT26_SOURCE_TOOLCHAIN:-0}" = "1" ]; then
  source "$VITIS/settings64.sh"
  source "$XILINX_XRT/setup.sh"
fi
exec '"$INNER_COMMAND"'
'

COMPOSE_RUN_ARGS=(
  --file "$COMPOSE_FILE"
  --project-directory "$REPO_ROOT"
  run --rm
  --entrypoint /bin/bash
)

if [ "$FPT26_XRT_SOURCE" = "host-override" ]; then
  COMPOSE_RUN_ARGS+=(--volume "$XRT:$XRT:ro")
fi

if [ -n "${PLATFORM:-}" ] && [ -f "$PLATFORM" ]; then
  COMPOSE_RUN_ARGS+=(--volume "$PLATFORM:$PLATFORM:ro")
fi

exec docker compose \
  "${COMPOSE_RUN_ARGS[@]}" \
  agent \
  -lc "$TOOLCHAIN_PREAMBLE"
