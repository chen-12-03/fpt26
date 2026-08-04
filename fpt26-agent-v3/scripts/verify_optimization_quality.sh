#!/bin/bash
# Verify optimization quality: run all qor_optimization tasks through
# the real Aliyun API (custom backend) and measure scores.
#
# Prerequisites:
#   1. Docker image fpt26-agent-v3:latest built
#   2. /tmp/fpt26.env with FPT26_LLM_BASE_URL, FPT26_LLM_API_KEY, FPT26_LLM_MODEL
#   3. Vitis 2025.2 at /tools/Xilinx/Vitis/2025.2
#
# Usage: bash scripts/verify_optimization_quality.sh
#
# Target: >70% of optimization tasks must score >76 on real API.

set -euo pipefail

REPO_ROOT="$(realpath "$(dirname "$0")/../..")"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RUN_NAME="opt_quality_verify_${TIMESTAMP}"
TASK_ROOT="/workspace/tasks/track_a_150"
OFFICIAL_TASK="/workspace/tasks/official/dotProduct_optimize"

echo "=== Optimization Quality Verification: ${RUN_NAME} ==="

# Collect optimization task IDs (qor_optimization__XX)
OPT_TASKS=$(docker run --rm \
  -v "${REPO_ROOT}:/workspace" \
  -w /workspace fpt26-agent-v3:latest \
  bash -c "ls ${TASK_ROOT} | grep '^qor_optimization' | sort")

OPT_COUNT=$(echo "${OPT_TASKS}" | wc -l)
echo "Found ${OPT_COUNT} optimization tasks in track_a_150"
echo "Plus 1 official task: dotProduct_optimize"
TOTAL=$((OPT_COUNT + 1))
echo "Total: ${TOTAL} tasks"

PASS_COUNT=0
FAIL_COUNT=0
SCORES_FILE="/tmp/opt_scores_${TIMESTAMP}.txt"
> "${SCORES_FILE}"

run_task() {
    local task_path="$1"
    local task_name="$2"
    local label="$3"

    echo ""
    echo "--- [${label}] ${task_name} ---"

    set +e
    docker run --rm \
      -v "${REPO_ROOT}:/workspace" \
      -v /tools/Xilinx:/tools/Xilinx:ro \
      --env-file /tmp/fpt26.env \
      -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
      -e PYTHONDONTWRITEBYTECODE=1 \
      -w /workspace fpt26-agent-v3:latest \
      bash -c "source /tools/Xilinx/Vitis/2025.2/settings64.sh && \
        python3 -m agent.main \
          --task '${task_path}' \
          --mode optimize \
          --output-root 'runs/${RUN_NAME}' \
          --backend custom \
          --competition \
          --max-optimization-rounds 3 \
          --scoring-profile balanced" 2>&1 | tee "/tmp/opt_log_${task_name}.txt"
    local exit_code=$?
    set -e

    # Extract score from the run report
    local report="runs/${RUN_NAME}/${task_name}/run_report.json"
    if [ -f "${REPO_ROOT}/${report}" ]; then
        local score=$(python3 -c "
import json
with open('${REPO_ROOT}/${report}') as f:
    data = json.load(f)
score = data.get('evaluation', {}).get('scorecard', {}).get('score', 0)
print(score)
" 2>/dev/null || echo "0")
        local passed="FAIL"
        if [ "$(echo "${score} > 76" | bc -l 2>/dev/null || echo 0)" = "1" ]; then
            passed="PASS"
            PASS_COUNT=$((PASS_COUNT + 1))
        else
            FAIL_COUNT=$((FAIL_COUNT + 1))
        fi
        echo "${task_name}: score=${score} -> ${passed}" | tee -a "${SCORES_FILE}"
    else
        echo "${task_name}: NO_REPORT (exit=${exit_code})" | tee -a "${SCORES_FILE}"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

# Run official task first (fastest feedback)
run_task "${OFFICIAL_TASK}" "dotProduct_optimize" "official"

# Run generated optimization tasks
for task in ${OPT_TASKS}; do
    run_task "${TASK_ROOT}/${task}" "${task}" "generated"
done

# Summary
echo ""
echo "========================================"
echo "Verification Complete: ${RUN_NAME}"
echo "========================================"
PASS_RATE=$(echo "scale=2; ${PASS_COUNT} / ${TOTAL} * 100" | bc -l 2>/dev/null || echo "0")
echo "Total tasks: ${TOTAL}"
echo "Score > 76:  ${PASS_COUNT}"
echo "Score <= 76: ${FAIL_COUNT}"
echo "Pass rate:   ${PASS_RATE}%"
echo "Target:      >70%"
if [ "$(echo "${PASS_RATE} > 70" | bc -l 2>/dev/null || echo 0)" = "1" ]; then
    echo "RESULT: PASS - target met!"
else
    echo "RESULT: NOT YET - target not met (${PASS_RATE}% <= 70%)"
fi
echo "Scores saved to: ${SCORES_FILE}"
