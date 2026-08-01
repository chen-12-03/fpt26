#!/usr/bin/env bash
# Re-evaluate re-run tasks that completed but lack evaluator scores.
# Usage: ./reeval_tasks.sh <model_shard>   e.g. ./reeval_tasks.sh dsv4_0
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${FPT26_AGENT_IMAGE:-fpt26-agent-v3:latest}"
TASK_ROOT="/workspace/tasks/track_a_150"

MODEL_SHARD="$1"

case "$MODEL_SHARD" in
    dsv4_0)
        ENV_FILE="/tmp/fpt26_or_dsv4.env"
        MODEL_ID="deepseek/deepseek-v4-pro"
        RUN_DIR="runs/track_a_150_or_dsv4_20260728_200507"
        RETRY_FILE="$REPO/runs/reeval_dsv4.json"
        ;;
    qwen36_0|qwen36_1|qwen36_2|qwen36_3)
        ENV_FILE="/tmp/fpt26_or_qwen36.env"
        MODEL_ID="qwen/qwen3.6-27b"
        RUN_DIR="runs/track_a_150_or_qwen36_20260729_053353"
        RETRY_FILE="$REPO/runs/reeval_qwen36.json"
        SHARD_IDX="${MODEL_SHARD#qwen36_}"
        ;;
    *)
        echo "Usage: $0 {dsv4_0|qwen36_0|qwen36_1|qwen36_2|qwen36_3}" >&2
        exit 2 ;;
esac

# Read task list and optionally filter by shard
if [[ "$MODEL_SHARD" == dsv4_* ]]; then
    mapfile -t TASKS < <(python3 -c "import json; [print(t) for t in json.load(open('$RETRY_FILE'))['tasks']]")
else
    mapfile -t TASKS < <(python3 -c "
import json
tasks = json.load(open('$RETRY_FILE'))['tasks']
shard = $SHARD_IDX
for i, t in enumerate(tasks):
    if i % 4 == shard:
        print(t)
")
fi

RE_RUN="/workspace/$RUN_DIR/re_run"
EVAL_OUT="/workspace/$RUN_DIR/re_eval"
TOTAL=${#TASKS[@]}
P=0; F=0; O=0

echo "[${MODEL_SHARD}] $TOTAL tasks"

for TID in "${TASKS[@]}"; do
    O=$((O+1))
    TASK_DIR="$TASK_ROOT/$TID"
    # Find final kernel
    FINAL_KERNEL=$(ls "$REPO/$RUN_DIR/re_run/$TID"/final_*.cpp 2>/dev/null | head -1)
    if [[ -z "$FINAL_KERNEL" ]]; then
        echo "[${MODEL_SHARD}] [$O/$TOTAL] $TID — SKIP (no final kernel)"
        continue
    fi
    FINAL_KERNEL_CONTAINER="/workspace/$RUN_DIR/re_run/$TID/$(basename "$FINAL_KERNEL")"
    SUBMISSION_EV="$RE_RUN/$TID/submission_evidence.json"

    echo -n "[${MODEL_SHARD}] [$O/$TOTAL] $TID ... "

    set +e
    docker run --rm \
        -e PYTHONPATH=/workspace:/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -e "LLM4HLS_MODEL=$MODEL_ID" \
        --env-file "$ENV_FILE" \
        -v "$REPO:/workspace" \
        -v /tools/Xilinx:/tools/Xilinx:ro \
        -w /workspace/fpt26-agent-v3 \
        "$IMAGE" \
        python3 -m agent.main \
            --task "$TASK_DIR" \
            --run-role evaluator \
            --final-kernel "$FINAL_KERNEL_CONTAINER" \
            --submission-evidence "$SUBMISSION_EV" \
            --output-root "$EVAL_OUT" \
            --quiet \
        2>&1 | tail -3
    RC=${PIPESTATUS[0]}
    set -e

    if [[ $RC -eq 0 ]]; then
        echo "  -> OK"
        P=$((P+1))
    else
        echo "  -> FAIL (rc=$RC)"
        F=$((F+1))
    fi
done

echo "[${MODEL_SHARD}] Done: $P passed, $F failed (of $TOTAL)"
