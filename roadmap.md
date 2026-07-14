# FPT26 Track-A Budgeted End-to-End LLM4HLS Agent Roadmap V4

> 定位：以官方 `fpt26-harness` 为唯一 HLS 执行与本地评测内核，将 `fpt26-agent` 建设为一个在工具调用预算内解释任务、诊断问题、生成或修改 HLS C/C++、修复 correctness、优化 PPA 并输出可复现实验结果的端到端 Agent。
>
> Docker 强制约束：除宿主机执行容器启动、构建和目录挂载外，Agent、官方 harness、任务解析、LLM 客户端、候选生成、HLS 调用、日志解析、候选选择、实验记录、replay 和最终导出全部在 Docker 容器内运行。

---

## 0. 修订摘要

V4 保留 V3 的核心架构，不重新实现官方 Vitis 工具链，也不恢复独立 HLS runner 主链。

本次修订重点：

1. 正式主入口从“自然语言或单 kernel”调整为“官方任务包”。
2. 支持多种初始状态：未优化、编译失败、综合失败、C-sim 失败、Co-sim 失败、结构问题和混合问题。
3. 将任务解释、初始状态分类和日志诊断前移到主循环入口。
4. `TaskContext` 和内部 IR 增加构建脚本、接口契约、数值容差、资源限制和预算配置。
5. HLS 预算同时支持统一 credit 和按工具调用次数限制。
6. 候选有效性增加任务时钟、100 MHz、可选资源上限和必要 Co-sim 门控。
7. 调整 Docker 工具链规则：宿主机 Vitis 必需，XRT 默认使用镜像内 `/opt/xilinx/xrt`，外部 XRT 可覆盖，platform 仅在实际流程需要 `.xpfm` 时强制。
8. 已完成的官方 harness 固化、Docker 入口、环境预检和 `dotProduct_optimize` C-sim/Synth smoke 作为稳定基线，不返工。

---

## 1. 比赛问题定义

Track-A 的目标不是单一代码生成，而是在有限 HLS 工具预算内完成端到端任务：

```text
Task Package
  -> Interpret specification and initial code
  -> Diagnose initial condition
  -> Generate / repair / optimize HLS C/C++ and pragmas
  -> Call provided evaluation interfaces
  -> Parse logs and reports
  -> Resolve correctness before PPA
  -> Stop within HLS and token budgets
  -> Return final reproducible candidate
```

### 1.1 可能的初始状态

Agent 必须能识别并处理：

- 功能正确但未优化的 C/C++ baseline。
- C/C++ 或 HLS 编译失败。
- C synthesis 失败。
- 编译成功但 C-sim 失败。
- 编译和 C-sim 成功但 Co-sim 失败。
- public test 通过但存在隐藏功能风险。
- stream/dataflow deadlock。
- 无效 streaming 行为。
- 严重资源低效。
- 多种问题混合存在。
- 其他 HLS 编译或综合相关问题。

### 1.2 正式任务包可能包含

```text
problem statement / description
source files
public testbench
build scripts, e.g. Makefile
interface contract
data types
numerical tolerance
design constraints
FPGA platform
HLS tool version
clock target
optional resource limits
budget configuration
```

系统不得继续假设：

- 每个任务只有一个输入源码文件。
- 每个任务都由 Agent 生成 testbench。
- 所有输出都必须逐元素精确相等。
- 所有任务使用同一种 budget 形式。
- 只要 C-sim 通过就不存在结构问题。

第一版仍可限制为一个主要 editable kernel，但必须显式识别不支持的多 editable source 布局，不得错误合并或静默忽略。

### 1.3 评价优先级

```text
correctness
  > synthesizability
  > task constraints
  > required Co-sim validity
  > PPA
  > token and tool efficiency
```

---

## 2. 比赛硬约束与工程落点

| 比赛要求 | 工程落点 |
|---|---|
| Alveo U55C | 使用任务目标 part/platform；默认 part 为 `xcu55c-fsvh2892-2L-e` |
| Vitis 2025.2 | 容器内预检 `settings64.sh` 和 `vitis-run` |
| 通过 C-sim、Synth、Co-sim | 统一通过官方 `ToolServer` |
| 至少 100 MHz | `estimated_clock_ns <= 10.0`，同时满足更严格的任务时钟 |
| 有限工具调用预算 | 支持统一 credit 或按工具调用限制 |
| Token 消耗参与评价 | 独立记录每次 LLM 的 token、用途、耗时和缓存 |
| 仅开源 LLM | manifest 记录模型、版本、许可证和 endpoint 类型 |
| Hidden benchmark | 不读取 hidden testbench，不使用 hidden grading 反馈优化 |
| Docker 运行 | 全部业务代码和 HLS 流程在容器内执行 |
| 可复现提交 | Dockerfile、Compose、锁定依赖、统一入口、manifest、replay |
| 实验报告 | 自动从结构化 JSON 生成，不手工复制指标 |
| 5 分钟演示 | 使用固定已验证案例，不现场运行无边界搜索 |

### 2.1 有效时钟门槛

```text
competition_clock_limit_ns = 10.0
requested_clock_ns = task target clock, if provided

effective_clock_limit_ns =
    min(requested_clock_ns, 10.0), if requested clock exists
    10.0, otherwise
```

候选必须满足 `estimated_clock_ns <= effective_clock_limit_ns`。

示例：

| 任务目标 | 有效门槛 |
|---:|---:|
| 5 ns | 5 ns |
| 8 ns | 8 ns |
| 12 ns | 10 ns |
| 未提供 | 10 ns |

### 2.2 资源限制

若任务提供资源上限，候选还必须满足：

```text
LUT  <= max_lut
FF   <= max_ff
DSP  <= max_dsp
BRAM <= max_bram
URAM <= max_uram
```

未提供的限制使用 `null`，不得猜测。

---

## 3. Docker 强制边界

### 3.1 宿主机允许做的事情

宿主机只允许：

- `docker build` / `docker compose build`。
- `docker run` / `docker compose run`。
- 挂载仓库和运行产物目录。
- 挂载宿主机 Vitis 2025.2。
- 可选挂载宿主机 XRT 或 platform。
- 传入模型和许可证配置。
- 查看容器输出与生成文件。

### 3.2 宿主机禁止做的事情

宿主机不得：

- 直接执行 Agent Python 模块。
- 直接执行官方 `run_poc.py`。
- 直接运行 `vitis-run`。
- 调用 LLM。
- 生成、修复或优化 kernel。
- 解析 HLS report。
- 维护第二套 HLS runner。

### 3.3 工具链来源规则

```text
VITIS:
  required host mount
  validate $VITIS/settings64.sh

XRT:
  optional host override
  default /opt/xilinx/xrt inside vitis_runtime:2025.2

PLATFORM:
  optional for Python, tests, C-sim and ordinary part-based Synth
  required only when the selected flow explicitly requires .xpfm

HLS_PART:
  task target first
  fallback xcu55c-fsvh2892-2L-e
```

不得再次把宿主机 XRT 和 U55C `.xpfm` 设为所有容器命令的强制前置条件。

### 3.4 容器内必须运行

- `agent/main.py`。
- `CompetitionAgent`。
- 官方 harness。
- Task/IR 解析。
- 初始状态分类。
- 静态分析和日志诊断。
- LLM 调用。
- deterministic transform。
- candidate store 和 selector。
- `ToolServer.csim/synth/cosim`。
- `vitis-run`。
- report 解析。
- manifest、实验报告和 replay。
- 单元测试和集成测试。

### 3.5 唯一宿主入口

```bash
VITIS=/tools/Xilinx/Vitis/2025.2 \
./fpt26-agent/run-agent.sh \
  python3 -m agent.main \
  --task third_party/fpt26_harness/tasks/dotProduct_optimize \
  --mode full
```

`run-agent.sh` 只负责检查宿主机 Docker/Vitis 配置、启动容器、传递参数和退出码。

---

## 4. 总体架构

```text
┌──────────────────────────────────────────────────────────────┐
│                       Docker Container                       │
│                                                              │
│  Task Package                                                │
│  ├── Problem statement                                       │
│  ├── Initial source files                                    │
│  ├── Public testbench / build scripts                        │
│  ├── Interface / tolerance / constraints                     │
│  └── Target / budget configuration                           │
│                          │                                   │
│                          v                                   │
│  InputAdapter + TaskAdapter + TaskInspector                  │
│                          │                                   │
│                          v                                   │
│  TaskContext / HLS IR V2                                    │
│                          │                                   │
│                          v                                   │
│  InitialConditionClassifier                                 │
│                          │                                   │
│                          v                                   │
│  CompetitionAgent                                            │
│  ├── BaselineController                                      │
│  ├── RepairController                                        │
│  ├── StructuralRepairController                              │
│  ├── OptimizationController                                  │
│  ├── BudgetPolicy                                            │
│  ├── CandidateStore / Selector                               │
│  ├── LLM Planner                                             │
│  └── Deterministic Transformer                               │
│                          │                                   │
│                          v                                   │
│  HarnessBackend + ResultAdapter                              │
│                          │                                   │
│                          v                                   │
│  Official Task + ToolServer + Budget + Transcript            │
│  ├── csim(kernel_code)                                       │
│  ├── synth(kernel_code)                                      │
│  └── cosim(kernel_code)                                      │
│                          │                                   │
│                          v                                   │
│  LogNormalizer + IssueClassifier + ReportAnalyzer            │
│                          │                                   │
│                          v                                   │
│  Final Kernel + Manifest + Experiment Report + Replay         │
└──────────────────────────────────────────────────────────────┘
```

---

## 5. 官方 Harness 的定位

### 5.1 官方能力是唯一真实执行来源

保持官方模块原貌：

```text
llm4hls/task.py
llm4hls/vitis.py
llm4hls/tools.py
llm4hls/report.py
llm4hls/budget.py
llm4hls/harness.py
llm4hls/scoring.py
```

它们负责：

- 加载官方任务。
- 控制不可编辑的 header/testbench。
- 调用 Vitis。
- C-sim、Synth、Co-sim。
- report 解析。
- HLS 工具预算和 transcript。
- hidden grading 和 scorecard。

### 5.2 自研策略替换 ReferenceAgent

官方 `ReferenceAgent` 只作为参考。

自研 `CompetitionAgent` 负责：

- 解释规格和初始源码。
- 判断初始问题类别。
- 决定下一次工具调用。
- 生成、修复或优化候选 kernel。
- 控制 HLS 和 token 预算。
- 保存 candidate lineage。
- 选择最终候选。

### 5.3 官方副本规则

官方 harness 已固化到：

```text
third_party/fpt26_harness/
```

规则：

1. 官方目录默认只读。
2. 通过 import、adapter、composition 或 subclass 集成。
3. 不在官方模块中混入 Agent 策略。
4. 不绕过 `ToolServer` 直接调用 Vitis。
5. 已知官方工具路径问题优先在 adapter 中规避，不直接修改官方快照。
6. 保持 SHA-256 完整性测试持续通过。

---

## 6. 输入路线与优先级

### 6.1 路线 A：官方任务包

最高优先级和正式评测路线：

```text
task.toml / problem statement
initial source files
headers
public testbench
build scripts
constraints and budget
       |
       v
Official Task Loader + TaskInspector
       |
       v
TaskContext V2
       |
       v
CompetitionAgent
       |
       v
ToolServer
       |
       v
Final editable kernel
```

正式模式中：

- Agent 只修改允许编辑的 kernel 源码。
- 不修改 header。
- 不修改 public testbench。
- 不访问 hidden testbench。
- 不在搜索循环中调用 hidden grading。
- 不修改接口契约，除非任务明确允许。

### 6.2 路线 B：已有 HLS 工程

```text
Existing Project
  -> discover sources/build files/spec
  -> identify editable and immutable files
  -> construct local official-style task
  -> TaskContext V2
  -> CompetitionAgent
```

第一版仅支持一个主要 editable kernel。遇到多个需要共同修改的源码时明确返回 `UNSUPPORTED_MULTI_EDITABLE_SOURCE`。

### 6.3 路线 C：自然语言任务

```text
Natural Language Spec
  -> Spec Extractor
  -> HLS IR V2
  -> conservative kernel + local public testbench
  -> LocalTaskBuilder
  -> official-style local task
  -> CompetitionAgent
```

该路线为辅助能力，优先级低于官方任务的 repair/optimize。

近期模板限制：

1. vector/map。
2. reduction。
3. small matrix multiplication。
4. generic fixed-bound loop。

在官方 repair、optimize 和 structural 三类样例跑通前，不继续扩大模板范围。

### 6.4 路线 D：已有 IR

```text
HLS IR V2
  -> schema validation
  -> source and task artifact resolution
  -> LocalTaskBuilder
  -> CompetitionAgent
```

`replay` 模式禁止调用 LLM。

---

## 7. TaskContext 与 HLS IR V2

内部 `TaskContext` 不替代官方 `Task`，仅向策略层暴露必要信息。

建议结构：

```python
@dataclass
class TaskContext:
    task_id: str
    input_mode: str
    declared_task_type: str | None
    description: str

    editable_sources: list[str]
    immutable_sources: list[str]
    header_files: list[str]
    public_testbench: str | None
    build_files: list[str]

    top_function: str
    interface_contract: dict
    data_types: dict
    numeric_tolerance: dict | None
    design_constraints: dict

    target_part: str
    target_platform: str | None
    requested_clock_ns: float | None
    competition_clock_limit_ns: float
    effective_clock_limit_ns: float
    resource_limits: dict

    requires_cosim: bool
    budget_config: dict
    inferred_fields: list[str]
```

### 7.1 任务类型

```text
GENERATE
COMPILE_REPAIR
SYNTH_REPAIR
CSIM_REPAIR
COSIM_REPAIR
STRUCTURAL_REPAIR
PPA_OPTIMIZE
MIXED
UNKNOWN
```

任务标签只是先验，必须结合初始工具反馈更新实际分类。

### 7.2 数值容差

支持表示：

```json
{
  "mode": "exact|absolute|relative|absolute_or_relative|custom",
  "atol": null,
  "rtol": null,
  "description": null
}
```

Agent 不修改 public testbench，但在任务解释、诊断和报告中必须保留 tolerance 信息。

### 7.3 数据优先级

```text
Official task artifacts
  > task specification
  > local task config
  > HLS IR
  > explicit CLI override allowed by mode
  > conservative default
```

所有推断和默认值写入 `inferred_fields`，不得静默覆盖官方参数。

---

## 8. TaskInspector 与初始状态分类

### 8.1 TaskInspector

在首次 HLS 调用前完成：

- 源文件和构建文件发现。
- editable/immutable 文件划分。
- top function 和签名提取。
- 接口、类型、shape 和 tolerance 摘要。
- pragma 和 loop 摘要。
- stream/dataflow 使用检测。
- 递归、动态内存和明显不支持结构检测。
- 目标时钟和资源限制加载。
- budget 形式识别。

### 8.2 InitialConditionClassifier

分类信息来自：

1. task 声明。
2. 静态检查。
3. 首次 C-sim 结果。
4. 必要时 Synth 或 Co-sim 结果。

建议状态机：

```text
STATIC_INVALID
COMPILE_FAIL
CSIM_FAIL
CSIM_PASS_SYNTH_FAIL
SYNTH_PASS_PPA_POOR
COSIM_FAIL
STRUCTURAL_RISK
BASELINE_VALID
MIXED
```

### 8.3 初始工具调用策略

```text
Static invalid
  -> no HLS call, repair first

Ordinary task
  -> C-sim first

C-sim pass
  -> Synth

Stream/dataflow or declared structural task
  -> reserve and run early Co-sim after C-sim/Synth prerequisites

Declared compile/synth issue
  -> still use the lowest-cost official interface capable of exposing it
```

---

## 9. HarnessBackend 与统一结果

所有策略模块只能通过 `HarnessBackend` 调用官方工具。

```python
class HarnessBackend:
    def csim(self, candidate): ...
    def synth(self, candidate): ...
    def cosim(self, candidate): ...
```

职责：

- 接收官方 `Task` 和 `ToolServer`。
- 只调用 `server.csim/synth/cosim`。
- 将 build/run directory 规范化为绝对路径。
- 保留官方 budget 与 transcript。
- 关联 candidate ID 和工具调用序号。
- 标准化返回结果。
- 捕获并分类预算不足、超时和工具异常。
- 不直接调用 shell、`vitis-run` 或自定义 Tcl。

### 9.1 统一结果结构

```json
{
  "candidate_id": "c001_repair",
  "stage": "csim",
  "status": "pass|fail|error|budget_exceeded|timeout",
  "tool_phase": "compile|runtime|synthesis|cosimulation|null",
  "return_code": 0,
  "elapsed_seconds": 1.23,
  "summary": "...",
  "metrics": {},
  "diagnostics": [],
  "warnings": [],
  "artifacts": {
    "stdout_log": "...",
    "stderr_log": "...",
    "raw_report": null,
    "run_directory": "..."
  },
  "budget": {
    "mode": "unified_credits|per_tool_limits",
    "before": {},
    "after": {}
  },
  "transcript_index": 3
}
```

### 9.2 Synth 指标

```text
estimated_clock_ns
latency_min
latency_max
latency_average, if available
ii_min
ii_max
lut
ff
dsp
bram_18k
uram
```

缺失值使用 `null`，不得猜测。

### 9.3 原始日志策略

- JSON 保存短摘要和结构化 diagnostics。
- 完整 stdout/stderr/report 保存为 artifact 文件。
- 发送给 LLM 前进行裁剪和去重。
- 原始日志不得因摘要失败而丢失。

---

## 10. 日志与问题诊断

```text
ToolResult
  -> LogNormalizer
  -> IssueClassifier
  -> DiagnosticSummary
  -> RepairPlanner / OptimizationPlanner
```

### 10.1 LogNormalizer

负责：

- 去除无关重复行。
- 保留错误上下文和源码位置。
- 识别 Vitis 阶段。
- 提取 error/warning。
- 生成稳定 hash。
- 限制 LLM 输入长度。

### 10.2 IssueClassifier

第一版优先类别：

```text
missing_include
undefined_symbol
type_mismatch
signature_mismatch
unsupported_cpp
invalid_pragma
dynamic_allocation
recursion
out_of_bounds
shape_mismatch
functional_mismatch
synthesis_failure
timing_failure
resource_limit_failure
stream_deadlock
invalid_stream_behavior
cosim_mismatch
timeout
unknown
```

每个诊断至少包含：

```text
category
stage
confidence
file
line
message
minimal_context
suggested_action_family
```

---

## 11. CompetitionAgent 主循环

```text
Load Task Package
  -> Inspect and normalize TaskContext
  -> Create c000_initial
  -> Static validation
  -> Initial condition classification
  -> Correctness loop
       - C-sim
       - compile / functional repair
       - early Co-sim when structural
  -> Baseline Synth
  -> Constraint validation
       - task clock
       - 100 MHz
       - resource limits
  -> PPA optimization loop
  -> Final candidate selection
  -> Final C-sim
  -> Final Synth
  -> Final Co-sim
  -> Return final kernel and artifacts
```

### 11.1 correctness first

禁止在以下状态进入 PPA 搜索：

- 静态非法。
- C-sim 未通过。
- 无法综合。
- required baseline Co-sim 未通过。
- 明确接口或 tolerance 未解析。

### 11.2 终止条件

任一条件满足即停止扩展搜索：

- HLS budget 不足以完成预留的最终验证。
- token budget 达上限。
- 达到候选或迭代上限。
- 连续动作无收益。
- 没有新的合法 action。
- 已有候选达到任务目标且风险可接受。
- 只剩结构重写但预算不足。

停止后返回最优可验证候选，不返回最后生成但未验证的候选。

---

## 12. Repair 路线

### 12.1 静态与编译修复

优先确定性修复：

- 缺少 include。
- 明确的命名或未定义符号。
- top 签名偏差。
- 简单类型转换错误。
- pragma 语法或位置错误。
- 动态内存、递归和明显不支持 STL。

确定性规则无法安全处理时，再调用 LLM 输出局部 patch。

### 12.2 功能修复

```text
C-sim mismatch
  -> preserve interface and tolerance
  -> localize failing computation
  -> generate one focused patch
  -> C-sim revalidate
```

限制：

- 每轮只修一个主要错误。
- 默认最多两轮 LLM repair。
- 不允许通过修改 testbench 绕过错误。
- 不允许擅自改变数据类型或数值容差。

### 12.3 Synth 修复

处理：

- 不支持语法。
- 不可综合结构。
- 循环边界不明确。
- stream 使用错误。
- pragma 冲突。
- 资源爆炸导致综合失败。

### 12.4 Co-sim 与结构修复

用于：

- stream/dataflow deadlock。
- RTL/C mismatch。
- 无效 FIFO 行为。
- 接口握手问题。
- C-sim 无法暴露的结构问题。

策略：

1. 在结构任务中预留早期 Co-sim。
2. 保存超时和报告上下文。
3. 优先小范围调整 FIFO depth、dataflow 边界和生产消费结构。
4. 修复后重新执行 C-sim、Synth、Co-sim。
5. 不在每个普通优化候选上运行 Co-sim。

---

## 13. PPA 优化路线

### 13.1 前置条件

候选必须：

```text
C-sim pass
Synth pass
no hard task constraint violation
```

结构任务还需通过要求的 correctness Co-sim 门控。

### 13.2 第一层：确定性 action

支持：

```text
pipeline
unroll factor 2
unroll factor 4
array partition factor 2
remove or reduce over-aggressive pragma
```

典型映射：

| 现象 | 优先动作 |
|---|---|
| latency 高且资源低 | pipeline 关键 loop |
| II > 1，memory port 受限 | partition |
| 乘法密集且并行度低 | 小 factor unroll |
| timing 失败 | 降低 unroll、拆分组合路径 |
| 资源超限 | 降低 factor、撤销 partition/unroll |
| latency 改善但资源越界 | 淘汰或回退 |

### 13.3 第二层：LLM Planner

输入：

- TaskContext 摘要。
- 当前 kernel 摘要。
- loop/array 分析。
- Synth 指标。
- 资源限制。
- 历史动作及失败原因。
- 剩余工具和 token 预算。

输出结构化 action，不默认重写完整 kernel。

### 13.4 搜索顺序

```text
baseline
  -> pipeline one loop
  -> unroll 2
  -> partition 2
  -> unroll 4 when justified
  -> low-risk combination
  -> LLM structural patch only when necessary
```

默认：

- 有效 Synth 候选最多 3 到 5 个。
- 复杂 LLM 优化最多 1 到 2 次。
- 中间 Co-sim 候选最多 1 个。
- final Co-sim 单独预留。

---

## 14. 双 HLS 预算与 Token 预算

### 14.1 HLS 预算形式

策略层必须支持：

```text
UnifiedCreditBudget
PerToolInvocationBudget
```

统一 credit 示例：

```text
C-sim  = 1
Synth  = 4
Co-sim = 20
```

按工具限制示例：

```json
{
  "csim_max_calls": 8,
  "synth_max_calls": 4,
  "cosim_max_calls": 1
}
```

官方 Budget 仍是唯一真实计费来源；`BudgetPolicy` 只提供只读视图和调用规划。

### 14.2 统一预算接口

```python
class BudgetView:
    def mode(self) -> str: ...
    def can_call(self, tool: str) -> bool: ...
    def remaining(self, tool: str | None = None): ...
    def can_reserve(self, plan: list[str]) -> bool: ...
```

### 14.3 最终验证预留

进入搜索前预留：

```text
final C-sim
final Synth
final Co-sim
safety margin
```

若任务 budget 无法同时完成所有理想阶段，则优先保证正式要求和 correctness，并在报告中记录缺失原因。

### 14.4 Token 预算

记录：

- model。
- purpose。
- prompt hash。
- input/output/total tokens。
- elapsed time。
- cache hit。
- candidate ID。

达到 token 上限后切换为 deterministic-only，并保留 best valid。

---

## 15. 候选生命周期和有效性

### 15.1 状态

```text
CREATED
  -> STATIC_VALID
  -> CSIM_VALID
  -> SYNTH_VALID
  -> TASK_TIMING_VALID
  -> COMPETITION_TIMING_VALID
  -> RESOURCE_VALID
  -> COSIM_VALID
```

失败状态：

```text
UNSUPPORTED_TASK_LAYOUT
STATIC_FAIL
COMPILE_FAIL
CSIM_FAIL
SYNTH_FAIL
TASK_TIMING_FAIL
COMPETITION_TIMING_FAIL
RESOURCE_LIMIT_FAIL
COSIM_FAIL
TIMEOUT
HLS_BUDGET_EXCEEDED
TOKEN_BUDGET_EXCEEDED
INVALID_LLM_OUTPUT
```

### 15.2 有效性定义

```text
correctness_valid = C-sim pass

synth_valid = correctness_valid and Synth pass

constraint_valid =
  synth_valid
  and estimated_clock <= effective clock limit
  and all provided resource limits pass

final_valid =
  constraint_valid
  and final Co-sim pass
```

对于官方明确不要求某类 Co-sim 的内部中间候选，可标记 `COSIM_NOT_RUN`，但最终提交路径仍需完成完整验证和说明。

### 15.3 必须保存

- initial candidate。
- latest correctness-valid。
- latest synth-valid。
- best constraint-valid。
- best latency。
- best timing。
- best resource。
- best token。
- latest Co-sim-valid。
- final selected。

优化失败不得覆盖唯一有效版本。

---

## 16. 候选选择策略

选择顺序：

```text
final validity
  > correctness
  > synthesizability
  > task clock
  > 100 MHz
  > resource limits
  > Co-sim validity
  > latency
  > II
  > resource efficiency
  > HLS calls
  > token
  > iterations
```

同时保存 Pareto 数据，不只保存一个加权分数：

- latency min/max/average。
- II min/max。
- estimated clock。
- LUT/FF/DSP/BRAM/URAM。
- resource margin。
- HLS 工具调用。
- token。
- wall time。
- action history。
- diagnostic history。

---

## 17. LLM 职责边界

### 17.1 LLM 负责

- 从问题描述提取结构化规格。
- 解释初始代码和算法。
- 解释复杂编译、C-sim、Synth 和 Co-sim 错误。
- 生成局部 repair patch。
- 基于 report 输出优化 action。
- 必要时做受控结构重写。

### 17.2 LLM 不负责

- 运行 Vitis。
- 修改官方 header/testbench/build constraints。
- 更改 numerical tolerance。
- 绕过 budget。
- 使用 hidden grading 结果。
- 输出 Docker 挂载命令作为策略。
- 每轮自由重写完整工程。
- 未经校验直接决定 final candidate。

### 17.3 输出形式

优先：

```json
{
  "reasoning_summary": "...",
  "actions": [],
  "risk": "low|medium|high",
  "expected_effect": {},
  "required_revalidation": ["csim", "synth"]
}
```

所有输出必须通过 JSON schema。Patch 必须经过接口保护和静态检查。

---

## 18. 运行模式

| 模式 | 行为 |
|---|---|
| `inspect` | 解析任务包、TaskContext、静态分析和初始分类，不运行 HLS |
| `smoke` | 环境预检和最小官方 HLS 调用 |
| `baseline` | 初始 C-sim、Synth，结构任务按策略运行 Co-sim |
| `repair` | correctness 诊断与有限 repair |
| `optimize` | 从有效 baseline 开始的小预算 PPA 搜索 |
| `full` | inspect + repair + optimize + final C-sim/Synth/Co-sim |
| `replay` | 不调用 LLM，重放已有候选和工具步骤 |
| `compare-models` | 固定任务和固定预算比较开源模型 |

所有模式均通过 Docker 入口执行。

---

## 19. 推荐目录结构

```text
fpt26-agent/
  Dockerfile
  docker-compose.yml
  run-agent.sh
  pyproject.toml
  requirements.lock

  agent/
    main.py
    competition_agent.py
    config.py

    input/
      input_adapter.py
      task_adapter.py
      task_inspector.py
      local_task_builder.py
      project_analyzer.py

    core/
      ir.py
      task_context.py
      candidate.py
      candidate_store.py
      states.py
      run_context.py

    execution/
      harness_backend.py
      result_adapter.py
      environment_check.py

    analysis/
      initial_condition_classifier.py
      log_normalizer.py
      issue_classifier.py
      report_analyzer.py
      static_analyzer.py

    strategy/
      controller.py
      baseline_controller.py
      repair_controller.py
      structural_repair_controller.py
      optimization_controller.py
      budget_policy.py
      selector.py

    transform/
      actions.py
      planner.py
      transformer.py
      patch_guard.py

    llm/
      llm_client.py
      spec_extractor.py
      prompts.py
      token_tracker.py

    generation/
      template_generator.py
      templates/

    reporting/
      manifest_writer.py
      report_exporter.py
      replay_loader.py

  tools/
    preflight_hls_env.py
    smoke_dotproduct_official.py

  tests/
    unit/
    integration/
    docker/

  runs/
  reports/

third_party/
  fpt26_harness/
  fpt26_harness.upstream.json
  fpt26_harness.sha256
```

---

## 20. 运行目录和 Manifest

```text
runs/<task_id>/<run_id>/
  run_manifest.json
  task_snapshot/
  input/
    task_context.json
    ir.json
  candidates/
    c000_initial/
      kernel.cpp
      manifest.json
      static_analysis.json
      diagnostics.json
      actions.json
      result_csim.json
      result_synth.json
      result_cosim.json
      diff.patch
      tokens.json
      logs/
      reports/
  final/
    kernel.cpp
    report.json
    scorecard.json
  transcript/
    official_transcript.json
  replay/
    replay_manifest.json
```

`run_manifest.json` 至少记录：

- Docker image tag/digest。
- Git commit。
- Vitis 和 XRT 版本。
- XRT 来源：`image-default` 或 `host-override`。
- part/platform。
- requested/effective/competition clock。
- resource limits。
- budget mode 和初始配置。
- 模型、版本、许可证。
- HLS 调用和 token。
- task/source/build 文件 hash。
- candidate lineage。
- final kernel hash。
- final selection reason。
- 未执行阶段及原因。

---

## 21. 测试策略

### 21.1 单元测试

覆盖：

- TaskContext/IR V2 校验。
- budget 两种模式。
- tolerance 和 resource limits 解析。
- HarnessBackend 结果标准化。
- LogNormalizer。
- IssueClassifier。
- candidate 状态和 selector。
- LLM schema 和 patch guard。
- replay 禁止 LLM。

### 21.2 官方任务集成测试

按顺序：

1. `dotProduct_optimize`：baseline 与 PPA。
2. `projection_bugfix`：C-sim repair。
3. `residual_stream_deadlock`：Co-sim 和 structural repair。

### 21.3 额外故障型测试

至少构建或收集：

- 编译失败。
- Synth 失败。
- C-sim mismatch。
- timing fail。
- resource limit fail。
- Co-sim mismatch/deadlock。
- per-tool budget exhausted。
- unified credit exhausted。
- unsupported multi-editable source。
- tolerance-sensitive floating-point task。

### 21.4 Docker 测试

- 容器外运行 Agent 时拒绝。
- 缺失 Vitis 时快速失败。
- 未提供 XRT 时使用镜像内 `/opt/xilinx/xrt`。
- host XRT override 生效。
- 未提供 platform 时普通测试/C-sim/Synth 不失败。
- 需要 platform 的模式缺失 `.xpfm` 时明确失败。
- 工作目录为 `/workspace`。
- clean clone 一键构建。
- replay 在无 LLM endpoint 下成功。

---

## 22. 当前进度基线

### 已完成

- [x] 官方 harness 固化到 `third_party/fpt26_harness/`。
- [x] upstream 记录和 SHA-256 完整性基线。
- [x] Dockerfile、Compose 和 `run-agent.sh`。
- [x] Agent 与官方 harness 可在 `/workspace` 导入。
- [x] 宿主机 Vitis + 镜像内 XRT 的环境规则。
- [x] 容器内环境预检。
- [x] `dotProduct_optimize` 初始 kernel 真实 C-sim/Synth smoke。
- [x] 全量 Python 测试在 Docker 内运行。

### 当前任务

```text
HarnessBackend + ResultAdapter
  -> official ToolServer only
  -> absolute run directory
  -> normalized result
  -> budget/transcript preservation
```

当前任务继续执行，无需因 V4 修订返工；只需确保 budget 字段可承载统一 credit 或按工具限制，并保存后续诊断所需的原始 artifact 路径。

---

## 23. 后续实施顺序

### 阶段 1：执行适配层完成

1. 完成 `HarnessBackend`。
2. 完成 `ResultAdapter`。
3. fake server 单元测试。
4. 官方 `dotProduct_optimize` 真实 C-sim/Synth 集成测试。
5. 保持官方 transcript 和 budget 不变。

验收：策略代码不直接调用 shell/Vitis，标准结果 JSON 稳定。

### 阶段 2：任务模型和诊断基础

1. `TaskContext` / HLS IR V2。
2. `TaskAdapter` 和 `TaskInspector`。
3. 构建脚本、tolerance、resource limits 和 budget config 解析。
4. `InitialConditionClassifier`。
5. `LogNormalizer` 和 `IssueClassifier`。

验收：可解释官方任务并输出初始状态和结构化诊断。

### 阶段 3：最小 CompetitionAgent

```text
Task
  -> inspect
  -> initial candidate
  -> C-sim
  -> Synth
  -> constraint check
  -> return best baseline
```

暂不调用 LLM，不做搜索。

验收：`dotProduct_optimize` 通过统一 Agent 主链，不再依赖独立 smoke 脚本作为正式入口。

### 阶段 4：Correctness Repair

1. 确定性编译修复。
2. LLM 局部 repair patch。
3. 最多两轮 repair。
4. 接入 token tracker。
5. 跑通 `projection_bugfix`。
6. 实现明确回退。

验收：repair 不修改接口、header 或 testbench，失败时返回 best known candidate 和诊断。

### 阶段 5：Report-Driven PPA

1. loop/pragma 静态分析。
2. pipeline action。
3. unroll 2/4。
4. partition 2。
5. resource/timing gate。
6. candidate lineage 和 selector。
7. budget 预留。
8. `dotProduct_optimize` 至少一个指标改善。

验收：优化失败不破坏 baseline，资源超限或 timing fail 自动淘汰。

### 阶段 6：Co-sim 和结构修复

1. structural risk detection。
2. baseline/final Co-sim 策略。
3. deadlock/stream 诊断。
4. structural repair。
5. 跑通 `residual_stream_deadlock`。

验收：最终候选完成 C-sim、Synth、Co-sim。

### 阶段 7：辅助输入、Replay 和提交

1. 迁移现有自然语言 spec extractor。
2. 自然语言 vector_add 转 local official-style task。
3. 已有 kernel/project 入口。
4. replay 全容器化。
5. 模型比较。
6. hidden-like 测试。
7. 自动实验报告。
8. clean clone 复现和打包。
9. 5 分钟演示。

---

## 24. 四周映射（如仍按四周执行）

### Week 1：基础执行层

- 官方 harness 固化。
- Docker 入口。
- 环境预检。
- C-sim/Synth smoke。
- HarnessBackend 和 ResultAdapter。

### Week 2：任务解释和 Repair

- TaskContext/IR V2。
- TaskInspector 和初始分类。
- 日志诊断。
- 最小 CompetitionAgent。
- `projection_bugfix`。
- token/replay。

### Week 3：PPA 优化

- 静态分析。
- pipeline/unroll/partition。
- 双预算策略。
- constraint-aware selector。
- `dotProduct_optimize` 改善。

### Week 4：Co-sim、稳定性和提交

- structural repair。
- `residual_stream_deadlock`。
- final Co-sim。
- 模型比较。
- hidden-like 测试。
- 报告、README、打包和演示。

Week 4 不新增大型架构，不更换 Docker 主线，不扩展未经验证的模板。

---

## 25. 明确不做或延后

在端到端闭环完成前不做：

- 第二套 Vitis runner。
- 宿主机 Agent 模式。
- 完整通用 C++ 编译器。
- 大规模设计空间搜索。
- 每轮 Co-sim。
- 全自动多文件复杂重写。
- Web UI。
- 多 Agent 框架。
- 强化学习搜索。
- 将完整 Vitis 安装打入提交镜像。
- 让 LLM 修改官方 header、testbench、tolerance 或 budget。
- 针对 hidden benchmark 的硬编码。

---

## 26. 最终验收清单

### Docker

- [ ] 宿主机只执行 Docker 启动和挂载。
- [ ] Agent、LLM、Harness、Vitis、报告和 replay 全部在容器内。
- [ ] 默认使用镜像内 XRT，支持 host override。
- [ ] platform 只在需要时强制。
- [ ] clean clone 可复现。

### 任务理解

- [ ] 能加载问题描述、源码、public testbench 和 build scripts。
- [ ] 能保存接口、数据类型、tolerance 和 constraints。
- [ ] 能识别 budget mode。
- [ ] 能识别初始任务状态。
- [ ] 不支持的任务布局明确失败。

### Harness 集成

- [ ] 所有 HLS 调用通过 ToolServer。
- [ ] 官方 budget 和 transcript 未被绕过。
- [ ] HarnessBackend 结果稳定序列化。
- [ ] 原始日志和报告可追踪。
- [ ] hidden grading 不参与搜索反馈。

### Agent

- [ ] correctness 优先于 PPA。
- [ ] repair 和优化均有迭代上限。
- [ ] 同时支持统一 credit 和按工具预算视图。
- [ ] token 有预算和审计。
- [ ] task clock、100 MHz 和资源上限均门控。
- [ ] best valid 永久保留。
- [ ] replay 不调用 LLM。
- [ ] final candidate 通过 C-sim、Synth、Co-sim。

### 官方样例

- [ ] `projection_bugfix` repair。
- [ ] `dotProduct_optimize` PPA 改善。
- [ ] `residual_stream_deadlock` structural repair 和 Co-sim。

### 提交

- [ ] Dockerfile 和 Compose。
- [ ] 源码、testbench 和补充材料。
- [ ] 锁定依赖。
- [ ] 模型与许可证说明。
- [ ] 实验报告和结构化结果。
- [ ] 日志、manifest、candidate lineage 和 replay。
- [ ] clean clone 复现记录。
- [ ] 5 分钟演示视频。

---

## 27. 最终技术结论

最终系统应实现为：

> 一个完全运行在 Docker 内、以官方 `Task + ToolServer + Budget + Vitis + Scoring` 为执行和评测内核、能够解释完整任务包并识别多种初始 HLS 问题、在统一或按工具预算内进行 correctness repair 和 constraint-aware PPA optimization、使用开源 LLM 做结构化诊断与局部修改、具有候选回退、最终 Co-sim、token 审计和 replay 能力的端到端 LLM4HLS Agent。

当前最优先链路：

```text
已完成 Docker/HLS 基线
  -> HarnessBackend + ResultAdapter
  -> TaskContext/IR V2
  -> InitialConditionClassifier + Log Diagnostics
  -> Minimal CompetitionAgent
  -> Repair
  -> PPA Optimization
  -> Structural Co-sim Repair
  -> Reproducible Submission
```
