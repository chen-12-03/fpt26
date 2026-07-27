#!/usr/bin/env bash

set -o pipefail

# 无论从哪个目录调用，都切换到脚本所在的项目根目录。
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

TASK_PATH="${TASK_PATH:-tasks/generated/c2hlsc__des}"
SCORING_PROFILE="${SCORING_PROFILE:-balanced}"
RUN_LABEL="${RUN_LABEL:-submission_c2hlsc_des_$(date +%Y%m%d_%H%M%S)}"
RUN_ROOT="${RUN_ROOT:-runs/${RUN_LABEL}}"
LOG_FILE="${LOG_FILE:-runs/${RUN_LABEL}.terminal.log}"

VITIS_SETTINGS="/tools/Xilinx/Vitis/2025.2/settings64.sh"
ENV_FILE="/tmp/fpt26.env"

if [[ ! -f "$VITIS_SETTINGS" ]]; then
  echo "错误：找不到 Vitis 环境脚本：$VITIS_SETTINGS" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "错误：找不到 Agent 环境变量文件：$ENV_FILE" >&2
  exit 1
fi

if [[ ! -d "fpt26-agent-v3" ]]; then
  echo "错误：找不到目录：$SCRIPT_DIR/fpt26-agent-v3" >&2
  exit 1
fi

if [[ ! -e "$TASK_PATH" ]]; then
  echo "错误：找不到任务：$SCRIPT_DIR/$TASK_PATH" >&2
  exit 1
fi

mkdir -p runs

export LOCPATH=/tmp/fpt26_locale_dirs/usr/lib/locale

# shellcheck disable=SC1091
source "$VITIS_SETTINGS"

export LD_LIBRARY_PATH="/tmp/fpt26_vitis_tinfo5_qemu:/tools/Xilinx/2025.2/Vitis/lib/lnx64.o/Ubuntu/22:${LD_LIBRARY_PATH:-}"

set -a
# shellcheck disable=SC1091
source "$ENV_FILE"
set +a

echo "task=$TASK_PATH"
echo "run_root=$RUN_ROOT"
echo "terminal_log=$LOG_FILE"
echo

PYTHONPATH=fpt26-agent-v3:. python3 -m agent.main \
  --task "$TASK_PATH" \
  --mode auto \
  --backend custom \
  --output-root "$RUN_ROOT" \
  --scoring-profile "$SCORING_PROFILE" \
  --color always \
  2>&1 | tee "$LOG_FILE"

RUN_EXIT=${PIPESTATUS[0]}

echo
echo "run_root=$RUN_ROOT"
echo "terminal_log=$LOG_FILE"
echo "exit_code=$RUN_EXIT"

exit "$RUN_EXIT"
