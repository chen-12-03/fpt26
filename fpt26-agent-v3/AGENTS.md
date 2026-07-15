# AGENTS.md — fpt26-agent-v3

## 1. 项目概述

`fpt26-agent-v3` 是 LLM4HLS Track A 比赛 agent 的第三版。

核心策略：
- **`scoring/`** — V3 统一评分引擎 `scoring_v3.grade()`，所有任务同一公式
- **`agent/`** — 自研 agent 逻辑，通过 Pipeline 声明式工作流组织
- **`llm4hls/`** — 指向 `../fpt26-harness/llm4hls/`（官方 harness，不可修改）
- **Docker 内运行全部代码**（Vitis HLS + agent + LLM 调用 + 评分）

## 2. 最高优先级规则

### 2.1 Docker-only — 所有操作在 Docker 中执行

```bash
docker run --rm \
  -v $(pwd)/..:/workspace \
  -v /tools/Xilinx:/tools/Xilinx:ro \
  --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -w /workspace fpt26-agent-v3:latest \
  bash -c "source /tools/Xilinx/Vitis/2025.2/settings64.sh && python3 -m agent.main ..."
```

宿主机只允许 `docker run` 和 `docker compose`，不允许直接运行 Python。

### 2.2 V3 统一评分 — 所有任务同一公式

评分使用 `scoring/scoring_v3.py`，核心公式：

```
ratio_quality(r) = 1 - 1/(1+r)²
q_perf   = 0.85 × ratio_quality(latency_ratio) + 0.15 × ratio_quality(ii_ratio)
q_area   = ratio_quality(1 / max(growth_by_resource))
q_hw     = √(q_perf × q_area)
efficiency = max(0.80, 1 - 0.10×cost_ratio - 0.10×time_ratio)
score    = 100 × validity × q_hw × efficiency
```

关键设计：
- **无 task type 分支** — task_type 仅为标签，不影响公式
- **统一 utility** — `1-1/(1+r)²`，baseline(1x)=0.75
- **Anchor 选择** — starter valid → starter；starter invalid → reference
- **时钟周期纳入计算** — `anchor_time = clock × latency`
- **资源瓶颈惩罚** — 以最差资源增长比为 area_growth

### 2.3 统一提示词 — 禁止 mode/task-type 特定提示词

`agent/prompts.py` 中所有 mode 使用同一个 `SYSTEM` 提示词。
**禁止**根据 task_type、mode 切换不同的系统提示词。
Agent 根据工具结果（csim fail / cosim deadlock / all pass）自行判断行动。

### 2.4 官方 harness 只读

`fpt26-harness/llm4hls/` 目录中的文件**禁止修改**：
- `scoring.py` — 旧版评分（保留兼容，V3 优先使用 `scoring/scoring_v3.py`）
- `harness.py` — ToolServer 接口
- `tools.py` — ToolResult, CSimTool, SynthTool, CoSimTool
- `task.py` — Task 数据类 + load_task()
- `llm.py` — LLM backend（可添加新 backend 类）

## 3. 目录结构

### 3.1 工作区总览

```
fpt26_new/                  ← 仓库根目录
├── tasks/                  ← 🆕 统一测试任务库（97 个 task）
│   ├── official/           ← 官方 3 个竞赛任务
│   │   ├── dotProduct_optimize/
│   │   ├── projection_bugfix/
│   │   └── residual_stream_deadlock/
│   └── generated/          ← 自动生成 94 个任务（8 个来源）
│       ├── c2hlsc__*/      ← C2HLSC 加密/HLS 任务
│       ├── chstone__*/     ← CHStone HLS benchmark
│       ├── flowgnn__*/     ← FlowGNN 图神经网络
│       ├── gnnbuilder__*/  ← GNNBuilder 图处理
│       ├── machsuite__*/   ← MachSuite FPGA benchmark
│       ├── polybench__*/   ← PolyBench 数值计算
│       ├── pp4fpga__*/     ← PP4FPGA 并行模式
│       └── rosetta__*/     ← Rosetta HLS benchmark
├── fpt26-agent-v3/         ← 当前 agent（v3）
├── fpt26-harness/          ← 官方 harness（llm4hls/）
├── third_party/            ← 第三方参考（hls-generator）
├── runs/                   ← 运行输出
└── docs/                   ← 设计文档
```

### 3.2 Agent 目录

```
fpt26-agent-v3/
├── scoring/              ← 🆕 V3 统一评分引擎
│   ├── scoring_v3.py     ← grade(): 权威 V3 评分公式
│   ├── test_scoring_v3.py← 评分单元测试
│   └── __init__.py
├── agent/                ← 🆕 自研 agent 逻辑
│   ├── workflow.py       ← 🔑 Pipeline 定义（一个文件看清流程）
│   ├── main.py           ← CLI 入口
│   ├── prompts.py        ← 统一 LLM 提示词（所有 mode 共用 SYSTEM）
│   ├── knowledge.py      ← HLS 优化模式查找（纯关键词匹配）
│   ├── backends.py       ← LLM backend 工厂
│   ├── reporting.py      ← 运行报告 + 控制台输出
│   ├── eval.py           ← 跨运行评估工具
│   ├── agents/           ← Agent 实现
│   │   ├── base.py       ← RunState + AgentConfig
│   │   ├── repair.py     ← C-sim 失败修复 Agent
│   │   ├── optimize.py   ← 报告驱动的优化 Agent
│   │   ├── structural.py ← Cosim 死锁修复 Agent
│   │   └── competition.py← 并行竞争（可选）
│   ├── analysis/         ← 日志规范化 + 问题分类
│   └── transform/        ← 确定性 pragma 变换
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── run-agent.sh
├── test_all.sh
└── tasks → ../tasks/     ← symlink → 统一任务库
```

## 4. 核心架构

### 4.1 Pipeline 工作流

工作流在 `agent/workflow.py` → `build_pipeline()` 中定义：

```
init → csim → [repair] → synth → [cosim] → [structural_repair] → [optimize] → score → finalize
```

- `repair` 仅在 csim 失败时触发
- `cosim` / `structural_repair` 仅在 requires_cosim 时触发
- `optimize` 仅在 mode 为 optimize/full 且 csim+synth 均通过时触发
- `score` 使用 V3 评分（hidden csim → synth(cand) → synth(base) → cosim(if needed)）

### 4.2 RunState

Pipeline 步骤间传递的共享状态：

```python
@dataclass
class RunState:
    task: Task            # 官方 Task 对象
    server: ToolServer    # 官方 ToolServer（计量）
    llm: LLMClient | None
    config: AgentConfig   # mode, max_attempts, output_root, score 等
    kernel: str           # 当前 kernel 源代码
    csim_ok: bool
    synth_ok: bool
    cosim_ok: bool
    best_latency: int | None
    results: list[ToolResult]
    scorecard: Scorecard | None  # V3 Scorecard（schema_version=5）
    status: str           # running | completed | budget_exceeded | error
```

### 4.3 V3 评分流程

`step_score()` in `workflow.py`:

1. Hidden C-simulation（hidden testbench）
2. Hidden C/RTL co-simulation（仅 requires_cosim 任务）
3. Candidate synthesis
4. Baseline (starter) synthesis
5. Reference synthesis（如果存在，作为 anchor 后备）
6. 构建 `TaskScoringConfig`, `Anchor`, `QoREvidence`, `ValidityGates`
7. 调用 `scoring_v3.grade()` → `Scorecard`

## 5. 运行方式

### 5.1 任务路径

所有任务统一位于 `/workspace/tasks/`：

| 类别 | 路径 | 数量 |
|------|------|:----:|
| 官方竞赛任务 | `/workspace/tasks/official/<name>` | 3 |
| 自动生成任务 | `/workspace/tasks/generated/<name>` | 94 |

### 5.2 测试优先级 ⚠️

**必须优先使用 official 任务进行测试和优化。** 只有 official 任务表现理想后，才引入 generated 任务扩展测试。

```
official (3 tasks) → 理想 → generated (94 tasks)
                     ↓ 不理想
              继续优化 official，不碰 generated
```

原因：避免对 generated 任务过拟合，确保 agent 优化策略的泛化能力。official 任务覆盖了三种核心场景（repair / optimize / structural），是衡量 agent 性能的最小完备集。

### 5.2 Docker 运行命令

```bash
# 构建镜像
docker build -t fpt26-agent-v3:latest -f fpt26-agent-v3/Dockerfile .

# 官方任务 — 基线模式（只跑 csim+synth，不调 LLM）
docker run --rm \
  -v $(pwd):/workspace -v /tools/Xilinx:/tools/Xilinx:ro \
  --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
  -w /workspace fpt26-agent-v3:latest \
  bash -c "source /tools/Xilinx/Vitis/2025.2/settings64.sh && \
    python3 -m agent.main --task /workspace/tasks/official/projection_bugfix --mode baseline"

# 官方任务 — 修复模式
docker run ... python3 -m agent.main --task /workspace/tasks/official/projection_bugfix --mode repair

# 官方任务 — 优化模式
docker run ... python3 -m agent.main --task /workspace/tasks/official/dotProduct_optimize --mode optimize

# 官方任务 — 结构修复模式（含 cosim）
docker run ... python3 -m agent.main --task /workspace/tasks/official/residual_stream_deadlock --mode structural

# 生成任务示例
docker run ... python3 -m agent.main --task /workspace/tasks/generated/polybench__seidel_2d --mode optimize
docker run ... python3 -m agent.main --task /workspace/tasks/generated/machsuite__aes_aes --mode full

# 常用参数
--output-root runs/iter1        # 输出目录（默认 runs/）
--backend custom                # LLM backend（auto/openrouter/custom/scripted）
--max-repair-attempts 3         # 最大修复尝试次数
--max-optimization-rounds 3     # 最大优化轮数  
--max-structural-attempts 3     # 最大结构修复尝试次数
```

## 6. LLM 后端

| 场景 | 环境变量 |
|------|---------|
| 自定义 OpenAI 兼容 API | `FPT26_LLM_BASE_URL=...` + `FPT26_LLM_API_KEY=...` + `FPT26_LLM_MODEL=...` |
| OpenRouter | `OPENROUTER_API_KEY=sk-...` |
| 离线 Scripted | `--backend scripted` |

配置通常放在 `/tmp/fpt26.env` 并通过 `--env-file` 传入 Docker。

## 7. 代码规范

- Python 3.12+ stdlib 优先，避免第三方依赖
- 直接使用官方 `Task`、`ToolResult`、`ToolServer`，不要包装
- 评分必须调用 `scoring.scoring_v3.grade()`，不要自己实现
- **提示词必须统一** — 所有 mode 共用同一个 SYSTEM 提示词，不根据 task_type 切换
- **Agent 根据工具结果自行判断** — 不读取 task_type 标签做决策
- 所有文件系统输出写入 `runs/<iter>/<task_id>/` 下
- 所有操作在 Docker 中执行

## 8. 关键文件入口

| 想看什么 | 打开哪个文件 |
|---------|------------|
| 完整工作流 | `agent/workflow.py` → `build_pipeline()` |
| V3 评分公式 | `scoring/scoring_v3.py` → `grade()` |
| V3 评分流程 | `agent/workflow.py` → `step_score()` |
| 统一提示词 | `agent/prompts.py` → `_SYS` |
| 优化逻辑（报告驱动） | `agent/agents/optimize.py` |
| 修复逻辑 | `agent/agents/repair.py` |
| 结构修复（cosim 死锁） | `agent/agents/structural.py` |
| HLS 优化知识库 | `agent/knowledge.py` |
| 如何添加新 Agent | `agent/agents/base.py` + `agent/workflow.py` |

## 9. 已废弃

- `fpt26-agent-v2/` — 已压缩归档为 `fpt26-agent-v2.tar.gz`，不再使用
- `llm4hls/scoring.py` — 旧版评分，保留兼容但 V3 优先使用 `scoring/scoring_v3.py`
