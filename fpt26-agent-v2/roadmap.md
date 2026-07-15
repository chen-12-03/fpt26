# roadmap.md — fpt26-agent-v2 迁移路线图

## 概述

从 v1 (`fpt26-agent/`) 迁移到 v2，核心变化：

| v1 问题 | v2 解决方案 |
|---------|------------|
| 工作流不明确（520行 if/else） | `workflow.py` Pipeline 声明式步骤 |
| 评分一致性风险（自实现） | 直接调用官方 `scoring.grade()` |
| 无法扩展多 Agent | Agent Protocol + CompetitionStage |
| 过度包装官方接口 | 直接用 `ToolServer` + `ToolResult` |

## 当前状态

**阶段 1 — 骨架搭建** ← 正在进行
- [x] 目录结构
- [x] 复制 llm4hls/
- [x] 修改 llm.py（添加 OpenAICompatClient）
- [x] Docker 文件 (Dockerfile, docker-compose.yml, run-agent.sh)
- [x] tasks symlink
- [ ] 核心框架 (base.py, workflow.py, backends.py, main.py)
- [ ] Baseline smoke test

**阶段 2 — Repair Agent** ← 待开始
- [ ] 迁移 analysis/ (log_normalizer, issue_classifier)
- [ ] 迁移 prompts.py (TaskContext → Task)
- [ ] 实现 repair.py
- [ ] Repair smoke test

**阶段 3 — Optimize Agent** ← 待开始
- [ ] 迁移 transform/ (actions, transformer)
- [ ] 实现 optimize.py
- [ ] Optimize smoke test

**阶段 4 — Structural + Full** ← 待开始
- [ ] 实现 structural.py
- [ ] 实现 reporting.py
- [ ] Full mode 端到端测试
- [ ] 评分一致性验证

**阶段 5 — Multi-Agent** ← 待开始
- [ ] 实现 competition.py
- [ ] CLI --competition 参数
- [ ] 并行竞争 smoke test

## 关键设计决策

### 为什么 llm4hls/ 不包装

v1 用 `HarnessBackend` → `UnifiedToolResult` 包装了官方 `ToolServer` → `ToolResult`。每次包装都有语义丢失风险。v2 直接使用官方类，零包装。

### 为什么用 Pipeline 而不是一个大方法

v1 的 `CompetitionAgent.run()` 是 520 行的 if/else 链：
- 改一处分支可能影响其他分支
- 新人无法快速理解流程
- 加新 Agent 需要改核心代码

v2 的 Pipeline：
- 每个 Step 是独立函数/Agent
- `build_pipeline()` 就是工作流文档
- 加新 Agent = 加一行 `Step(...)`

### 为什么丢弃 analysis/ 中的大部分

v1 的 `cosim_analyzer.py`、`stream_analyzer.py`、`report_analyzer.py`、`kernel_validator.py` 是过度分析层：
- LLM 本身就擅长从原始 log 中诊断问题
- 中间分析层增加了维护成本和出错可能
- 保留的 `log_normalizer.py` 和 `issue_classifier.py` 只做轻量预处理（去 ANSI、路径归一化）

### TaskContext → Task

v1 定义了自己的 `TaskContext`（277行），本质上是从官方 `Task` 复制字段。v2 直接用官方 `Task`，prompt 构建时从 `Task` 读取字段。

## 验收指标

1. **三个官方 task 在 Docker 中端到端跑通**（baseline/repair/optimize/structural/full 模式）
2. **`scoring.grade()` 输出与官方 `run_poc.py` 一致**
3. **打开 `agent/workflow.py` 能一眼看懂完整流程**
4. **新增 Agent = 实现协议 + 加一个 Step，不碰其他代码**
5. **agent/ 代码量 < 2000 行**（v1 是 ~7000 行）
