# Agent 快速上手

只保留最常用的环境配置和运行命令。以下命令默认在仓库根目录执行：

```bash
cd /home/chen1/projects/fpt26_new
```

## 1. 环境配置

检查必需文件和镜像：

```bash
docker image inspect fpt26-agent-v3:latest >/dev/null
test -f /tmp/fpt26.env
test -f /tools/Xilinx/2025.2/Vitis/settings64.sh
test -d tasks/track_a_150
```

`/tmp/fpt26.env` 至少需要：

```bash
OPENROUTER_API_KEY=sk-...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

选择模型：

```bash
export MODEL='deepseek/deepseek-v4-pro'
```

可替换为：

```bash
export MODEL='qwen/qwen3.5-122b-a10b'
export MODEL='qwen/qwen3.6-27b'
```

## 2. 单个 task 运行

按 `run_agent.sh` 的方式前台运行，终端实时输出，同时写入 `runs/*.terminal.log`：

```bash
export TASK_ID='compile_repair__16__amd_intro__interface_memory_burst_rw'
export TASK_PATH="tasks/track_a_150/${TASK_ID}"
export RUN_LABEL="single_${TASK_ID}_$(date +%Y%m%d_%H%M%S)"
export RUN_ROOT="runs/${RUN_LABEL}"
export LOG_FILE="runs/${RUN_LABEL}.terminal.log"

export LOCPATH=/tmp/fpt26_locale_dirs/usr/lib/locale
source /tools/Xilinx/2025.2/Vitis/settings64.sh
export LD_LIBRARY_PATH="/tmp/fpt26_vitis_tinfo5_qemu:/tools/Xilinx/2025.2/Vitis/lib/lnx64.o/Ubuntu/22:${LD_LIBRARY_PATH:-}"

set -a
source /tmp/fpt26.env
set +a

export LLM4HLS_MODEL="${MODEL}"

PYTHONPATH=fpt26-agent-v3:. python3 -m agent.main \
  --task "${TASK_PATH}" \
  --mode auto \
  --backend openrouter \
  --output-root "${RUN_ROOT}" \
  --scoring-profile balanced \
  --color always \
  2>&1 | tee "${LOG_FILE}"

echo "run_root=${RUN_ROOT}"
echo "terminal_log=${LOG_FILE}"
```

## 3. Track-A 150 三分片运行

`docker-compose.yml` 只有一个 `agent` 服务；三分片是手动启动 3 个独立容器。分片规则是：

```text
index % shard_count == shard_index
```

启动前设置输出目录：

```bash
export RUN_LABEL="track_a_150_openrouter_$(date +%Y%m%d_%H%M%S)"
export RUN_ROOT="runs/${RUN_LABEL}"
```

一条命令启动 3 个 shard：

```bash
for SHARD in 0 1 2; do
  docker run -d --name "fpt26-${RUN_LABEL}-s${SHARD}" --env-file /tmp/fpt26.env \
    -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -v /home/chen1/projects/fpt26_new:/workspace \
    -v /tools/Xilinx:/tools/Xilinx:ro \
    -w /workspace/fpt26-agent-v3 \
    fpt26-agent-v3:latest \
    bash -lc "source /tools/Xilinx/2025.2/Vitis/settings64.sh && python3 -m scoring.run_p0_real_api_shard \
      --task-root /workspace/tasks/track_a_150 \
      --output-root /workspace/${RUN_ROOT}/shard_0${SHARD} \
      --shard-index ${SHARD} --shard-count 3 --task-timeout-s 7200 \
      --backend openrouter --model ${MODEL}"
done
```

## 4. 查看进度

容器状态：

```bash
docker ps -a --filter "name=fpt26-${RUN_LABEL}" --format 'table {{.Names}}\t{{.Status}}'
```

日志：

```bash
docker logs --tail 80 "fpt26-${RUN_LABEL}-s0"
docker logs --tail 80 "fpt26-${RUN_LABEL}-s1"
docker logs --tail 80 "fpt26-${RUN_LABEL}-s2"
```

汇总完成数：

```bash
python3 - <<'PY'
import json, pathlib, os
root = pathlib.Path(os.environ["RUN_ROOT"])
total = 0
outcomes = {}
for p in sorted(root.glob("shard_*/shard_summary.json")):
    d = json.loads(p.read_text())
    n = int(d.get("completed_record_count") or 0)
    total += n
    for k, v in (d.get("outcome_counts") or {}).items():
        outcomes[k] = outcomes.get(k, 0) + int(v)
    print(p.parent.name, f"{n}/{d.get('selected_task_count')}", d.get("outcome_counts"))
print("TOTAL", f"{total}/150", outcomes)
PY
```

## 5. 生成最终报告

```bash
python3 tools/finalize_track_a_150.py \
  --corpus-manifest runs/track_a_150_initial_acceptance_headers_20260727/accepted_manifest.json \
  --gate-matrix runs/track_a_150_initial_acceptance_headers_20260727/initial_gate_matrix.json \
  --run-root "${RUN_ROOT}" \
  --shard-summary "${RUN_ROOT}/shard_00/shard_summary.json" \
  --shard-summary "${RUN_ROOT}/shard_01/shard_summary.json" \
  --shard-summary "${RUN_ROOT}/shard_02/shard_summary.json"

python3 tools/write_track_a_final_summary.py \
  --final-report "${RUN_ROOT}/final_report.json" \
  --output "${RUN_ROOT}/FINAL_SUMMARY.md"
```
