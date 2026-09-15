# FPT'26 Track-A：基于已验证候选回路的预算约束 LLM 辅助 HLS

本仓库发布 Verified-Candidate Loop（VCL）智能体、冻结的 Track-A v4
语料、评分代码和论文证据。Submission 与 Evaluator 在独立 Docker 容器
中运行。Submission 只能读取公开任务；Evaluator 无网络且不接收 API
凭据。

## 快速开始

环境要求：Docker 24+、amd64、Vitis 2025.2 和可用的兼容 API。Vitis
默认路径为 `/tools/Xilinx/2025.2/Vitis`，也可通过 `VITIS_SDK` 指定具有
相同目录结构的安装。

```bash
export VITIS_SDK=/tools/Xilinx/2025.2/Vitis
export FPT26_REPO_ROOT="$PWD" HOST_UID=$(id -u) HOST_GID=$(id -g)
docker compose -f fpt26-agent-v3/docker-compose.yml build

read -s -p "粘贴 OpenRouter API Key: " KEY && echo
cat > /tmp/fpt26.env << EOF
OPENROUTER_API_KEY=${KEY}
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
LLM4HLS_MODEL=qwen/qwen3.6-27b
EOF

RUN_LABEL=demo_qwen36 \
MODEL_ID=qwen/qwen3.6-27b \
ENV_FILE=/tmp/fpt26.env BACKEND=openrouter \
SHARD_COUNT=1 SHARD_INDEX=0 TASK_IDS=ta2_qo_001 \
./run_track_a_v4_split.sh
```

三模型对应的 provider model ID：

```text
deepseek/deepseek-v4-pro
qwen/qwen3.5-122b-a10b
qwen/qwen3.6-27b
```

## 目录结构

```text
fpt26-agent-v3/                       智能体和评分代码
fpt26-harness/                        Vitis 工具封装
releases/track_a_150_v4_20260911/
  public_agent/                       Submission 只读挂载
  evaluator_private/                  仅 Evaluator 挂载
technical-paper/                      论文源码、最终 PDF 和证据
tools/                                审计与汇总工具
run_track_a_v4_split.sh               物理隔离的运行入口
runs/                                 被 Git 忽略的运行输出
```

## 任务模式

| 模式 | 功能 |
|---|---|
| `auto` | 从 `task.toml` 自动选择流程 |
| `generate` | 从桩代码生成内核 |
| `repair` | 修复编译、综合或功能错误 |
| `structural` | 修复 C/RTL CoSim 问题 |
| `optimize` | 优化 QoR |
| `full` | 执行完整修复与优化流程 |

## 完整评估

```bash
RUN_LABEL=my_qwen36_full150 \
MODEL_ID=qwen/qwen3.6-27b \
ENV_FILE=/tmp/fpt26.env BACKEND=openrouter \
SHARD_COUNT=3 SHARD_INDEX=all \
./run_track_a_v4_split.sh
```

挂载边界、断点续跑、输出结构和三模型命令见
[`docs/track-a-v4-isolated-reproduction.md`](docs/track-a-v4-isolated-reproduction.md)。

## 复现论文数据

论文数据复现不需要 API key 或 Vitis license。下面的离线命令验证两份
LaTeX 宏文件与 canonical v4 JSON 完全一致：

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace \
  fpt26-agent-v3:latest \
  python3 technical-paper/scripts/update_results.py --check
```

需要重新生成宏文件时，使用可写挂载并去掉 `--check`：

```bash
docker run --rm --network none \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/workspace" -w /workspace \
  fpt26-agent-v3:latest \
  python3 technical-paper/scripts/update_results.py
```

生成器只读取
`technical-paper/evidence/track_a_v4_three_model_paper_data_20260913.json`
和冻结的 evaluator mapping，不读取 `runs/` 或旧任务目录。托管模型输出
具有非确定性，因此重新运行完整三模型评估可能产生不同候选代码。

论文编译命令：

```bash
cd technical-paper
pdflatex main && bibtex main && pdflatex main && pdflatex main
```

## 许可证

本仓库原创代码采用 [MIT License](LICENSE)。冻结语料保留十个上游来源
各自的许可证。完整文本和任务级出处见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、[`LICENSES/`](LICENSES/)
和 evaluator bundle 中的 `EVALUATOR_MAPPING.json`。
