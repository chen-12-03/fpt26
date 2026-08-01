#!/usr/bin/env bash
# Continue re-running remaining API-failed tasks.
# Usage: ./rerun_continue.sh <model>
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${FPT26_AGENT_IMAGE:-fpt26-agent-v3:latest}"
TASK_ROOT_CONTAINER="/workspace/tasks/track_a_150"

MODEL="$1"
case "$MODEL" in
    dsv4)
        ENV_FILE="/tmp/fpt26_or_dsv4.env"
        MODEL_ID="deepseek/deepseek-v4-pro"
        RUN_DIR="runs/track_a_150_or_dsv4_20260728_200507"
        ;;
    qwen36)
        ENV_FILE="/tmp/fpt26_or_qwen36.env"
        MODEL_ID="qwen/qwen3.6-27b"
        RUN_DIR="runs/track_a_150_or_qwen36_20260729_053353"
        ;;
    *)
        echo "Usage: $0 {dsv4|qwen36}" >&2; exit 2 ;;
esac

RETRY_FILE="$REPO_ROOT/runs/retry_${MODEL}_remaining.json"
CONTAINER_OUTPUT="/workspace/$RUN_DIR/re_run"

TOTAL=$(python3 -c "import json; print(len(json.load(open('$RETRY_FILE'))['retry_task_ids']))")
echo "[$MODEL] $TOTAL tasks remaining"

mapfile -t TASK_IDS < <(python3 -c "
import json
for tid in json.load(open('$RETRY_FILE'))['retry_task_ids']:
    print(tid)
")

PASSED=0; FAILED=0; ORDINAL=0
for TASK_ID in "${TASK_IDS[@]}"; do
    ORDINAL=$((ORDINAL + 1))
    TASK_DIR="$TASK_ROOT_CONTAINER/$TASK_ID"
    LOG_HOST="/tmp/rerun_${MODEL}_${TASK_ID}.log"

    echo -n "[$MODEL] [$ORDINAL/$TOTAL] $TASK_ID ... "

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
            --task "$TASK_DIR" \
            --mode auto \
            --backend openrouter \
            --output-root "$CONTAINER_OUTPUT" \
            --quiet \
        2>&1 | tee "$LOG_HOST"
    RC=${PIPESTATUS[0]}
    set -e

    if [[ $RC -eq 0 ]]; then
        echo "  -> OK"; PASSED=$((PASSED + 1))
    else
        echo "  -> FAIL (rc=$RC)"; FAILED=$((FAILED + 1))
    fi
done

echo "[$MODEL] Complete: $PASSED passed, $FAILED failed (of $TOTAL)"
