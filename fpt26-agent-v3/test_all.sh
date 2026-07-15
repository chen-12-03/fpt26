#!/bin/bash
set -euo pipefail
export VITIS=/tools/Xilinx/Vitis/2025.2
export VITIS_MOUNT_ROOT=/tools/Xilinx
export FPT26_REPO_ROOT=/home/chen1/projects/fpt26_new
export XILINX_XRT=/opt/xilinx/xrt
export HLS_PART=xcu55c-fsvh2892-2L-e
export LLM4HLS_VITIS_HLS_ROOT=/tools/Xilinx/Vitis/2025.2
export LLM4HLS_PART=xcu55c-fsvh2892-2L-e
export FPT26_LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export FPT26_LLM_MODEL="qwen3-coder-plus"
export FPT26_LLM_API_KEY="${FPT26_LLM_API_KEY:-sk-your-api-key-here}"
export FPT26_LLM_TIMEOUT_SECONDS=120
export FPT26_LLM_MAX_OUTPUT_TOKENS=8192
export FPT26_LLM_TEMPERATURE=0
export HOST_UID=$(id -u)
export HOST_GID=$(id -g)
export HOME=$HOME
COMPOSE_FILE=/home/chen1/projects/fpt26_new/fpt26-agent-v2/docker-compose.yml

run_test() {
    local name="$1"
    local task="$2"
    local mode="$3"
    local extra="${4:-}"
    echo "===== $name ====="
    docker compose -f "$COMPOSE_FILE" run --rm --entrypoint "" agent bash -c "
pip3 install -q tomli 2>/dev/null
source /tools/Xilinx/Vitis/2025.2/settings64.sh
source /opt/xilinx/xrt/setup.sh
cd /workspace/fpt26-agent-v2
python3 -m agent.main --task $task --mode $mode $extra
" || echo "[$name] exit code: $?"
    echo ""
}

run_test "TASK 1: projection_bugfix (repair)" "tasks/projection_bugfix" "repair" "--max-repair-attempts 2"
run_test "TASK 2: dotProduct_optimize (optimize)" "tasks/dotProduct_optimize" "optimize" "--max-optimization-rounds 2"
run_test "TASK 3: residual_stream_deadlock (structural)" "tasks/residual_stream_deadlock" "structural" "--max-structural-attempts 2"
echo "===== ALL DONE ====="
