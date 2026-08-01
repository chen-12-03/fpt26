#!/usr/bin/env bash
# Re-run Track-A tasks whose API calls failed (partial or total).
#
# Usage:
#   ./rerun_api_failed.sh dsv4    # re-run deepseek-v4 failed tasks
#   ./rerun_api_failed.sh qwen35  # re-run qwen3.5 failed tasks
#   ./rerun_api_failed.sh qwen36  # re-run qwen3.6 failed tasks
#   ./rerun_api_failed.sh ALL     # re-run all three sequentially
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${FPT26_AGENT_IMAGE:-fpt26-agent-v3:latest}"
TASK_ROOT_CONTAINER="/workspace/tasks/track_a_150"

declare -A MODEL_CONFIG
MODEL_CONFIG[dsv4]="runs/track_a_150_or_dsv4_20260728_200507|/tmp/fpt26_or_dsv4.env|deepseek/deepseek-v4-pro"
MODEL_CONFIG[qwen35]="runs/track_a_150_or_qwen35_20260729_003822|/tmp/fpt26_or_qwen35.env|qwen/qwen3.5-122b-a10b"
MODEL_CONFIG[qwen36]="runs/track_a_150_or_qwen36_20260729_053353|/tmp/fpt26_or_qwen36.env|qwen/qwen3.6-27b"

run_model() {
    local MODEL="$1"
    local IFS='|'
    local cfg_parts=(${MODEL_CONFIG[$MODEL]})
    local RUN_DIR="${cfg_parts[0]}"
    local ENV_FILE="${cfg_parts[1]}"
    local MODEL_ID="${cfg_parts[2]}"

    local RETRY_FILE="$REPO_ROOT/runs/retry_${MODEL}.json"
    local CONTAINER_OUTPUT="/workspace/$RUN_DIR/re_run"
    local HOST_OUTPUT="$REPO_ROOT/$RUN_DIR/re_run"

    if [[ ! -f "$RETRY_FILE" ]]; then
        echo "[$MODEL] Retry manifest not found: $RETRY_FILE" >&2
        return 1
    fi

    local TASK_COUNT
    TASK_COUNT=$(python3 -c "import json; print(len(json.load(open('$RETRY_FILE'))['retry_task_ids']))")

    echo "============================================================"
    echo "[$MODEL] Model: $MODEL_ID"
    echo "[$MODEL] Tasks to retry: $TASK_COUNT"
    echo "[$MODEL] Output: $HOST_OUTPUT"
    echo "============================================================"

    if [[ $TASK_COUNT -eq 0 ]]; then
        echo "[$MODEL] No tasks to retry — skipping"
        return 0
    fi

    # Read task IDs
    mapfile -t TASK_IDS < <(python3 -c "
import json
for tid in json.load(open('$RETRY_FILE'))['retry_task_ids']:
    print(tid)
")

    local TOTAL=${#TASK_IDS[@]}
    local PASSED=0
    local FAILED=0
    local ORDINAL=0

    # Create output dir via Docker (runs as root inside container)
    docker run --rm \
        -v "$REPO_ROOT:/workspace" \
        -w /workspace \
        "$IMAGE" \
        mkdir -p "$CONTAINER_OUTPUT" 2>/dev/null || true

    for TASK_ID in "${TASK_IDS[@]}"; do
        ORDINAL=$((ORDINAL + 1))
        local TASK_DIR="$TASK_ROOT_CONTAINER/$TASK_ID"
        local LOG_HOST="/tmp/rerun_${MODEL}_${TASK_ID}.log"

        echo -n "[$MODEL] [$ORDINAL/$TOTAL] $TASK_ID ... "

        # Run inside Docker.  Output goes to a container-side file (root can
        # write to the mounted volume) and we tee a copy to host /tmp.
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
        local RC=${PIPESTATUS[0]}
        set -e

        if [[ $RC -eq 0 ]]; then
            echo "  -> OK"
            PASSED=$((PASSED + 1))
        else
            echo "  -> FAIL (rc=$RC)"
            FAILED=$((FAILED + 1))
        fi
    done

    echo "============================================================"
    echo "[$MODEL] Complete: $PASSED passed, $FAILED failed (of $TOTAL)"
    echo "[$MODEL] Logs in /tmp/rerun_${MODEL}_*.log"
    echo "============================================================"
    return $FAILED
}

# ── Main ──────────────────────────────────────────────────────────────────────
TARGET="${1:-ALL}"

if [[ "$TARGET" == "ALL" ]]; then
    ALL_FAILED=0
    for m in dsv4 qwen35 qwen36; do
        run_model "$m" || ALL_FAILED=$((ALL_FAILED + $?))
    done
    echo "ALL models complete."
    exit $(( ALL_FAILED > 0 ? 1 : 0 ))
elif [[ -n "${MODEL_CONFIG[$TARGET]:-}" ]]; then
    run_model "$TARGET"
else
    echo "Usage: $0 {dsv4|qwen35|qwen36|ALL}" >&2
    exit 2
fi
