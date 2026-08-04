#!/bin/bash
# Batch verification of ALL optimization tasks
# Run from repo root
set -euo pipefail

RESULTS_FILE="/tmp/opt_batch_results_$(date +%Y%m%d_%H%M%S).txt"
echo "task,q_hw_before,q_hw_after,improved,winner_strategy" > "$RESULTS_FILE"

run_one() {
    local task_path="$1"
    local task_name="$2"

    echo "=== $task_name ==="
    output=$(docker run --rm \
      -v /home/chen1/projects/fpt26_new:/workspace \
      -v /tools/Xilinx:/tools/Xilinx:ro \
      --env-file /tmp/fpt26.env \
      -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
      -e PYTHONDONTWRITEBYTECODE=1 \
      -w /workspace fpt26-agent-v3:latest \
      bash -c "source /tools/Xilinx/Vitis/2025.2/settings64.sh && \
        python3 -m agent.main \
          --task '${task_path}' \
          --mode optimize \
          --output-root runs/opt_batch_v4 \
          --backend custom \
          --competition \
          --max-optimization-rounds 3 \
          --scoring-profile balanced" 2>&1)

    q_hw=$(echo "$output" | grep "strategy competition final:" | tail -1 | grep -oP 'Q_HW=\K[0-9.]+' || echo "0.75")
    improved=$(echo "$output" | grep "strategy competition final:" | tail -1 | grep -c "Q_HW=0\.[8-9]" || echo "0")
    winner=$(echo "$output" | grep "strategy competition final:" | tail -1 | grep -oP 'winner=\K\S+' || echo "none")

    echo "${task_name},0.75,${q_hw},${improved},${winner}" >> "$RESULTS_FILE"
    echo "  Q_HW=${q_hw} improved=${improved} winner=${winner}"
}

# Official task
run_one "/workspace/tasks/official/dotProduct_optimize" "dotProduct_optimize"

# All 25 track_a_150 optimization tasks
for i in $(seq -w 1 25); do
    task_dir=$(ls -d /home/chen1/projects/fpt26_new/tasks/track_a_150/qor_optimization__${i}__* 2>/dev/null || echo "")
    if [ -n "$task_dir" ]; then
        task_name=$(basename "$task_dir")
        run_one "/workspace/tasks/track_a_150/${task_name}" "$task_name"
    fi
done

echo ""
echo "=== SUMMARY ==="
total=$(tail -n +2 "$RESULTS_FILE" | wc -l)
above_76=$(awk -F, 'NR>1 && $3+0 > 0.80 {count++} END {print count+0}' "$RESULTS_FILE")
pct=$(echo "scale=1; $above_76 / $total * 100" | bc -l)
echo "Total: $total | Q_HW > 0.80: $above_76 | Rate: ${pct}%"
echo "Results: $RESULTS_FILE"
