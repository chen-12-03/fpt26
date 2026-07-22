# FPT26 Track-A Agent v3 — 代码阅读指南

## 项目概述

本工程是 **FPT26 竞赛 Track-A** 的参赛 Agent，目标是用 **LLM（大语言模型）驱动** 的方式，
自动修复和优化 AMD-Xilinx Vitis HLS 的 C/C++ 内核代码。

```
                      ┌──────────────────────────────┐
                      │        CLI 入口 (main.py)      │
                      │    python -m agent.main ...    │
                      └─────────────┬────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │       参数解析 (cli.py)         │
                    │    mode / backend / budget     │
                    └───────────────┬───────────────┘
                                    │
              ┌─────────────────────┴─────────────────────┐
              │              角色分发                       │
              │  ┌──────────┐            ┌──────────────┐ │
              │  │Submission│            │  Evaluator   │ │
              │  │ (参赛者)  │            │  (评分者)     │ │
              │  └────┬─────┘            └──────┬───────┘ │
              └───────┼────────────────────────┼─────────┘
                      │                        │
              ┌───────┴────────┐      ┌────────┴─────────┐
              │ Pipeline 流水线 │      │ 评分流水线        │
              │ (submission.py) │      │ (evaluator.py)   │
              └───────┬────────┘      └────────┬─────────┘
                      │                        │
        ┌─────────────┼─────────────┐          │
        │             │             │          │
   ┌────┴────┐  ┌────┴────┐  ┌────┴────┐     │
   │ Repair  │  │Structural│  │Optimize │     │
   │ Agent   │  │  Agent   │  │  Agent  │     │
   │(修复CSim)│  │(修复CoSim)│  │(优化性能)│     │
   └────┬────┘  └────┬────┘  └────┬────┘     │
        │             │             │          │
        └─────────────┼─────────────┘          │
                      │                        │
              ┌───────┴────────┐      ┌────────┴─────────┐
              │   Candidate    │      │   Scoring V3      │
              │   Validator    │      │   评分系统         │
              │  (候选验证器)   │      │ (scoring_v3.py)   │
              └───────┬────────┘      └────────┬─────────┘
                      │                        │
              ┌───────┴────────┐      ┌────────┴─────────┐
              │   工具执行层    │      │   报告生成         │
              │  (runner.py)   │      │  (reporting/)     │
              │ SecureExecutor │      └──────────────────┘
              └────────────────┘
```

## 建议阅读顺序（从入门到精通）

### 第 1 步：理解"这个程序做什么"

**先看这两份文件，建立全局概念：**

| 序号 | 文件 | 说明 |
|------|------|------|
| 1 | [cli.py](agent/cli.py) | 命令行参数定义 — 了解所有可配置选项 |
| 2 | [main.py](agent/main.py) | 程序入口 — 看 Submission 和 Evaluator 两条路 |

读完你应知道：程序从命令行启动，有两种角色（Submission 提交 / Evaluator 评分），
通过 Pipeline 流水线串联多个步骤。

### 第 2 步：理解"数据怎么流动"

**核心数据模型：**

| 序号 | 文件 | 说明 |
|------|------|------|
| 3 | [models.py](agent/models.py) | **所有数据结构定义** — RunState（运行状态）、各种 Gate 证据、SubmissionEvidence 等 |
| 4 | [agents/base.py](agent/agents/base.py) | AgentConfig（配置）和 RunState（核心运行状态） |

读完你应知道：整个流水线的共享状态是 `RunState`，
它记录了内核代码、各门控检查结果、PPA 指标、预算消耗等。`RunState` 在每一步之间传递并修改。

### 第 3 步：理解"流水线怎么跑"

**流水线编排：**

| 序号 | 文件 | 说明 |
|------|------|------|
| 5 | [pipeline/submission.py](agent/pipeline/submission.py) | **核心流水线** — 6 个阶段的完整编排 |
| 6 | [workflow.py](agent/workflow.py) | 向后兼容的外观层 — 转发到真正的实现 |
| 7 | [pipeline/stages.py](agent/pipeline/stages.py) | 最终化（finalize）和公共验收（public_acceptance）阶段 |

Submission 流水线的 6 个阶段：
```
阶段1: Baseline CSim  → 使用初始代码做C仿真
阶段2: Repair          → 如果CSim失败，LLM修复
阶段3: Synthesis       → C综合 + 频率门控 + 资源门控
阶段4: CoSim           → 结构型任务需要C/RTL联合仿真
阶段5: Optimization    → LLM驱动的性能优化（只对已通过所有门控的代码）
阶段6: Public Acceptance → 最终验收，持久化最终内核
```

### 第 4 步：理解"三个 Agent 各自做什么"

**LLM Agent 模块：**

| 序号 | 文件 | 说明 |
|------|------|------|
| 8 | [agents/repair.py](agent/agents/repair.py) | **修复 Agent** — 修 CSIM/综合失败 |
| 9 | [agents/structural.py](agent/agents/structural.py) | **结构修复 Agent** — 修 CoSim 死锁/超时 |
| 10 | [agents/optimize.py](agent/agents/optimize.py) | **优化 Agent** — 降低延迟/优化资源 |

三个 Agent 的循环模式相同：
```
循环（最多 N 次）:
    1. 运行工具（CSim/Synth/CoSim）
    2. 如果通过 → 成功返回
    3. 如果失败 → 构建 Prompt → LLM 修改代码 → 提取新代码
    4. 验证新代码（接口门控 + 工具门控）
    5. 回到步骤 1
```

### 第 5 步：理解"如何验证候选代码"

**候选代码验证：**

| 序号 | 文件 | 说明 |
|------|------|------|
| 11 | [candidate/validator.py](agent/candidate/validator.py) | **统一的候选验证器** — 所有门控检查的单一权威来源 |
| 12 | [validation.py](agent/validation.py) | 向后兼容层 |

门控检查流程（fail-fast，任何一步失败立即返回）：
```
接口门控 → CSim门控 → 综合门控 → 频率门控(≥100MHz) → 资源门控(不超出器件容量)
                                                                    ↓
                                                            (如果是结构型任务)
                                                            CoSim门控 → 标记为"完全验证"
```

### 第 6 步：理解"评分怎么算"

**评分系统：**

| 序号 | 文件 | 说明 |
|------|------|------|
| 13 | [scoring/profiles.py](../scoring/profiles.py) | **评分策略配置** — 三种硬件取舍策略 |
| 14 | [scoring/evaluator.py](../scoring/evaluator.py) | **评分编排** — hidden-CSim → 综合比较 → 评分 |

评分公式：
```
总分 = 硬件质量(Q_HW) × 效率因子(Efficiency)

Q_HW = f(性能比值, 面积比值, 性能权重, 面积权重)
  - balanced 策略: 性能 55% + 面积 45%
  - extreme_speed 策略: 性能 70% + 面积 30%

Efficiency = f(credits消耗, 时间消耗, 预算上限, 时间上限)
```

### 第 7 步：理解"基础设施层"

**支撑模块：**

| 序号 | 文件 | 说明 |
|------|------|------|
| 15 | [runner.py](agent/runner.py) | **工具服务器** — CSim/Synth/CoSim 的工具适配器 |
| 16 | [backends.py](agent/backends.py) | **LLM 后端工厂** — 根据配置创建 LLM 客户端 |
| 17 | [prompts.py](agent/prompts.py) | **Prompt 模板** — 系统提示词和用户 Prompt 构建 |
| 18 | [integrations/harness.py](agent/integrations/harness.py) | **工具边界** — 所有 llm4hls 导入的统一入口 |

---

## 架构设计要点

### 1. 外观模式 (Facade)
`workflow.py` 和 `validation.py` 是向后兼容的外观层，
真正的实现在 `pipeline/submission.py` 和 `candidate/validator.py`。

### 2. 单一权威来源 (Single Source of Truth)
- `CandidateValidator` (candidate/validator.py) — **唯一**的候选验证器
- `RunState` (agents/base.py) — **唯一**的生产级运行上下文
- `evaluate_and_score` (scoring/evaluator.py) — **唯一**的评分编排

### 3. 安全失败 (Fail-Closed)
Evaluator 对缺失/损坏的证据一律拒绝评分，
Anchor 无效时分数归零。

### 4. LLM 无状态
每个 Agent 的每次循环都完全由工具结果驱动，
不积累隐式的"已尝试过的方法"状态。

---

## 关键术语表

| 英文 | 中文 | 说明 |
|------|------|------|
| CSim | C仿真 | 用 C++ 编译器运行 HLS 内核的功能验证 |
| Synth / Synthesis | C综合 | 将 C++ 代码综合成 RTL（寄存器传输级）电路 |
| CoSim | C/RTL联合仿真 | 验证综合后的 RTL 与原始 C++ 行为一致 |
| Gate | 门控 | 通过/失败的检查点 |
| Anchor | 锚点 | 评分基准（starter 代码或 reference 代码） |
| PPA | 性能/功耗/面积 | Performance, Power, Area |
| QoR | 结果质量 | Quality of Results |
| II | 启动间隔 | Initiation Interval — 循环两次迭代之间的时钟周期数 |
| Latency | 延迟 | 函数/循环完成所需的时钟周期总数 |
| Budget | 预算 | 云端 credits 消耗上限 |
| Pipeline | 流水线 | 顺序执行的步骤序列 |
| RunState | 运行状态 | 在流水线步骤间传递的共享上下文 |

---

## 目录结构总览

```
fpt26-agent-v3/
├── agent/                         # Agent 主包
│   ├── main.py                    # CLI 入口
│   ├── cli.py                     # 参数解析
│   ├── models.py                  # 数据模型（状态、证据、门控）
│   ├── workflow.py                # 向后兼容外观
│   ├── runner.py                  # 工具适配器（CSim/Synth/CoSim）
│   ├── backends.py                # LLM 后端工厂
│   ├── prompts.py                 # Prompt 模板
│   ├── evaluator.py               # Evaluator 外观
│   ├── validation.py              # 验证兼容层
│   ├── agents/                    # LLM Agent 实现
│   │   ├── base.py                # 基础类型（RunState, AgentConfig）
│   │   ├── repair.py              # 修复 Agent
│   │   ├── structural.py          # 结构修复 Agent
│   │   ├── optimize.py            # 优化 Agent
│   │   └── optimization/         # 优化子模块（诊断/反馈/策略/评分）
│   ├── pipeline/                  # 流水线编排
│   │   ├── submission.py          # Submission 流水线（核心）
│   │   ├── evaluator.py           # Evaluator 流水线（核心）
│   │   ├── stages.py              # 阶段函数（finalize, acceptance）
│   │   └── core.py                # 流水线上下文（已弃用）
│   ├── candidate/                 # 候选代码验证
│   │   ├── validator.py           # 统一候选验证器
│   │   └── selector.py            # Anchor 选择器
│   ├── analysis/                  # 分析模块
│   │   ├── issue_classifier.py    # 问题分类器
│   │   └── log_normalizer.py      # 日志规范化
│   ├── integrations/              # 外部集成
│   │   ├── harness.py             # llm4hls 工具边界
│   │   ├── vitis.py               # Vitis 安全执行器
│   │   └── llm/                   # LLM 协议适配
│   └── reporting/                 # 报告生成
│       ├── console.py             # 控制台输出
│       ├── writer.py              # JSON 报告写入
│       ├── metrics.py             # 度量计算
│       └── builder.py             # 报告构建器
├── scoring/                       # 评分系统
│   ├── profiles.py                # 评分策略（balanced/extreme_speed）
│   ├── evaluator.py               # 评分编排
│   └── scoring_v3.py              # V3 评分内核（第三方）
└── tests/                         # 测试
    ├── test_candidate_pipeline.py
    ├── test_workflow_capacity_gate.py
    └── test_workflow_cosim_latency.py
```
