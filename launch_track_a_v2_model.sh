#!/bin/bash
# Launch Track-A 150 v2 shards for one model against the frozen release.
#
# Frozen inputs (do not vary between models):
#   release root, image, task timeout, PYTHONPATH, tool timeout policy.
# Varied per model: ENV_FILE / MODEL_ID / RUN_LABEL.
#
# Usage:
#   RUN_LABEL=... ENV_FILE=... MODEL_ID=... ./launch_track_a_v2_model.sh
#   TASK_IDS="ta2_cg_011 ta2_xr_014" SHARD_COUNT=3 RUN_LABEL=smoke ... ./launch_track_a_v2_model.sh
#
# Requeue pass (fresh attempts for tasks flagged by a prior audit):
#   RUN_LABEL=<label>_retry1 RETRY_FROM_AUDIT=/workspace/runs/audits/<audit>.json \
#     ENV_FILE=... MODEL_ID=... ./launch_track_a_v2_model.sh
#   RETRY_FROM_AUDIT is a CONTAINER path (under the mounted repo). The pass
#   reruns the audit's retry_task_ids; the audit merges both run roots and
#   supersedes the flagged records.
set -euo pipefail

# docker CLI lives outside the distro's PATH (Docker Desktop WSL integration
# ships no /usr/bin/docker in this distro); prefer it if present.
if [ -x "$HOME/.local/bin/docker" ]; then
  PATH="$HOME/.local/bin:$PATH"
fi
command -v docker >/dev/null || { echo "docker CLI not found" >&2; exit 1; }

HOST_REPO="${HOST_REPO:-/home/chen1/projects/fpt26_new}"
IMAGE="${IMAGE:-fpt26-agent-v3:latest}"
RELEASE_ROOT="${RELEASE_ROOT:-/workspace/releases/track_a_150_v2_20260910}"
case "${RELEASE_ROOT}" in
  /workspace/*) RELEASE_HOST="${HOST_REPO}/${RELEASE_ROOT#/workspace/}" ;;
  *) echo "RELEASE_ROOT must be a container path under /workspace: ${RELEASE_ROOT}" >&2; exit 1 ;;
esac

RUN_LABEL="${RUN_LABEL:?RUN_LABEL is required}"
ENV_FILE="${ENV_FILE:?ENV_FILE is required}"
MODEL_ID="${MODEL_ID:?MODEL_ID is required}"
BACKEND="${BACKEND:-custom}"
SHARD_COUNT="${SHARD_COUNT:-3}"
TASK_TIMEOUT_S="${TASK_TIMEOUT_S:-7200}"
LLM_TIMEOUT_S="${LLM_TIMEOUT_S:-360}"
MAX_REPAIR_ATTEMPTS="${MAX_REPAIR_ATTEMPTS:-6}"
TASK_IDS="${TASK_IDS:-}"
RETRY_FROM_AUDIT="${RETRY_FROM_AUDIT:-}"

[ -f "$ENV_FILE" ] || { echo "env file not found: $ENV_FILE" >&2; exit 1; }
[ -d "$RELEASE_HOST" ] || { echo "release not found: $RELEASE_HOST" >&2; exit 1; }

TASK_ID_ARGS=()
if [ -n "${TASK_IDS}" ]; then
  for t in ${TASK_IDS}; do TASK_ID_ARGS+=(--task-id "${t}"); done
fi

RETRY_ARGS=()
if [ -n "${RETRY_FROM_AUDIT}" ]; then
  case "${RETRY_FROM_AUDIT}" in
    /workspace/*) ;;
    *) echo "RETRY_FROM_AUDIT must be a container path under /workspace: ${RETRY_FROM_AUDIT}" >&2; exit 1 ;;
  esac
  RETRY_ARGS+=(--retry-from-audit "${RETRY_FROM_AUDIT}")
fi

echo "=== Launching ${SHARD_COUNT} shard(s) ==="
echo "RUN_LABEL       = ${RUN_LABEL}"
echo "MODEL           = ${MODEL_ID} (backend=${BACKEND})"
echo "RELEASE_ROOT    = ${RELEASE_ROOT}"
echo "ENV_FILE        = ${ENV_FILE}"
echo "TASK_TIMEOUT_S  = ${TASK_TIMEOUT_S}"
echo "LLM_TIMEOUT_S   = ${LLM_TIMEOUT_S}"
echo "REPAIR_ATTEMPTS = ${MAX_REPAIR_ATTEMPTS}"
echo "TASK_IDS        = ${TASK_IDS:-<full 150-task corpus>}"
echo "RETRY_FROM_AUDIT= ${RETRY_FROM_AUDIT:-<none: first pass>}"
echo ""

for SHARD in $(seq 0 $((SHARD_COUNT - 1))); do
  CONTAINER_NAME="fpt26-${RUN_LABEL}-s${SHARD}"
  OUTPUT_DIR="/workspace/runs/${RUN_LABEL}/shard_0${SHARD}"
  LOG_HOST="/tmp/${RUN_LABEL}_s${SHARD}.log"

  echo "--- shard ${SHARD}: ${CONTAINER_NAME} -> ${OUTPUT_DIR}"

  docker run -d \
    --name "${CONTAINER_NAME}" \
    --env-file "${ENV_FILE}" \
    -e PYTHONPATH=/workspace:/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -e FPT26_LLM_TIMEOUT_SECONDS="${LLM_TIMEOUT_S}" \
    -e FPT26_MAX_REPAIR_ATTEMPTS="${MAX_REPAIR_ATTEMPTS}" \
    -v "${HOST_REPO}:/workspace" \
    -v /tools/Xilinx:/tools/Xilinx:ro \
    -w /workspace/fpt26-agent-v3 \
    "${IMAGE}" \
    bash -lc "source /tools/Xilinx/2025.2/Vitis/settings64.sh && \
      python3 -m scoring.run_p0_real_api_shard \
        --submission-task-root ${RELEASE_ROOT}/public_agent \
        --evaluator-task-root ${RELEASE_ROOT}/evaluator_private \
        --output-root ${OUTPUT_DIR} \
        --shard-index ${SHARD} \
        --shard-count ${SHARD_COUNT} \
        --task-timeout-s ${TASK_TIMEOUT_S} \
        --backend ${BACKEND} \
        --model ${MODEL_ID} \
        ${TASK_ID_ARGS[*]} ${RETRY_ARGS[*]}" > /dev/null

  echo "    logs: docker logs -f ${CONTAINER_NAME}  (tee: ${LOG_HOST})"
done

echo ""
echo "All shards launched. RUN_LABEL=${RUN_LABEL}"
echo "${RUN_LABEL}" > /tmp/current_track_a_v2_run_label.txt
