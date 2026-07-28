# Agent 快速上手

只保留最常用的环境配置和运行命令。以下命令默认在仓库根目录执行：

```bash
cd /home/chen1/projects/fpt26_new
```

## 1. 换机与环境配置

仓库内的 Dockerfile 已包含 Agent、Python 和 Vitis Linux runtime
依赖。首次运行若找不到 `fpt26-agent-v3:latest`，入口脚本会自动从
Dockerfile 构建，不再依赖旧设备预先制作的 `vitis_runtime:2025.2`
本地镜像。

仍有三项不能随 Git 仓库分发：

- x86_64 Linux/WSL 上可用的 Docker；
- 宿主机安装的 AMD Vitis 2025.2 及有效许可证；
- OpenRouter 或其他兼容后端的 API key。

默认检查位置：

```bash
docker version
test -f /tmp/fpt26.env
test -f /tools/Xilinx/2025.2/Vitis/settings64.sh
test -d tasks/track_a_150
```

若 Vitis 安装在其他路径，设置：

```bash
export FPT26_VITIS_SETTINGS=/opt/amd/Vitis/2025.2/settings64.sh
```

入口会把对应的安装根目录按原绝对路径只读挂载进容器。运行完整自检：

```bash
./fpt26-agent-v3/run-task-cli --doctor --backend openrouter
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

推荐使用统一 CLI。入口脚本默认只在宿主机组装一次 `docker run`，task
发现、Vitis HLS、agent、LLM 调用和评分都在该容器内执行；无需在宿主机
提前 `source settings64.sh`。CLI 会按 task ID 查找路径，自动加载
`/tmp/fpt26.env`、自动检测 Vitis `settings64.sh`，生成带时间戳的 run
root，并把无 ANSI 控制符的完整终端输出写入
`runs/*.terminal.log`。

```bash
./fpt26-agent-v3/run-task-cli \
  --task-id compile_repair__16__amd_intro__interface_memory_burst_rw \
  --mode auto \
  --backend openrouter \
  --model "${MODEL}" \
  --max-optimization-rounds 2
```

也可以直接指定路径：

```bash
./fpt26-agent-v3/run-task-cli \
  --task-path tasks/track_a_150/compile_repair__16__amd_intro__interface_memory_burst_rw \
  --mode auto --backend openrouter --model "${MODEL}"
```

查看任务、预览配置或进入交互设置：

```bash
./fpt26-agent-v3/run-task-cli --list-tasks burst_rw
./fpt26-agent-v3/run-task-cli --task-id compile_repair__16__amd_intro__interface_memory_burst_rw --dry-run
./fpt26-agent-v3/run-task-cli --interactive
```

配置面板的 `Runtime` 会显示 `docker`，`--dry-run` 会在容器中打印实际
agent 命令但不执行 task。镜像默认是 `fpt26-agent-v3:latest`，可用
`--image <image>` 或 `FPT26_AGENT_IMAGE` 覆盖。仅调试 CLI 本身时才应
显式使用 `--runtime local`；通过入口脚本调用时，即使选择 local，入口
脚本本身仍会把整个 CLI 放进同一个 Docker 容器。

自动构建可用 `FPT26_AUTO_BUILD=0` 禁用。基础镜像可用
`FPT26_AGENT_BASE_IMAGE` 覆盖；默认是公开的
`xilinx/xilinx_runtime_base:alveo-2023.2-ubuntu-22.04`。

高级参数仍直接透传到 `agent.main`，包括 `--budget`、`--competition`、
`--max-repair-attempts`、`--max-optimization-rounds`、
`--max-structural-attempts` 和 `--scoring-profile`。

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
    -e PYTHONPATH=/workspace:/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -v /home/chen1/projects/fpt26_new:/workspace \
    -v /tools/Xilinx:/tools/Xilinx:ro \
    -w /workspace/fpt26-agent-v3 \
    fpt26-agent-v3:latest \
    bash -lc "source /tools/Xilinx/2025.2/Vitis/settings64.sh && python3 -m scoring.run_p0_real_api_shard \
      --task-root /workspace/tasks/track_a_150 \
      --output-root /workspace/${RUN_ROOT}/shard_0${SHARD} \
      --shard-index ${SHARD} --shard-count 3 --task-timeout-s 3600 \
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
