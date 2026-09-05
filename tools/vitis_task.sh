#!/usr/bin/env bash
# One-shot Vitis operation on a single task, executed inside Docker.
#
# Usage:
#   tools/vitis_task.sh <task-dir> <csim|synth|cosim> [--build-dir DIR]
#
# Examples (from the repo root):
#   tools/vitis_task.sh tasks/official/dotProduct_optimize csim
#   tools/vitis_task.sh tasks/official/dotProduct_optimize synth
#   tools/vitis_task.sh tasks/official/dotProduct_optimize cosim
#
# The task dir may be given as a repo-relative or absolute path.  The host
# Xilinx install is bind-mounted read-only and sourced inside the container,
# and the driver (tools/vitis_task.py) reuses the harness llm4hls tools, so
# results match the agent/grading pipeline.  Exit code: 0 = op passed.
#
# Env overrides: FPT26_AGENT_IMAGE, FPT26_VITIS_SETTINGS, VITIS_MOUNT_ROOT.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
IMAGE=${FPT26_AGENT_IMAGE:-fpt26-agent-v3:latest}
VITIS_SETTINGS=${FPT26_VITIS_SETTINGS:-}

if ! command -v docker >/dev/null 2>&1; then
  echo "vitis_task.sh: docker is not installed or not available on PATH" >&2
  exit 2
fi
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "vitis_task.sh: image not found: $IMAGE (build it with: docker compose -f fpt26-agent-v3/docker-compose.yml build)" >&2
  exit 2
fi

if [ -z "$VITIS_SETTINGS" ]; then
  for candidate in \
    "${VITIS:-}/settings64.sh" \
    "${XILINX_VITIS:-}/settings64.sh" \
    /tools/Xilinx/2025.2/Vitis/settings64.sh \
    /tools/Xilinx/Vitis/2025.2/settings64.sh
  do
    if [ -f "$candidate" ]; then
      VITIS_SETTINGS=$candidate
      break
    fi
  done
fi
if [ ! -f "$VITIS_SETTINGS" ]; then
  echo "vitis_task.sh: Vitis settings64.sh not found; set FPT26_VITIS_SETTINGS" >&2
  exit 2
fi
VITIS_SETTINGS=$(realpath "$VITIS_SETTINGS")
VITIS_ROOT=$(dirname "$VITIS_SETTINGS")
VITIS_MOUNT_ROOT=${VITIS_MOUNT_ROOT:-$(dirname "$(dirname "$VITIS_ROOT")")}
[ -d "$VITIS_MOUNT_ROOT" ] || {
  echo "vitis_task.sh: VITIS_MOUNT_ROOT does not exist: $VITIS_MOUNT_ROOT" >&2
  exit 2
}

# Translate a repo-relative task path to absolute; the same path is visible
# inside the container (the repo is mounted at both /workspace and $REPO_ROOT).
args=("$@")
if [ "$#" -ge 1 ] && [[ "${args[0]}" != -* ]]; then
  if [[ "${args[0]}" == /* ]]; then
    TASK_DIR=${args[0]}
  else
    TASK_DIR="$REPO_ROOT/${args[0]}"
  fi
  if [[ "$TASK_DIR" != "$REPO_ROOT"* ]]; then
    echo "vitis_task.sh: task dir outside the repo is not mounted in the container: $TASK_DIR" >&2
    exit 2
  fi
  args[0]=$TASK_DIR
fi

DOCKER_ARGS=(
  run --rm
  --user "$(id -u):$(id -g)"
  -v "$REPO_ROOT:/workspace"
  -v "$REPO_ROOT:$REPO_ROOT"
  -v /etc/passwd:/etc/passwd:ro
  -v /etc/group:/etc/group:ro
  -v "$HOME:$HOME"
  -v "$VITIS_MOUNT_ROOT:$VITIS_MOUNT_ROOT:ro"
  -e "HOME=$HOME"
  -e "USER=${USER:-fpt26}"
  -e "LOGNAME=${LOGNAME:-${USER:-fpt26}}"
  -e FPT26_CLI_IN_CONTAINER=1
  -e "LLM4HLS_VITIS_HLS_ROOT=$VITIS_ROOT"
  -e PYTHONPATH=/workspace:/workspace/fpt26-agent-v3:/workspace/fpt26-harness
  -e PYTHONDONTWRITEBYTECODE=1
  -e PYTHONUNBUFFERED=1
  -w /workspace
)

# Locale / libtinfo compat dirs, if a previous harness run created them.
if [ -d /tmp/fpt26_locale_dirs ]; then
  DOCKER_ARGS+=(
    -v /tmp/fpt26_locale_dirs:/tmp/fpt26_locale_dirs:ro
    -e LOCPATH=/tmp/fpt26_locale_dirs/usr/lib/locale
  )
fi
if [ -d /tmp/fpt26_vitis_tinfo5_qemu ]; then
  DOCKER_ARGS+=(
    -v /tmp/fpt26_vitis_tinfo5_qemu:/tmp/fpt26_vitis_tinfo5_qemu:ro
  )
fi

exec docker "${DOCKER_ARGS[@]}" "$IMAGE" python3 tools/vitis_task.py "${args[@]}"
