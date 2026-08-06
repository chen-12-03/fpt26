# FPT'26 Track-A：基于已验证候选回路的预算约束下 LLM 辅助高层次综合

面向高层次综合（HLS）的自主 LLM 智能体，使用已验证候选回路（VCL）在明确的
模型和工具预算内修复并优化 FPGA 内核。智能体在 Docker 中运行，配合
Vitis 2025.2，目标平台为 Alveo U55C。

## 快速开始

```bash
# 0. 必填——设置本地 Vitis 2025.2 安装路径。
#    先在终端执行 ls "$VITIS_SDK/settings64.sh" 确认路径存在。
#    容器内固定期望 /tools/Xilinx/2025.2/Vitis/settings64.sh。
#    示例：
#      export VITIS_SDK=/tools/Xilinx/2025.2/Vitis          # AMD 默认（Linux/WSL）
#      export VITIS_SDK=/mnt/c/Xilinx/Vitis/2025.2/Vitis    # Windows（Docker Desktop 可能无法访问）
#
export VITIS_SDK=/tools/Xilinx/2025.2/Vitis   # <-- 修改这一行
ls "$VITIS_SDK/settings64.sh"                 # 验证路径存在

# 1. 构建 Docker 镜像（基础镜像为公开的 ubuntu:22.04）
export FPT26_REPO_ROOT=$(pwd) HOST_UID=$(id -u) HOST_GID=$(id -g)
docker compose -f fpt26-agent-v3/docker-compose.yml build

# 2. 创建环境文件，安全输入 API Key（输入时不显示，不入历史记录）
read -s -p "粘贴 OpenRouter API Key: " KEY && echo
cat > /tmp/fpt26.env << EOF
OPENROUTER_API_KEY=${KEY}
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
LLM4HLS_MODEL=qwen/qwen3.6-27b
EOF

# 3. 运行单个任务（将 Vitis 父目录挂载到 /tools/Xilinx）
VITIS_PARENT=$(dirname $(dirname "$VITIS_SDK"))   # 例如 /tools/Xilinx
docker run --rm \
  -v $(pwd):/workspace \
  -v "${VITIS_PARENT}:/tools/Xilinx:ro" \
  --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace:/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
  -e FPT26_CLI_IN_CONTAINER=1 \
  -w /workspace/fpt26-agent-v3 \
  fpt26-agent-v3:latest \
  bash -c "source /tools/Xilinx/2025.2/Vitis/settings64.sh && \
    python3 -m agent.run_cli \
      --task-root /workspace/tasks/track_a_150 \
      --task-id code_generation__01__amd_accel__performance_axi_burst_performance_src_test_kernel_maxi_256bit_1 \
      --mode auto \
      --backend openrouter \
      --output-root /workspace/runs/demo"
```

## 环境要求

| 组件 | 版本 / 说明 |
|------|------------|
| Docker | 24+，支持 `docker compose` |
| Vitis HLx | 2025.2 — **需自行提供安装，不随镜像分发** |
| Alveo U55C | `xcu55c-fsvh2892-2L-e` |
| Python | 3.10+（容器内） |
| LLM API | 任意兼容 OpenRouter 的端点 |

> **Vitis SDK 路径：** 设置 `VITIS_SDK` 为本地 Vitis 安装路径
> （例如 `/tools/Xilinx/2025.2/Vitis`）。其父目录（`/tools/Xilinx`）
> 以只读方式 bind-mount 到容器内。Docker 镜像仅含运行时库；完整 Vitis
> 工具链从宿主机挂载。

### API 配置

智能体通过环境变量支持任意 OpenAI 兼容 API：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENROUTER_API_KEY` | — | API 密钥（**必填**） |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | API 基础 URL |
| `LLM4HLS_MODEL` | — | 模型 ID，如 `qwen/qwen3.6-27b` |

论文中推荐的三模型评估配置：

```bash
# DeepSeek V4 Pro（1.6T MoE）
LLM4HLS_MODEL=deepseek/deepseek-v4-pro

# Qwen3.5 122B A10B（MoE，AWQ-4bit）
LLM4HLS_MODEL=qwen/qwen3.5-122b-a10b

# Qwen3.6 27B（Dense，FP8）
LLM4HLS_MODEL=qwen/qwen3.6-27b
```

## 目录结构

```
.
├── fpt26-agent-v3/          # 智能体源码
│   ├── agent/               #   核心（CLI、流水线、优化）
│   ├── scoring/             #   评分与批量运行基础设施
│   ├── Dockerfile           #   Docker 镜像定义
│   ├── docker-compose.yml   #   构建与运行时编排
│   ├── requirements.txt     #   Python 依赖（tomli, pytest）
│   └── run-agent.sh         #   便捷启动脚本
├── fpt26-harness/           # Vitis 工具调用封装
│   ├── run-vitis.sh         #   csim / synth / cosim 封装
│   └── vitis.dockerfile     #   参考 Vitis 镜像
├── tasks/track_a_150/       # 150 任务均衡基准
│   ├── candidate_manifest.json
│   ├── code_generation/     #   25 任务：桩 → 完整内核
│   ├── compile_repair/      #   25 任务：修复编译错误
│   ├── synthesis_repair/    #   25 任务：修复综合失败
│   ├── functional_repair/   #   25 任务：修复 CSim 失败
│   ├── structural_cosim_repair/  # 25 任务：修复 CoSim 死锁
│   └── qor_optimization/    #   25 任务：提升 PPA
├── tools/                   # 审计、验证与汇总脚本
├── runs/150_ultimate/       # 原始结果（提交证据）
│   ├── CROSS_MODEL_REPORT.md
│   ├── deepseek/
│   ├── qwen3.5-122b-a10b/
│   └── qwen3.6-27b/
├── technical-paper/         # IEEE 双栏论文与 LaTeX 源码
│   ├── main.pdf
│   ├── main_cn.pdf          #   中文版（审核用）
│   ├── main.tex
│   └── sections/
├── README.md                # 英文说明
└── README_CN.md             # 本文件
```

## 任务模式

`--mode` 参数选择智能体的修复流水线：

| 模式 | 说明 |
|------|------|
| `auto` | 从 `task.toml` 自动检测类别（推荐） |
| `generate` | 从桩生成完整代码 |
| `repair` | 编译 / 综合 / 功能修复 |
| `structural` | C/RTL 协同仿真死锁修复 |
| `optimize` | QoR 优化 |
| `full` | 完整流水线：修复 → 结构修复 → 优化 |

## 批量评估（150 任务）

评分基础设施将 150 任务语料库分片到并行 Docker 容器中运行：

```bash
# 三路分片启动 —— 每个分片索引分别执行
SHARD=0  # 或 1、2
MODEL=qwen/qwen3.6-27b
OUTPUT=runs/my_run_shard${SHARD}

VITIS_PARENT=$(dirname $(dirname "$VITIS_SDK"))
docker run -d --name fpt26-s${SHARD} \
  -v $(pwd):/workspace \
  -v "${VITIS_PARENT}:/tools/Xilinx:ro" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace:/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
  -w /workspace/fpt26-agent-v3 \
  fpt26-agent-v3:latest \
  bash -c "source /tools/Xilinx/2025.2/Vitis/settings64.sh && \
    python3 -m scoring.run_p0_real_api_shard \
      --task-root /workspace/tasks/track_a_150 \
      --output-root /workspace/${OUTPUT} \
      --shard-index ${SHARD} --shard-count 3 \
      --task-timeout-s 7200 \
      --backend openrouter --model ${MODEL}"
```

所有分片完成后，生成跨模型报告：

```bash
python3 tools/write_track_a_final_summary.py \
  --run-root runs/my_run_shard0 \
  runs/my_run_shard1 \
  runs/my_run_shard2 \
  --output runs/my_run/CROSS_MODEL_REPORT.md
```

## 复现论文结果

1. 将三个模型的输出放入 `runs/150_ultimate/`（已随提交证据提供）。
2. 刷新生成的宏：
   ```bash
   python3 technical-paper/scripts/update_results.py
   ```
3. 编译论文：
   ```bash
   cd technical-paper
   # 英文版
   pdflatex main && bibtex main && pdflatex main && pdflatex main
   # 中文版（审核用）
   pdflatex main_cn && bibtex main_cn && pdflatex main_cn && pdflatex main_cn
   ```

## 提交清单（Track-A）

- [x] 技术论文（IEEE 双栏，正文 ≤ 2 页 + 附录）
- [x] Dockerfile 可复现构建
- [x] 智能体源码
- [x] 任务语料库（150 均衡任务）
- [x] 每任务提交证据（`submission_evidence.json`）
- [x] 跨模型评估报告
- [x] 令牌与积分核算
- [x] 三款推荐开源模型对比
- [ ] 演示视频（≤ 5 分钟，单独录制）

## 许可证

智能体代码：MIT。任务语料内核衍生自 AMD/Xilinx 的
`Vitis-HLS-Introductory-Examples`（Apache-2.0）和 `Vitis_Accel_Examples`
（MIT）。每任务出处详见 `tasks/track_a_150/candidate_manifest.json`。
