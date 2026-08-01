#!/usr/bin/env bash
set -euo pipefail
SHARD="$1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${FPT26_AGENT_IMAGE:-fpt26-agent-v3:latest}"

RETRY="$REPO_ROOT/runs/retry_qwen36_shard_${SHARD}.json"
ENV_FILE="/tmp/fpt26_or_qwen36.env"
MODEL_ID="qwen/qwen3.6-27b"
RUN_DIR="runs/track_a_150_or_qwen36_20260729_053353"
OUT="/workspace/$RUN_DIR/re_run"

TOTAL=$(python3 -c "import json; print(len(json.load(open('$RETRY'))['retry_task_ids']))")
echo "[qwen36/shard$SHARD] $TOTAL tasks"

mapfile -t TIDS < <(python3 -c "import json
for tid in json.load(open('$RETRY'))['retry_task_ids']: print(tid)")

P=0; F=0; O=0
for TID in "${TIDS[@]}"; do
    O=$((O+1))
    echo -n "[s$SHARD] [$O/$TOTAL] $TID ... "
    set +e
    docker run --rm \
        -e PYTHONPATH=/workspace:/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -e "LLM4HLS_MODEL=$MODEL_ID" \
        --env-file "$ENV_FILE" \
        -v "$REPO_ROOT:/workspace" \
        -v /tools/Xilinx:/tools/Xilinx:ro \
        -w /workspace/fpt26-agent-v3 \
        "$IMAGE" \
        python3 -m agent.main \
            --task "/workspace/tasks/track_a_150/$TID" \
            --mode auto --backend openrouter \
            --output-root "$OUT" --quiet \
        2>&1 | tee "/tmp/rerun_qwen36_s${SHARD}_${TID}.log"
    RC=${PIPESTATUS[0]}
    set -e
    if [[ $RC -eq 0 ]]; then echo "  -> OK"; P=$((P+1)); else echo "  -> FAIL (rc=$RC)"; F=$((F+1)); fi
done
echo "[s$SHARD] Done: $P passed, $F failed (of $TOTAL)"
