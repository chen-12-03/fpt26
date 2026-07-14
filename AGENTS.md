# AGENTS.md

## 1. 文件目的

本文件定义本仓库中所有代码代理、自动化开发工具和人工开发者必须遵守的工程规则。

项目目标是实现 FPT26 Track-A LLM4HLS 比赛系统：

- 以官方 `fpt26-harness` 为唯一 HLS 执行与评测内核。
- 以自研 `CompetitionAgent` 为策略层。
- 支持官方任务、自然语言规格、已有 HLS kernel 和已有 HLS IR。
- 在工具调用预算和 token 预算内完成 HLS 代码修复与 PPA 优化。
- 所有 Agent、官方 harness、LLM 客户端、Vitis 调用、候选搜索和报告生成均在 Docker 容器内执行。

开始修改代码前，必须先阅读：

```text
roadmap.md
AGENTS.md
README.md
```

发生冲突时，优先级如下：

```text
比赛官方要求
  > roadmap.md 中的架构与阶段约束
  > AGENTS.md
  > README.md
  > 局部代码注释
```

---

## 2. 最高优先级规则

### 2.1 Docker-only

除构建、启动和挂载容器外，不得在宿主机运行项目代码。

宿主机允许执行：

```bash
docker build ...
docker compose build ...
docker run ...
docker compose run ...
./run-agent.sh ...
```

宿主机禁止执行：

```bash
python -m agent.main
python third_party/fpt26_harness/scripts/run_poc.py
pytest
vitis-run
pip install
```

上述命令必须在容器内执行。

任何新脚本、测试文档和 README 示例，都必须默认使用 Docker 命令。

### 2.2 官方 Harness 是唯一 HLS 执行内核

所有 HLS 验证必须通过官方 `ToolServer`：

```python
server.csim(kernel_code)
server.synth(kernel_code)
server.cosim(kernel_code)
```

禁止：

- 新建第二套 Vitis runner。
- 从策略模块直接调用 `vitis-run`。
- 绕过 `ToolServer` 或官方 Budget。
- 在 Agent 中自行生成另一套 HLS Tcl 主链。
- 把旧 `run-hls-in-docker.sh` 恢复为主执行路径。

### 2.3 Agent 只能修改候选 Kernel

对于官方任务：

- 不得修改 header。
- 不得修改 public testbench。
- 不得访问或修改 hidden testbench。
- 不得修改 top function 的外部接口。
- 不得在优化循环中调用 hidden grading。

Agent 的主要输出是候选 kernel 源码。

### 2.4 Correctness First

候选必须按以下顺序验证：

```text
static check
  -> csim
  -> synth
  -> task timing check
  -> 100 MHz compliance check
  -> cosim when required
```

未通过前置阶段的候选不得进入后续阶段或参与 PPA 比较。

### 2.5 永远保留回退候选

任何优化都不得覆盖唯一可工作版本。

每个任务至少保留：

- initial baseline。
- latest valid candidate。
- best valid candidate。
- best latency candidate。
- best timing candidate。
- final cosim candidate。

---

## 3. 仓库预期结构

```text
fpt26-agent/
  AGENTS.md
  roadmap.md
  README.md
  Dockerfile
  docker-compose.yml
  pyproject.toml
  requirements.lock
  run-agent.sh

  third_party/
    fpt26_harness/

  agent/
    main.py
    competition_agent.py
    config.py

    input/
    core/
    execution/
    strategy/
    analysis/
    transform/
    llm/
    generation/
    reporting/

  tasks/
    local/
    hidden_like/

  tests/
    unit/
    integration/
    docker/

  runs/
  reports/
```

如实际仓库尚未完全迁移到该结构，新增代码应朝该结构收敛，不得再扩大旧目录布局。

---

## 4. 目录修改权限

### 4.1 `third_party/fpt26_harness/`

该目录保存官方 harness。

默认规则：只读。

优先使用：

- import。
- adapter。
- composition。
- subclass。
- 外部配置。

只有在官方代码存在阻塞性缺陷且无法通过 adapter 解决时才允许修改。

修改官方代码时必须同时：

1. 保持修改范围最小。
2. 在提交说明中解释原因。
3. 保存可审查 diff。
4. 不将 Agent 策略写入官方核心模块。
5. 增加覆盖该修改的集成测试。
6. 确认官方三个样例任务仍可运行。

禁止修改官方 scoring 以提高本地成绩。

### 4.2 `agent/`

这是自研代码的主要修改区域。

职责边界：

- `input/`：输入检测、Task 适配、本地任务构建和已有项目分析。
- `core/`：IR、Candidate、状态、运行上下文和持久化模型。
- `execution/`：官方 ToolServer adapter、结果规范化和环境预检。
- `strategy/`：baseline、repair、optimization、预算规划和候选选择。
- `analysis/`：错误分类、静态分析和综合报告分析。
- `transform/`：结构化 action、确定性代码变换和受控 patch。
- `llm/`：开源模型客户端、prompt、规格提取和 token 统计。
- `generation/`：保守模板和本地任务 baseline 生成。
- `reporting/`：manifest、实验报告和 replay 数据。

不得跨层直接调用：

```text
strategy -> vitis-run
llm -> ToolServer
transform -> hidden grading
input -> scoring
reporting -> 修改候选代码
```

### 4.3 `runs/` 和 `reports/`

这些目录是生成产物目录。

- 不手工编辑 HLS 指标。
- 不把临时大文件提交到 Git，除非提交要求明确需要。
- 报告中的关键表格必须从 JSON 或官方报告自动生成。
- replay 所需的 manifest、hash 和候选 lineage 必须保留。

---

## 5. 统一调用链

任何正式执行路径必须收敛到：

```text
Input
  -> InputAdapter / TaskAdapter
  -> TaskContext
  -> CompetitionAgent
  -> HarnessBackend
  -> Official ToolServer
  -> Official Vitis / Budget / Transcript
  -> CandidateStore / ReportExporter
```

### 5.1 `HarnessBackend`

所有策略模块只能通过 `HarnessBackend` 使用 HLS 工具。

示例接口：

```python
class HarnessBackend:
    def csim(self, candidate): ...
    def synth(self, candidate): ...
    def cosim(self, candidate): ...
```

`HarnessBackend` 可以：

- 调用官方 ToolServer。
- 规范化官方返回值。
- 关联 candidate ID。
- 持久化 stage result。
- 记录调用前后的官方预算状态。

`HarnessBackend` 不可以：

- 重复实现官方计费。
- 直接调用 shell。
- 生成第二套 Tcl。
- 修改 testbench 或 header。

### 5.2 `CompetitionAgent`

`CompetitionAgent` 是正式策略入口。

最低接口应保持简单：

```python
class CompetitionAgent:
    def run(self, task, server) -> str:
        """Return final kernel source code."""
```

最终返回值必须是可供官方 grading 使用的 kernel 源码。

---

## 6. 输入处理规则

### 6.1 官方任务

官方 `Task` 是正式评测主路线。

数据优先级最高，不得被 CLI 或 IR 静默覆盖：

```text
Official Task
  > Local Task Config
  > HLS IR
  > CLI Override
  > Conservative Default
```

官方 task 中的以下内容必须保持：

- top。
- header files。
- public testbench。
- target part。
- requested clock。
- requires_cosim。
- budget。

### 6.2 自然语言任务

自然语言任务必须先转为经过 schema 校验的 HLS IR，再由 `LocalTaskBuilder` 创建 official-style local task。

不得让自然语言路径维护独立 HLS runner。

近期模板范围限制为：

- vector/map。
- reduction。
- small matrix multiplication。
- generic fixed-bound loop。

在官方三个样例全部通过前，不增加新的大类模板。

### 6.3 已有 Kernel 或已有 IR

已有代码必须进入同一 `CompetitionAgent + ToolServer` 主链。

`replay` 模式必须：

- 禁止调用 LLM。
- 使用已保存候选和配置。
- 重新通过官方工具验证。
- 标记 `llm_called=false`。

---

## 7. 候选数据模型

每个候选必须有不可变 ID，例如：

```text
c000_baseline
c001_repair_missing_include
c002_pipeline_loop_j
c003_unroll2_loop_k
```

候选不得原地覆盖父候选。

每个候选至少记录：

- candidate ID。
- parent candidate ID。
- task ID。
- kernel source。
- kernel hash。
- 创建原因。
- action 列表。
- diff。
- 当前状态。
- static/csim/synth/cosim 结果。
- timing 和 PPA。
- HLS credits。
- token 使用。
- 模型和 prompt hash。
- 创建时间。

候选状态必须使用明确枚举，不使用任意字符串。

推荐状态：

```text
CREATED
STATIC_VALID
CSIM_VALID
SYNTH_VALID
TASK_TIMING_VALID
COMPETITION_TIMING_VALID
COSIM_VALID

STATIC_FAIL
COMPILE_FAIL
CSIM_FAIL
SYNTH_FAIL
TASK_TIMING_FAIL
COMPETITION_TIMING_FAIL
COSIM_FAIL
TIMEOUT
HLS_BUDGET_EXCEEDED
TOKEN_BUDGET_EXCEEDED
INVALID_LLM_OUTPUT
```

---

## 8. 时钟与 PPA 规则

必须区分：

```text
requested_clock_ns   = task.target.clock_ns
competition_limit_ns = 10.0
```

不得把 `10 ns` 用作覆盖官方 task 目标时钟的默认值。

候选报告必须分别记录：

- 是否满足 task requested clock。
- 是否满足比赛最低 100 MHz 要求。

候选选择顺序：

```text
correctness
  > synthesizable
  > requested task clock
  > 100 MHz compliance
  > cosim validity
  > latency
  > II
  > reasonable resource use
  > token
  > iteration count
```

不得仅保存一个加权总分。必须保留完整指标，以便后续重新选择候选。

---

## 9. Repair 和 Optimization 规则

### 9.1 Repair

默认最多 1 到 2 轮。

优先顺序：

```text
错误分类
  -> 确定性修复
  -> 受控 LLM patch
  -> 新候选
  -> 重新验证
```

优先处理：

- 缺失 include。
- 类型不匹配。
- top 签名问题。
- 未定义符号。
- 无效 pragma。
- 动态内存和不支持 STL。
- 数组越界和 shape mismatch。
- 有限模式的 stream/dataflow deadlock。

每轮只修复一个主要问题。

### 9.2 Optimization

确定性优化优先于 LLM。

默认搜索顺序：

```text
baseline
  -> pipeline one loop
  -> unroll factor 2
  -> unroll factor 4
  -> array partition factor 2
  -> low-risk combination
  -> LLM structural rewrite only when necessary
```

每个新候选必须重新通过 C-sim 和 synth。

禁止根据未验证的代码推测性能提升后直接选为 final。

### 9.3 Co-simulation

cosim 成本高，只用于：

- `requires_cosim=true` 的 baseline 或修复候选。
- 当前 best valid 的关键检查。
- final candidate。
- 少量明确需要 RTL 验证的候选。

禁止每轮都跑 cosim。

---

## 10. LLM 使用规范

比赛只允许开源 LLM。

每个模型配置必须记录：

- model name。
- version 或可识别 revision。
- provider/endpoint。
- license 信息。
- prompt hash。
- input/output/total tokens。
- elapsed time。

LLM 优先输出结构化 JSON action，不直接自由重写整个工程。

所有 LLM JSON 必须经过 schema 校验。

无效输出必须：

1. 标记 `INVALID_LLM_OUTPUT`。
2. 不修改当前有效候选。
3. 最多进行一次格式修复请求，或直接回退 deterministic 模式。

不得把以下内容发送给 LLM：

- hidden testbench。
- 不必要的完整 Vitis 日志。
- API key 或其他秘密。
- 与当前问题无关的完整仓库。

日志应先裁剪为最小可诊断摘要。

---

## 11. 双预算规则

### 11.1 HLS 预算

官方 Budget 是唯一真实计费来源。

自研 `BudgetPolicy` 只能做预测和预留，不得重复扣减或篡改官方预算。

开始搜索前必须预留：

- final C-sim。
- final synth。
- final cosim（任务需要时）。
- 安全余量。

### 11.2 Token 预算

默认约束：

- repair LLM 最多 2 次。
- optimization LLM 最多 1 到 2 次。
- 有效 synth candidate 最多 3 到 5 个。
- cosim candidate 最多 1 到 2 个。

达到 token 上限后：

```text
停止 LLM
  -> deterministic-only
  -> 返回 best valid candidate
```

---

## 12. Docker 实现规范

### 12.1 Dockerfile

镜像应包含：

- Python runtime。
- Agent 源码。
- 官方 harness。
- 锁定的 Python 依赖。
- 测试工具。
- 统一容器入口。

默认不把完整 Vitis 安装打入镜像，而是挂载 Vitis 2025.2、XRT 和 U55C platform。

### 12.2 Compose

`docker-compose.yml` 只负责：

- build。
- mount。
- environment。
- user/permission。
- working directory。
- entrypoint。

不得在 Compose 中编写 Agent 策略或候选搜索逻辑。

### 12.3 容器检测

`agent.main` 启动时必须确认运行环境位于容器内。

容器外直接运行正式模式应快速失败，并给出 Docker 启动命令。

### 12.4 环境预检

运行 HLS 前必须检查：

- `vitis-run` 存在。
- Vitis 版本为 2025.2。
- XRT 可用。
- U55C platform 存在。
- part 合法。
- 输出目录可写。
- 输入路径对容器可见。
- 依赖版本匹配。
- LLM 模型符合开源要求。

`inspect` 和纯 replay 元数据检查可根据需要跳过不相关检查；任何实际 HLS 调用不得跳过 Vitis/platform 检查。

---

## 13. 命令规范

所有文档和测试报告中的正式命令使用 Docker。

示例：

```bash
./run-agent.sh \
  --task tasks/dotProduct_optimize \
  --mode full
```

或：

```bash
docker compose run --rm agent \
  python -m agent.main \
  --task /workspace/tasks/dotProduct_optimize \
  --mode full
```

运行单元测试：

```bash
docker compose run --rm agent \
  pytest -q tests/unit
```

运行集成测试：

```bash
docker compose run --rm agent \
  pytest -q tests/integration
```

运行 Docker 边界测试：

```bash
docker compose run --rm agent \
  pytest -q tests/docker
```

禁止在说明中把宿主机 `pytest` 或宿主机 `python` 作为推荐执行方式。

---

## 14. 测试要求

### 14.1 单元测试

新增或修改以下模块必须增加单元测试：

- IR validation。
- TaskAdapter。
- CandidateStore。
- state transitions。
- error classifier。
- result adapter。
- selector。
- token tracker。
- action schema。
- deterministic transformer。

单元测试不得要求实际 Vitis；使用 mock ToolServer。

### 14.2 集成测试

涉及主链的修改必须至少覆盖一个官方样例：

1. `projection_bugfix`：repair。
2. `dotProduct_optimize`：PPA optimization。
3. `residual_stream_deadlock`：structural/cosim。

如本地环境无法运行完整 Vitis，必须至少提供：

- mock 集成测试。
- 明确标记的 Vitis integration test。
- 说明未实际运行的原因。

不得声称未执行的 Vitis 测试已通过。

### 14.3 Docker 测试

必须覆盖：

- 容器外正式运行被拒绝。
- 缺失 Vitis 挂载快速失败。
- 缺失 platform 快速失败。
- 输出目录权限正确。
- clean clone 可构建。
- replay 在无 LLM endpoint 时可运行。

---

## 15. 代码风格

### 15.1 Python

- 使用类型注解。
- 公共接口写 docstring。
- 优先使用 `dataclass`、`Enum` 和显式 schema。
- 禁止用裸字典在模块间传递复杂核心状态，除非处于序列化边界。
- 捕获具体异常，不使用无条件 `except Exception` 吞掉错误。
- 错误信息应包含 task ID、candidate ID 和 stage。
- 路径使用 `pathlib.Path`。
- 不使用个人绝对路径。

### 15.2 Shell

- 使用 `set -euo pipefail`。
- shell 只负责容器启动和轻量入口。
- 不在 shell 中实现候选搜索、日志解析或 HLS 决策。
- 所有变量正确引用。
- 不打印秘密环境变量。

### 15.3 JSON 和 Manifest

- schema 版本必须显式记录。
- 时间使用 ISO 8601。
- hash 算法固定并记录，建议 SHA-256。
- 路径优先保存相对 run directory 的路径。
- 不在 JSON 中写入 API key。

---

## 16. 日志与可审计性

每次运行至少产生：

```text
runs/<task_id>/<run_id>/
  run_manifest.json
  task_snapshot/
  candidates/
  final/
  transcript/
  replay/
```

日志必须能回答：

- 使用了哪个输入和 task 配置。
- 运行在哪个 Docker image。
- 使用哪个 Vitis/XRT/platform。
- 调用了哪些 HLS 工具。
- 消耗多少官方 credits。
- 调用了哪些 LLM。
- 消耗多少 token。
- 每个候选如何从父候选生成。
- 为什么选择最终候选。
- 失败后回退到了哪个候选。

任何修改候选的操作都必须有 action 或 diff 记录。

---

## 17. 安全与秘密

- 不提交 API key、token 或私有 endpoint 凭据。
- `.env` 只提供示例文件 `.env.example`。
- 日志中不得输出完整认证头。
- 运行快照不得复制宿主机敏感目录。
- LLM prompt 和日志中不得包含 hidden testbench。
- Docker mount 使用最小所需范围。

---

## 18. 任务执行工作流

代码代理处理任务时遵循以下顺序。

### 18.1 修改前

1. 阅读相关代码、测试、`roadmap.md` 和本文件。
2. 确认改动属于当前阶段。
3. 确认不会引入第二套 runner。
4. 确认是否触及官方 harness。
5. 识别需要更新的 schema、manifest 和测试。

### 18.2 实现时

1. 保持改动小而可验证。
2. 优先添加 adapter，而不是侵入官方代码。
3. 每个候选相关操作保持 lineage。
4. 所有新命令默认在 Docker 内运行。
5. 为失败路径提供明确日志和回退。

### 18.3 完成后

1. 在容器内运行相关单元测试。
2. 在容器内运行相关集成测试。
3. 检查格式、类型和 schema。
4. 检查没有泄露凭据。
5. 检查文档命令没有宿主机执行路径。
6. 报告实际执行的测试和未执行的测试。

---

## 19. 当前阶段优先级

在 `roadmap.md` 的最小闭环未完成前，优先级固定为：

```text
1. Docker 内跑通官方 harness
2. CompetitionAgent 最小桥接
3. HarnessBackend
4. baseline csim + synth
5. manifest 和 replay
6. projection_bugfix repair
7. pipeline / unroll / partition
8. dotProduct_optimize
9. residual_stream_deadlock cosim
10. 自然语言模板扩展
```

不得为了增加功能数量跳过前面的稳定性任务。

---

## 20. 明确禁止事项

禁止代码代理：

- 在宿主机运行 Agent、测试或 Vitis。
- 创建或恢复第二套 HLS runner 主链。
- 绕过 ToolServer。
- 修改官方 hidden grading 以提高分数。
- 访问 hidden testbench 作为优化反馈。
- 让 LLM 修改官方 header 或 testbench。
- 原地覆盖唯一有效候选。
- 每轮运行 cosim。
- 进行无边界候选搜索。
- 在完成主闭环前开发 Web UI、多 Agent 或强化学习搜索。
- 把完整 Vitis 安装包提交进普通项目镜像。
- 在最后阶段重写核心架构。
- 伪造或手工修改实验指标。
- 声称未运行的测试已通过。

---

## 21. Definition of Done

一项改动只有满足以下条件才算完成：

- [ ] 符合 Docker-only 规则。
- [ ] 未绕过官方 ToolServer 和 Budget。
- [ ] 未修改受保护的官方 task 接口和测试。
- [ ] 核心数据使用明确类型或 schema。
- [ ] 有对应单元测试。
- [ ] 主链改动有集成测试。
- [ ] 失败不会破坏 best valid candidate。
- [ ] token 和 HLS 调用可审计。
- [ ] replay 所需信息完整。
- [ ] 文档命令全部以 Docker 为正式入口。
- [ ] 实际运行的测试结果已记录。
- [ ] 未运行的测试已明确说明。

---

## 22. 最终架构判定

所有设计决策都应支持以下目标：

> 一个完全运行在 Docker 内、以官方 `Task + ToolServer + Budget + Vitis + Scoring` 为执行和评测内核、以自研 `CompetitionAgent` 为策略层、通过确定性 HLS 工程流程托底、由开源 LLM 提供结构化规格理解和优化决策、具有候选回退、双预算、最终 cosim、完整审计和 replay 能力的比赛型 LLM4HLS Agent。

当某项实现与该目标冲突时，应停止扩展并回到最小官方主链。
