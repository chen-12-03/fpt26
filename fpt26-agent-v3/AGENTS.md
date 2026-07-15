# AGENTS.md — fpt26-agent-v2

## 1. 项目概述

`fpt26-agent-v2` 是 LLM4HLS Track A 比赛 agent 的第二版。核心策略：

- **`llm4hls/`** — 从官方 `fpt26-harness` 原样复制，**不改参数只加 LLM backend**
- **`agent/`** — 自研 agent 逻辑，通过 Pipeline 声明式工作流组织
- **Docker 内运行全部代码**（Vitis HLS + agent + LLM 调用）

## 2. 文件优先级

发生冲突时按以下优先级：

```
比赛官方要求
  > 迁移计划（见 roadmap.md）
  > AGENTS.md（本文件）
  > workflow.py 中的 Pipeline 定义
  > 各 Agent 实现代码
```

## 3. 最高优先级规则

### 3.1 Docker-only

所有 Python 代码必须在 Docker 容器内执行。宿主机只允许：

```bash
docker compose build ...
docker compose run ...
./run-agent.sh ...
```

### 3.2 官方 harness 只读

`llm4hls/` 目录中除 `llm.py` 外的所有文件**禁止修改**。这是评分一致性的保证。

- `llm4hls/scoring.py` — 权威评分算法，禁止修改
- `llm4hls/harness.py` — ToolServer 接口，禁止修改
- `llm4hls/tools.py` — ToolResult 结构，禁止修改
- `llm4hls/llm.py` — 可以添加新 backend 类，已有代码禁止修改

### 3.3 工作流可读性

`agent/workflow.py` 的 `build_pipeline()` 函数必须一眼看清完整流程。添加新步骤时：
- 在对应 `agents/` 文件中实现 Agent
- 在 `build_pipeline()` 中添加一个 `Step`
- 不得在 workflow.py 中写业务逻辑（业务逻辑在 Agent 里）

## 4. 目录结构

```
fpt26-agent-v2/
├── llm4hls/          ← 🔒 官方 harness（除 llm.py 外禁止修改）
│   ├── harness.py    ← ToolServer: csim/synth/cosim 计量接口
│   ├── scoring.py    ← grade(): 权威评分
│   ├── task.py       ← Task 数据类
│   ├── tools.py      ← ToolResult
│   └── llm.py        ← ✏️ 可添加新 backend
├── agent/            ← 🆕 自研 agent 逻辑
│   ├── workflow.py   ← 🔑 Pipeline 定义（一个文件看清流程）
│   ├── main.py       ← CLI 入口
│   ├── prompts.py    ← LLM 提示词
│   ├── agents/       ← Agent 实现
│   │   ├── base.py       ← RunState + AgentResult
│   │   ├── repair.py     ← 修复 Agent
│   │   ├── optimize.py   ← 优化 Agent
│   │   ├── structural.py ← 结构修复 Agent
│   │   └── competition.py← 并行竞争
│   ├── analysis/     ← 日志规范化 + 问题分类（从 v1 保留）
│   └── transform/    ← 确定性 pragma 变换（从 v1 保留）
├── Dockerfile
├── docker-compose.yml
├── run-agent.sh
└── tasks/            ← symlink → ../fpt26-harness/tasks/
```

## 5. 核心架构

### 5.1 Pipeline 声明式工作流

工作流在 `agent/workflow.py` 中定义：

```python
def build_pipeline(mode, task, server, llm):
    return Pipeline([
        Step("baseline",  BaselineAgent()),
        Step("repair",    RepairAgent(llm),     condition=csim_failed),
        Step("cosim",     CosimCheckAgent(),    condition=needs_cosim),
        Step("structural",StructuralRepairAgent(llm), condition=cosim_failed),
        Step("optimize",  OptimizeAgent(llm),    condition=can_optimize),
        Step("score",     ScoreAgent()),
    ])
```

### 5.2 Agent Protocol

每个 Agent 实现 `run(ctx: RunState) -> RunState`：

```python
class Agent:
    def run(self, ctx: RunState) -> RunState: ...
```

新增 Agent 只需：实现协议 + 在 `build_pipeline()` 加 Step。

### 5.3 RunState

pipeline 步骤间传递的共享状态：

```python
@dataclass
class RunState:
    task: Task            # 官方 Task 对象
    server: ToolServer    # 官方 ToolServer
    llm: LLMClient | None
    current_kernel: str   # 当前 kernel 代码
    csim_ok: bool
    synth_ok: bool
    cosim_ok: bool
    results: list         # ToolResult 累积列表
    scorecard: Any        # 评分结果
```

## 6. 运行方式

```bash
# 进入容器
./run-agent.sh bash

# 基线模式（只跑 csim+synth，不调 LLM）
./run-agent.sh python -m agent.main --task tasks/projection_bugfix --mode baseline

# 修复模式
./run-agent.sh python -m agent.main --task tasks/projection_bugfix --mode repair

# 优化模式
./run-agent.sh python -m agent.main --task tasks/dotProduct_optimize --mode optimize

# 全流程
./run-agent.sh python -m agent.main --task tasks/dotProduct_optimize --mode full

# 并行竞争模式
./run-agent.sh python -m agent.main --task tasks/dotProduct_optimize --mode full --competition
```

## 7. LLM 后端切换

| 场景 | 环境变量 |
|------|---------|
| OpenRouter | `OPENROUTER_API_KEY=sk-...` |
| 自定义 OpenAI 兼容 API | `FPT26_LLM_BASE_URL=http://...` + `FPT26_LLM_API_KEY=...` |
| 离线（Scripted） | `--backend scripted` |

## 8. 代码规范

- Python 3.12+ stdlib 优先，避免第三方依赖
- 直接使用官方 `Task`、`ToolResult`、`ToolServer`，不要包装
- 评分必须调用 `llm4hls.scoring.grade()`，不要自己实现
- Prompt 构建接受官方 `Task` 对象，不接受 v1 的 `TaskContext`
- 所有文件系统输出写入 `runs/<task_id>/` 下

## 9. 关键文件入口

| 想看什么 | 打开哪个文件 |
|---------|------------|
| 完整工作流 | `agent/workflow.py` → `build_pipeline()` |
| 修复逻辑 "LLM改代码→sim→读结果→决定" | `agent/agents/repair.py` |
| 优化逻辑 | `agent/agents/optimize.py` |
| LLM 提示词 | `agent/prompts.py` |
| 如何添加新 Agent | `agent/agents/base.py` + `agent/workflow.py` |
| 评分算法（不可改） | `llm4hls/scoring.py` → `grade()` |
