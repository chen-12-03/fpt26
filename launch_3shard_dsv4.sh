#!/bin/bash
# Launch 3-shard DeepSeek V4 Pro run against 150 Track-A tasks
set -euo pipefail

RUN_LABEL="track_a_150_openrouter_dsv4_$(date +%Y%m%d_%H%M%S)"
MODEL="deepseek/deepseek-v4-pro"

echo "=== Launching 3 shards ==="
echo "RUN_LABEL=${RUN_LABEL}"
echo "MODEL=${MODEL}"
echo ""

for SHARD in 0 1 2; do
  CONTAINER_NAME="fpt26-${RUN_LABEL}-s${SHARD}"
  OUTPUT_DIR="/workspace/runs/${RUN_LABEL}/shard_0${SHARD}"
  echo "Starting shard ${SHARD}: container=${CONTAINER_NAME}"

  docker run -d \
    --name "${CONTAINER_NAME}" \
    --env-file /tmp/fpt26.env \
    -e PYTHONPATH=/workspace:/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -v /home/chen1/projects/fpt26_new:/workspace \
    -v /tools/Xilinx:/tools/Xilinx:ro \
    -w /workspace/fpt26-agent-v3 \
    fpt26-agent-v3:latest \
    bash -lc "source /tools/Xilinx/2025.2/Vitis/settings64.sh && \
      python3 -m scoring.run_p0_real_api_shard \
        --task-root /workspace/tasks/track_a_150 \
        --output-root ${OUTPUT_DIR} \
        --shard-index ${SHARD} \
        --shard-count 3 \
        --task-timeout-s 7200 \
        --backend openrouter \
        --model ${MODEL}"
done

echo ""
echo "All shards launched!"
echo "RUN_LABEL=${RUN_LABEL}"

# Write label for later use
echo "RUN_LABEL=${RUN_LABEL}" > /tmp/current_run_label.txt
