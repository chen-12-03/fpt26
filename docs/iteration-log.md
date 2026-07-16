# fpt26-agent-v3 迭代日志

## 2026-07-16 — Preflight：真实 API + Vitis HLS official 死锁链路

### 目的与假设

- 目的：先验证 custom 真实 LLM API 能否驱动 `residual_stream_deadlock` 的候选生成，并由 Vitis 2025.2 实际完成 C-sim、synthesis、RTL co-sim 与 hidden grading。
- 假设：`qwen3-coder-plus` 能根据 co-sim 失败日志修复 official streaming deadlock；本次不修改 Agent 代码，不作为优化迭代的提升声明。
- 数据发送：用户已明确批准将 official task 源码、提示词和日志发送到 custom API；未记录 API key、API URL、prompt 或模型响应正文。

### 配置与命令

- Task：`fpt26-harness/tasks/residual_stream_deadlock`（official）
- Agent：`--mode structural --backend custom --max-structural-attempts 3`
- LLM：`qwen3-coder-plus`，temperature `0.7`，max output tokens `4096`
- 容器限制：4 CPU、16 GiB；单容器运行，独立目录 `runs/api_smoke_deadlock_20260716_r2/`
- 真实评测命令（API key 仅通过 `/tmp/fpt26.env` 注入，未展开）：

```bash
docker run --rm --cpus 4 --memory 16g \
  --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v /home/chen1/projects/fpt26_new:/workspace \
  -v /tools/Xilinx:/tools/Xilinx:ro \
  -w /workspace fpt26-agent-v3:latest \
  bash -lc "source /tools/Xilinx/Vitis/2025.2/settings64.sh; \
    python3 -m agent.main \
      --task /workspace/fpt26-harness/tasks/residual_stream_deadlock \
      --mode structural --backend custom --max-structural-attempts 3 \
      --output-root /workspace/runs/api_smoke_deadlock_20260716_r2"
```

- 评分入口：上述 `agent.main` 的 `agent/workflow.py::step_score()` 直接调用 `scoring/scoring_v3.py::grade()`；最终报告 `schema_version=5`。未使用旧评分、手算分或历史结果回放。

### 真实运行结果

- Workflow trace：starter C-sim PASS（8.0 s）→ synth PASS（12.7 s）→ co-sim FAIL（54.8 s）→ API 候选 1 co-sim FAIL（53.4 s）→ API 候选 2 C-sim PASS（5.0 s）、co-sim PASS（51.3 s）。
- 正确性：run status `completed`；hidden C-sim、candidate synth、hidden co-sim 全部 PASS。
- 当前统一 score：`75.52 / 100`（`scoring/scoring_v3.py`, schema 5）；validity PASS，`q_perf=0.8878`，`q_area=0.7674`，`q_hw=0.8254`，efficiency `0.9149`。
- Latency / II：starter synth `135 cycles / II 136`；candidate synth 原始 `residual_csynth.xml` 为 `68 cycles / II 64`；hidden co-sim measured latency `97 cycles`。V3 scorecard 使用 latency ratio `1.99x`；本次 `ii_applicable=False`，所以评分字段 `ii_ratio=1.00x`。
- 资源：starter → candidate：LUT `539 → 406`（0.75x），FF `248 → 231`（0.93x），DSP/BRAM_18K/URAM 均 `0 → 0`；瓶颈资源 FF，area growth `0.93x`。
- 预算：`66 / 80` credits；工具调用 6 次（C-sim 2、synth 1、co-sim 3）。
- 时间：Agent 计量工具时间 `185.2 s`；scoring 阶段约 `92 s`；按 console 与 run_report 文件时间计算，容器端到端约 `276.1 s`。
- API token：**未采集**。运行时 `OpenAICompatClient` 丢弃响应的 `usage` 字段，无法给出可信 token 数；未用字符数估算。
- 证据：`runs/api_smoke_deadlock_20260716_r2/console.log`、`runs/api_smoke_deadlock_20260716_r2/residual_stream_deadlock/run_report.json`、同目录 `grade/` 下的真实 Vitis 日志与 synthesis XML。

### 结论与下一步

- 结论：真实 custom API、`qwen3-coder-plus`、Vitis 2025.2 与 current scoring_v3 的端到端链路可用，official deadlock 在第 2 个 API 候选上修复。
- 当前缺口：API token consumption 不可观测，无法满足后续每轮预算比较要求。
- 下一组唯一改动：在不改变 `LLMClient.complete()` 和 harness 接口的前提下，采集服务端返回的 token usage 及覆盖率，并写入 run_report/console；随后以相同 task、模型、参数和容器限制真实重跑。

## 2026-07-16 — 可观测性改动：服务端 API token 统计

### 问题假设

- Preflight 已证明真实 API + Vitis 链路可用，但运行时 `OpenAICompatClient` 只返回模型文本，丢弃 OpenAI-compatible 响应中的 `usage`，导致每轮无法比较 API token 消耗。
- 只采集服务端报告的 usage 并保持 `complete(system, user) -> str` 不变，应能补齐预算证据而不改变 prompt、候选生成、harness 或 scoring 行为。

### 唯一改动组

- `fpt26-agent-v3/llm4hls/llm.py`
  - 为真实 `OpenAICompatClient` 和 `OpenRouterClient` 增加线程安全的 token usage 累计器。
  - 记录 request/response/usage 覆盖率，以及服务端返回的 prompt、completion、total tokens。
  - 任一请求失败或响应缺字段时，精确总数写为 `null`，同时保留明确标注的 observed subtotal；不做字符数估算。
- `fpt26-agent-v3/agent/reporting.py`
  - run_report 新增非敏感 `llm` 配置与 `token_usage`；console 输出精确 token 总量或不完整覆盖提示。
  - 不记录 API key、base URL、prompt 或 response 正文。
- `fpt26-agent-v3/tests/test_llm_token_usage.py`
  - 覆盖完整 usage 累计和缺失 usage 时拒绝伪装成精确总数。
- 未修改 `fpt26-harness/`、prompt、Agent 决策或评分公式。

### 验证配置与命令

- 与 preflight 相同：official `residual_stream_deadlock`、`qwen3-coder-plus`、temperature `0.7`、max output tokens `4096`、`--mode structural --backend custom --max-structural-attempts 3`、4 CPU / 16 GiB。
- 独立输出：`runs/api_smoke_deadlock_20260716_r3_tokens/`。
- 单元与 current scoring 回归：

```bash
docker run --rm \
  -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
  -v /home/chen1/projects/fpt26_new:/workspace \
  -w /workspace/fpt26-agent-v3 fpt26-agent-v3:latest \
  python3 -m pytest -q tests/test_llm_token_usage.py scoring/test_scoring_v3.py
```

- 结果：`38 passed`。额外探测的废弃 `tests/test_scoring_v2.py` 有 7 个既存失败，其断言针对旧公式；按目标要求不将其作为当前评分标准，也未修改 V3 迎合旧测试。
- 真实评测命令与 preflight 相同，仅将 `--output-root` 改为 `/workspace/runs/api_smoke_deadlock_20260716_r3_tokens`。
- 评分入口仍为 `agent/workflow.py::step_score()` → `scoring/scoring_v3.py::grade()`；run_report `schema_version=5`。

### 对照结果

- 正确性：preflight PASS → token 版 PASS；hidden C-sim、candidate synth、hidden co-sim 均 PASS，无回退。
- Current score：`75.52 → 75.52`（变化 `0.00`；本组只增加观测，不声明评分提升）。
- Latency / II：starter `135 cycles / II 136`；candidate `68 cycles / II 64`；hidden co-sim measured latency `97 cycles`；V3 latency ratio `1.99x`，`ii_applicable=False`。
- 资源：LUT `539 → 406`、FF `248 → 231`，DSP/BRAM_18K/URAM 均为 0；与 preflight 相同。
- 预算：`66/80` credits；与 preflight 相同。
- API token：服务端完整报告 `1/1` 请求，prompt `3008`、completion `326`、total `3334`，failed requests `0`。
- API 请求解释：repair 日志有两次 co-sim attempt，但第 1 次是在 LLM 前对未修改 kernel 的重复验证；随后只发起 1 次真实 API 请求，候选在下一次 co-sim 通过。因此 `request_count=1` 与代码路径一致。
- 时间：Agent 工具时间 `182.5 s`；scoring 阶段约 `94 s`；文件时间显示端到端约 `275.0 s`。
- 证据：`runs/api_smoke_deadlock_20260716_r3_tokens/console.log`、`runs/api_smoke_deadlock_20260716_r3_tokens/residual_stream_deadlock/run_report.json`、同目录 `grade/` 下 Vitis 日志与 synthesis XML。

### 结论与下一步

- 结论：精确 token 统计已通过真实 API 响应验证，且正确性、score、latency、II、资源和 credits 均无回退。
- 当前最大操作瓶颈：pipeline 的初始 co-sim 已失败，`StructuralRepairAgent` 随后又对同一 kernel 重跑 co-sim，额外消耗 20 credits 和约 50.5 s，且没有产生额外诊断信息。
- 下一轮假设：复用 pipeline 已有的失败 `ToolResult` 来构造第一次 repair prompt，可删除一次重复 co-sim；保持相同 prompt 内容和候选验证门，预计降低 credits、运行时间并通过 efficiency 提升 V3 score。

## 2026-07-16 — Iteration 1：复用已有 co-sim 失败，删除重复验证

### Trace 与最大瓶颈

- 对照运行 `api_smoke_deadlock_20260716_r3_tokens` 的 transcript 为：starter C-sim → starter synth → pipeline co-sim FAIL → `StructuralRepairAgent` 对同一未修改 kernel 再次 co-sim FAIL → 1 次 API 请求 → candidate C-sim → candidate co-sim PASS。
- 第二次失败 co-sim 没有新增代码或诊断信息，却消耗 `20 credits` 和 `50.5 s`，是该 workflow 当前最大的可归因预算/时间浪费。

### 问题假设与唯一改动组

- 假设：`step_structural_repair` 紧跟在失败的 `step_cosim` 后，`state.results[-1]` 已包含当前 kernel 的完整失败日志；第一次 repair 可直接复用它构造同一类 prompt。
- 修改：仅调整 `agent/agents/structural.py`。若最新结果为失败 co-sim，第一次循环复用该 `ToolResult`；standalone 或无可复用结果时仍执行原逻辑。
- 不变项：LLM prompt builder、模型配置、候选提取、每个新候选的 C-sim 和 RTL co-sim 门、harness 接口与 scoring 均不变。

### 配置、命令与评分

- 对照：`runs/api_smoke_deadlock_20260716_r3_tokens/`。
- 候选：`runs/iter1_deadlock_reuse_20260716/`。
- 两者均为 official `residual_stream_deadlock`，`qwen3-coder-plus`，temperature `0.7`，max output tokens `4096`，`--mode structural --backend custom --max-structural-attempts 3`，4 CPU / 16 GiB。
- 真实候选评测命令：

```bash
docker run --rm --cpus 4 --memory 16g \
  --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v /home/chen1/projects/fpt26_new:/workspace \
  -v /tools/Xilinx:/tools/Xilinx:ro \
  -w /workspace fpt26-agent-v3:latest \
  bash -lc "source /tools/Xilinx/Vitis/2025.2/settings64.sh; \
    python3 -m agent.main \
      --task /workspace/fpt26-harness/tasks/residual_stream_deadlock \
      --mode structural --backend custom --max-structural-attempts 3 \
      --output-root /workspace/runs/iter1_deadlock_reuse_20260716"
```

- 回归命令：`python3 -m pytest -q tests/test_llm_token_usage.py scoring/test_scoring_v3.py`（Docker 内），结果 `38 passed`。
- 评分入口：`agent/workflow.py::step_score()` → `scoring/scoring_v3.py::grade()`；两份最终 run_report 均为 `schema_version=5`。

### 真实对照结果

| 指标 | 对照 r3 | Iteration 1 | 变化 |
|---|---:|---:|---:|
| hidden correctness | PASS | PASS | 无回退 |
| current score | 75.52 | 79.21 | +3.69 |
| latency ratio | 1.99x | 1.99x | 0 |
| starter latency / II | 135 / 136 | 135 / 136 | 0 |
| candidate synth latency / II | 68 / 64 | 68 / 64 | 0 |
| hidden co-sim measured latency | 97 | 66 | -31 cycles（采样差异） |
| LUT | 406 | 436 | +30 |
| FF | 231 | 51 | -180 |
| area growth | 0.93x | 0.81x | -0.12x |
| q_hw | 0.8254 | 0.8428 | +0.0174 |
| efficiency | 0.9149 | 0.9399 | +0.0250 |
| credits | 66/80 | 46/80 | -20 |
| Agent 工具时间 | 182.5 s | 133.9 s | -48.6 s |
| 容器端到端时间 | 275.0 s | 227.1 s | -47.9 s |
| API 请求 | 1 | 1 | 0 |
| prompt tokens | 3008 | 3006 | -2 |
| completion tokens | 326 | 329 | +3 |
| total tokens | 3334 | 3335 | +1 |

- Iteration 1 transcript 只有 5 次工具调用：C-sim 2、synth 1、co-sim 2；日志明确出现 `reusing pipeline cosim failure`。
- 评分提升的归因边界：少 20 credits 和约 48 s 可直接归因于本轮 workflow 改动，并体现在 efficiency 提升；candidate 面积与 hidden co-sim latency 的变化受 temperature 0.7 采样影响，因此 `+3.69` 总分不能全部归因于删除重复 co-sim。
- V3 的 `ii_applicable=False`，所以 scorecard 仍显示 `ii_ratio=1.00x`；表中原始 II 来自各自 Vitis synthesis XML，不作为替代 score。

### 结论与下一步

- 结论：本轮 official correctness 无回退，current score 有效提升 3.69，credits 降低 30.3%，端到端时间降低 17.4%，token 基本不变；假设成立。
- generated tasks：暂不运行。当前只验证了一个 official task，尚不足以证明全部 official correctness 无回退。
- 下一步：继续 trace 当前 projection 与 dotProduct official workflows，并用同一真实模型/API/Vitis 配置建立带 token 的当前基线；基于三个 official task 的 current scoring 选择下一最大瓶颈，避免只针对 deadlock 过拟合。

## 2026-07-16 — 三个 official task 当前基线审计

### 目的与运行配置

- 目的：在 Iteration 1 后补齐 projection 与 dotProduct 的当前真实 API + Vitis + token 基线，并与 residual 组成全局瓶颈排序；本节不包含新 Agent 行为改动。
- 真实 LLM：custom `qwen3-coder-plus`，temperature `0.7`，max output tokens `4096`。
- 并发：主机 18 CPU、约 12.2 GiB 可用内存，因此只并行两个隔离容器；projection 4 CPU/4 GiB，dotProduct 6 CPU/8 GiB。运行中未出现 OOM 或 Vitis license 冲突。
- Projection：official `projection_bugfix`，`--mode repair --backend custom --max-repair-attempts 3`，输出 `runs/current_baseline_projection_20260716/`。
- DotProduct：official `dotProduct_optimize`，`--mode optimize --backend custom --max-optimization-rounds 5`，输出 `runs/current_baseline_dot_20260716/`。
- 两项均由 `agent/workflow.py::step_score()` 调用 `scoring/scoring_v3.py::grade()`；最终 run_report 为 `schema_version=5`。

### Current scoring 结果

| 指标 | projection_bugfix | residual_stream_deadlock | dotProduct_optimize |
|---|---:|---:|---:|
| correctness | PASS | PASS | PASS |
| score | 69.14 | 79.21 | 14.48 |
| latency ratio | 1.00x | 1.99x | 4.85x |
| starter latency / II | 0 / 1 | 135 / 136 | 1027 / 1025 |
| candidate latency / II | 0 / 1 | 68 / 64 | 34 / 32 |
| area growth | 1.14x | 0.81x | 75.75x |
| bottleneck resource | LUT | LUT | LUT |
| credits | 11/20 | 46/80 | 32/40 |
| Agent 工具时间 | 约 55 s | 133.9 s | 655 s |
| API requests | 1 | 1 | 3 |
| prompt tokens | 2237 | 3006 | 6874 |
| completion tokens | 557 | 329 | 399 |
| total tokens | 2794 | 3335 | 7273 |

- 三任务平均 current score：`54.28`，由三个 schema-5 run_report score（69.14、79.21、14.48）汇总；不使用旧评分字段。
- Projection 资源：starter LUT 607 → candidate LUT 692（1.14x），其余资源为 0；hidden correctness PASS。
- DotProduct 资源：starter → candidate 为 LUT `156 → 11817`（75.75x）、FF `93 → 1561`（16.78x）、DSP `2 → 64`（32x）；q_area 仅 `0.0259`，是 14.48 分的直接主因。
- DotProduct candidate estimated clock 为 `31.133 ns`，OptimizeAgent 仍只按 cycle latency `1027 → 34` 接受；current scorer 使用 clock × latency，因此 Agent 接受目标与评分目标错配。
- DotProduct transcript 还显示每轮开头重复 synthesis 当前 best：34-cycle candidate 被额外 synth 两次，各约 185 s；三轮共使用 7 次 synth，Agent 工具时间 655 s。
- Projection transcript 同样在 repair 前重复 C-sim 未修改 starter，但仅额外消耗约 6.3 s 和 1 credit，影响远小于 dotProduct 评分错配。
- 容器端到端文件时间（Docker 恢复后由 console birth → run_report mtime 核验）：projection `117.2 s`，dotProduct `867.3 s`；residual Iteration 1 为 `227.1 s`。

### 结论与下一步

- 全局最大瓶颈：dotProduct 的候选选择只优化 cycle latency，允许 75.75x LUT/32x DSP 和严重时钟退化；其 score 比另外两个 official task 低 54.66–64.73 分。
- 下一轮优先级：按提示词/操作策略优先原则，设计 scorer-aligned 候选目标与接受准则，明确使用 clock-adjusted latency 和最差资源增长，而不是只看 cycles；直接复用 `scoring_v3` 公共质量逻辑，禁止复制新公式。
- 重复 synthesis 是第二瓶颈，先不与 scorer-aligned 接受策略混在同一轮修改，以保持可归因性。
- generated tasks 继续不运行：尚未验证 dotProduct 的有效改善。

## 2026-07-16 — Iteration 2：scoring_v3 对齐的优化目标与候选接受门

### Trace 与最大瓶颈

- 三任务 current baseline 平均分为 `54.28`；dotProduct 仅 `14.48`，显著低于 projection `69.14` 和 residual `79.21`。
- DotProduct 的 OptimizeAgent 只比较 cycle latency，接受 `1027 → 34 cycles`，但 candidate estimated clock 恶化到 `31.133 ns`，LUT/FF/DSP 分别增长 `75.75x/16.78x/32x`。current scorer 最终 q_area 仅 `0.0259`、q_hw `0.1585`。
- current `scoring_v3.grade()` 使用 `max(task_clock, estimated_clock) × latency` 和最差资源增长；因此 Agent 的 cycle-only 接受目标与最终评分直接错配，是本轮最大正确性之外的分数瓶颈。
- 第二瓶颈是每轮重复 synthesis current best，但本轮刻意不删除，保留到后续单独归因。

### 外部资料核验

- Docker/WSL integration 暂时中断时查阅 AMD 官方 UG1399：全展开通过复制 loop body 提升并行度，但会增加面积；资源受限时应使用 partial unroll factor。[AMD UG1399 — Unrolling Loops](https://docs.amd.com/r/2025.1-English/ug1399-vitis-hls/Unrolling-Loops)
- AMD 官方还明确指出 unroll/array partition 会增加调度对象和 synthesis runtime，应谨慎使用而非全量展开。[AMD UG1399 — Improving Synthesis Runtime and Capacity](https://docs.amd.com/r/en-US/ug1399-vitis-hls/Improving-Synthesis-Runtime-and-Capacity)
- 外部资料仅用于策略设计；最终 score 仍只来自仓库 current `scoring/scoring_v3.py`。

### 问题假设与唯一改动组

- 假设：让 prompt 和候选接受门都复用 current scorer 的 Q_HW，可拒绝 cycle 更低但 clock/面积灾难性恶化的候选，至少安全保留 starter，并显著提高最终 score、稳定性和预算效率。
- `agent/agents/optimize.py`
  - 新增 optimization-time visible QoR proxy，直接构建 `Anchor/QoREvidence/ValidityGates` 并调用 `scoring.scoring_v3.grade()`；不复制评分公式。
  - cost/time 固定相等，只比较 scorer 返回的 q_hw；C-sim 和 synth 通过后，candidate q_hw 必须严格高于 current best 才接受。
  - 在 prompt 的 synth report 中提供 Q_HW、clock-adjusted latency ratio、area growth 与 bottleneck resource。
- `agent/prompts.py`
  - 统一 prompt 明确：目标是 current Q_HW，不是 cycle latency；有效时间为 `max(target clock, estimated clock) × cycles`，area 取最差资源增长。
  - 长循环优先 partial unroll + matching partial partition，禁止为压低 cycles 盲目 full unroll。
  - 停止条件改为连续两轮无 Q_HW 改善。
- `tests/test_optimize_scoring.py`
  - 用 dotProduct 真实 synth 指标验证 34-cycle/75.75x-LUT candidate 的 qhw `0.1585 < 0.7500` starter。
  - 验证相同面积下真实 latency 改善会提升 Q_HW。
- 未修改 `fpt26-harness/`、最终评分、LLM backend 接口、tool 验证门或本轮明确排除的重复 synthesis 行为。

### 配置、测试与真实命令

- 模型与参数：custom `qwen3-coder-plus`，temperature `0.7`，max output tokens `4096`。
- 回归命令（Docker）：

```bash
python3 -m pytest -q \
  tests/test_optimize_scoring.py \
  tests/test_llm_token_usage.py \
  scoring/test_scoring_v3.py
```

- 结果：`40 passed`。
- DotProduct 真实评测：official `dotProduct_optimize`，6 CPU/8 GiB，`--mode optimize --backend custom --max-optimization-rounds 5`，输出 `runs/iter2_dot_score_aligned_20260716/`。
- Official guard 并发：projection 4 CPU/4 GiB，`--mode repair --max-repair-attempts 3`，输出 `runs/iter2_projection_guard_20260716/`；residual 6 CPU/8 GiB，`--mode structural --max-structural-attempts 3`，输出 `runs/iter2_residual_guard_20260716/`。
- 三项统一命令骨架：

```bash
docker run --rm --cpus <N> --memory <LIMIT> \
  --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
  -v /home/chen1/projects/fpt26_new:/workspace \
  -v /tools/Xilinx:/tools/Xilinx:ro \
  -w /workspace fpt26-agent-v3:latest \
  bash -lc "source /tools/Xilinx/Vitis/2025.2/settings64.sh; \
    python3 -m agent.main --task /workspace/fpt26-harness/tasks/<official-task> \
      --mode <mode> --backend custom <attempt-limit> --output-root <isolated-root>"
```

- 评分入口：每次 `agent.main` 的 `agent/workflow.py::step_score()` → `scoring/scoring_v3.py::grade()`；三份最终 run_report 均为 `schema_version=5`。

### 真实三任务对照

| 指标 | projection 对照 → Iter2 | residual 对照 → Iter2 | dotProduct 对照 → Iter2 |
|---|---:|---:|---:|
| correctness | PASS → PASS | PASS → PASS | PASS → PASS |
| current score | 69.14 → 69.13 | 79.21 → 77.60 | 14.48 → 70.56 |
| latency ratio | 1.00x → 1.00x | 1.99x → 1.99x | 4.85x → 1.00x |
| candidate latency / II | 0 / 1 → 0 / 1 | 68 / 64 → 68 / 64 | 34 / 32 → 1027 / 1025 |
| area growth | 1.14x → 1.14x | 0.81x → 0.93x | 75.75x → 1.00x |
| q_hw | 0.7329 → 0.7329 | 0.8428 → 0.8254 | 0.1585 → 0.7500 |
| credits | 11/20 → 11/20 | 46/80 → 46/80 | 32/40 → 23/40 |
| Agent 工具时间 | 54.7 → 56.6 s | 133.9 → 117.6 s | 655.3 → 270.6 s |
| 端到端时间 | 117.2 → 123.7 s | 227.1 → 206.3 s | 867.3 → 336.0 s |
| API requests | 1 → 1 | 1 → 1 | 3 → 2 |
| total tokens | 2794 → 2956 | 3335 → 3489 | 7273 → 5106 |

- 三任务平均 current score：`54.28 → 72.43`，提升 `18.15`；仅汇总本轮三份 schema-5 official run_report。
- 三任务总 credits：`89 → 80`；总 Agent 工具时间：`843.9 → 444.8 s`；三任务端到端时间之和：`1211.6 → 666.0 s`；总 API tokens：`13402 → 11551`。
- DotProduct 两个真实 API candidates 都为 latency 342 / II 16、clock 3.17 ns，但 LUT 103858、FF 117342、DSP 128，scorer-aligned qhw 仅 0.0385；均被正确拒绝，最终提交 starter。
- Projection 的 -0.01 来自 scoring wall-time efficiency 舍入波动，qhw/资源/credits 不变。
- Residual 的 -1.61 来自 temperature 0.7 下 candidate 资源采样差异（qhw 0.8428 → 0.8254），correctness、latency/II 和 credits 无回退。

### 结论与下一步

- 结论：三项 official correctness 全 PASS；平均 score 提升 18.15，credits、tokens 和运行时间均改善。scorer-aligned 接受门成功阻止灾难性面积候选成为最终提交。
- 本轮没有找到比 starter 更好的 dotProduct candidate；两个 API 回合生成同一失衡架构，说明模型没有收到上一候选被拒绝的结构化反馈。
- generated tasks 暂不运行：虽然 official 平均分改善且正确性无回退，但 dotProduct 的实际优化能力尚未提升，只是安全回退 starter；先继续 official。
- 下一轮唯一假设：增加 rejected-candidate reflection feedback（clock、latency、最差资源增长、Q_HW 与拒绝原因）到下一回合 prompt，引导模型降低 partial unroll/partition factor，而不是重复同一极端方案。重复 synthesis 仍作为独立后续轮处理。

## 2026-07-16 — Iteration 3：rejected-candidate reflection feedback

### Trace 与问题假设

- Iteration 2 的两个 API candidates 完全相同：latency 342、II 16、LUT 103858、FF 117342、DSP 128、Q_HW 0.0385。
- 虽然 scorer-aligned 门正确拒绝了它们，但第 2 回合 prompt 只重新描述 starter，没有上一候选的 pragma、资源或拒绝原因；模型没有条件改变假设。
- 假设：将 rejected candidate 的 pragma 行、synth 指标、Q_HW、area growth、bottleneck 和 required next action 结构化反馈给下一轮，可促使模型降低 partial factor 或更换 pragma class。

### 唯一改动组

- `agent/agents/optimize.py`
  - 候选因 Q_HW 未改善被拒绝后，生成结构化 feedback：status、synth metrics、Q_HW、latency ratio、per-resource growth、bottleneck、候选 pragma 行和下一步要求。
  - 不保存或回传完整模型 response，只保留必要 pragma 证据。
- `agent/prompts.py`
  - 新增可选 `previous_candidate_feedback` payload；存在时要求不得重复相同 pragma/architecture，必须降低 factor 或更换单一 pragma class。
- `tests/test_optimize_scoring.py`
  - 新增 reflection 内容测试，确保真实 scorer metrics 与 pragma evidence 被保留。
- 不变项：scorer-aligned 接受门、候选验证工具、重复 current-best synthesis、harness 与最终评分。

### 配置、命令与评分

- 回归：`python3 -m pytest -q tests/test_optimize_scoring.py tests/test_llm_token_usage.py scoring/test_scoring_v3.py`（Docker），`41 passed`。
- 真实评测：official `dotProduct_optimize`，custom `qwen3-coder-plus`，temperature `0.7`，max output tokens `4096`，6 CPU/8 GiB，`--mode optimize --backend custom --max-optimization-rounds 5`。
- 输出：`runs/iter3_dot_reflection_20260716/`。
- 评分：`agent/workflow.py::step_score()` → `scoring/scoring_v3.py::grade()`；最终 run_report `schema_version=5`。
- Docker 命令与 Iteration 2 dotProduct 相同，仅将 output root 改为 `/workspace/runs/iter3_dot_reflection_20260716`。

### 真实对照结果

| 指标 | Iteration 2 | Iteration 3 | 变化 |
|---|---:|---:|---:|
| hidden correctness | PASS | PASS | 无回退 |
| current score | 70.56 | 70.56 | +0.00 |
| final latency / II | 1027 / 1025 | 1027 / 1025 | 0 |
| final area growth | 1.00x | 1.00x | 0 |
| q_hw | 0.7500 | 0.7500 | 0 |
| credits | 23/40 | 23/40 | 0 |
| Agent 工具时间 | 270.6 s | 512.9 s | +242.3 s |
| 端到端时间 | 336.0 s | 578.5 s | +242.5 s |
| API requests | 2 | 2 | 0 |
| prompt tokens | 4826 | 5215 | +389 |
| completion tokens | 280 | 444 | +164 |
| total tokens | 5106 | 5659 | +553 |

- Round 1：模型生成近 full-unroll 架构，latency 341、II 1、LUT 105199、FF 121486、DSP 2048、Q_HW 0.0379；synthesis 耗时 343.4 s，拒绝。
- Round 2：reflection 后模型确实降低并行 factor，latency 342、II 16、DSP 128、synthesis 98.0 s；但 LUT 103858、FF 117342 仍极高，Q_HW 0.0385，继续拒绝。
- 因最终提交仍为 starter，score/correctness/credits 不变；reflection 改变了架构方向但没有产生可计分改善，且 tokens 与时间明显恶化。
- 本轮只运行 dotProduct official；feedback payload 只由 OptimizeAgent 在 rejection 后传入，未运行 generated tasks，也不据此声称其它 official task 分数变化。

### 结论与下一步

- 结论：问题假设部分成立（第 2 候选从 DSP 2048 降至 128，方案不再完全相同），但平均/任务 score 提升不足 1 分且无 correctness 改善；本轮为一次低提升轮。
- 当前最大确定性预算瓶颈：每轮开头重新 synthesis 未修改的 current best。两轮均保留 starter，却额外调用两次 starter synth，共消耗 8 credits 和约 34 s；这与候选质量无关，可安全复用已有 report。
- 下一轮唯一改动：为 OptimizeAgent 缓存 current-best synthesis report；首次复用 pipeline `step_synth` 结果，候选被拒绝时继续复用相同 best report，候选被接受时直接缓存刚完成的 candidate synth report。保留 API/reflection/scorer 门不变。

## 2026-07-16 — Iteration 4：复用 current-best synthesis report

### Trace 与问题假设

- Iteration 3 的两个候选都被 Q_HW 门拒绝，最终 best 始终是 pipeline 已经 synthesis 的 starter；但 OptimizeAgent 在每个 API 回合开始时仍重新 synthesis 同一份未修改 best。
- Transcript 显示这两次重复 synthesis 共消耗 8 credits；它们不提供新证据，也不影响候选正确性或 current scoring。
- 假设：缓存并复用最近一次 successful synth result，可在不改变 prompt、候选生成、验证门或评分行为的前提下，确定性删除重复工具调用。

### 唯一改动组

- `agent/agents/optimize.py`
  - 新增 `_latest_successful_synth()`，从 pipeline state 中取得最近一次成功 synth result。
  - OptimizeAgent 首轮直接复用 `step_synth` 的 report；候选被拒绝后继续复用 current-best report。
  - 候选被接受时把该候选刚完成的 synth result 设为新缓存；仅在 standalone 调用没有上游结果时保留原 synthesis fallback。
- `tests/test_optimize_scoring.py`
  - 新增 helper 测试，验证选择最近一次成功 synthesis，并忽略失败或非 synth result。
- 不变项：real API 请求、reflection payload、scorer-aligned 接受门、候选 C-sim/synthesis、harness、scoring 实现及所有 prompt。

### 配置、命令与评分

- 回归命令（Docker）：

```bash
python3 -m pytest -q \
  tests/test_optimize_scoring.py \
  tests/test_llm_token_usage.py \
  scoring/test_scoring_v3.py
git diff --check
```

- 结果：`42 passed`，`git diff --check` 通过。
- 真实评测：official `dotProduct_optimize`，custom `qwen3-coder-plus`，temperature `0.7`，max output tokens `4096`，6 CPU/8 GiB，`--mode optimize --backend custom --max-optimization-rounds 5`。
- 输出：`runs/iter4_dot_synth_cache_20260716/`。
- 真实运行命令：

```bash
docker run --rm --cpus 6 --memory 8g \
  --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
  -v /home/chen1/projects/fpt26_new:/workspace \
  -v /tools/Xilinx:/tools/Xilinx:ro \
  -w /workspace fpt26-agent-v3:latest \
  bash -lc "source /tools/Xilinx/Vitis/2025.2/settings64.sh; \
    python3 -m agent.main \
      --task /workspace/fpt26-harness/tasks/dotProduct_optimize \
      --mode optimize --backend custom --max-optimization-rounds 5 \
      --output-root /workspace/runs/iter4_dot_synth_cache_20260716"
```

- 评分入口：`agent/workflow.py::step_score()` → current `scoring/scoring_v3.py::grade()`；最终 `run_report.json` 为 `schema_version=5`。下表 score 不使用手算分、旧公式或其它 report 字段。

### 真实对照结果

| 指标 | Iteration 3 | Iteration 4 | 变化 |
|---|---:|---:|---:|
| hidden correctness | PASS | PASS | 无回退 |
| current score | 70.56 | 72.06 | +1.50 |
| final latency / II | 1027 / 1025 | 1027 / 1025 | 0 |
| final area growth | 1.00x | 1.00x | 0 |
| q_hw | 0.7500 | 0.7500 | 0 |
| credits | 23/40 | 15/40 | -8 |
| synth calls | 5 | 3 | -2 |
| Agent 工具时间 | 512.9 s | 234.3 s | -278.6 s |
| 端到端时间 | 578.5 s | 299.3 s | -279.2 s |
| API requests | 2 | 2 | 0 |
| prompt tokens | 5215 | 5216 | +1 |
| completion tokens | 444 | 324 | -120 |
| total tokens | 5659 | 5540 | -119 |

- 两个回合均打印 `reusing current-best synth report`，工具统计为 C-sim 3 次、synth 3 次；pipeline starter synth 1 次加两个新候选 synth，各 current-best 不再重复 synthesis。
- Round 1：latency 342、II 16、LUT 103858、FF 117342、DSP 128、Q_HW 0.0385，拒绝。
- Round 2：reflection 后 latency 342、II 64、LUT 88312、FF 100210、DSP 32、Q_HW 0.0417，仍拒绝；最终提交 starter，hidden correctness PASS。
- score 增加 1.50 来自 current scorer 的 cost/time efficiency 改善；Q_HW 与正确性不变。减少 2 次 synth 和 8 credits 是缓存改动的直接、确定性归因。
- Iteration 3 的候选采样更慢，故工具/端到端时间降幅不能全部归因于缓存；与候选 synth 更接近的 Iteration 2 相比，工具时间仍由 270.6 s 降至 234.3 s。
- 本轮只运行受改动影响的 dotProduct official；缓存路径仅属于 OptimizeAgent，因此没有复用 projection/residual 的历史结果作为本轮评测，也没有声称二者获得新分数。

### 结论与下一步

- 结论：缓存按预期删除 2 次冗余 synthesis，correctness 和 Q_HW 无回退，score 提升 1.50，credits 从 23 降到 15；假设成立。
- Iteration 3 为 +0.00、Iteration 4 为 +1.50，尚未满足“连续两轮提升不足 1 分且无 correctness 改善”的转向条件。
- 当前最大瓶颈回到候选质量：reflection 逐步降低 DSP factor，但 LUT/FF 仍比 starter 高数百倍。下一轮先 trace 两个真实候选源文件与 transcript，确认具体 partition/unroll pragma，再只实施一组针对性提示词/操作策略改进。
- generated tasks 继续不运行：最终 dotProduct 仍是未优化 starter，尚无真实 Q_HW 改善可补充验证。

## 2026-07-16 — Iteration 5：loop-aware synthesis evidence 与 pragma scope

### 完整 trace 与最大瓶颈

- Iteration 4 两个被拒候选仍有 LUT `103858/88312`、FF `117342/100210`。候选源码显示：
  - Round 1 在函数 body、loop 之前放置 `PIPELINE II=1`，并对两个 1024 元素顶层数组做 cyclic partition factor 32。
  - Round 2 把 partition factor 降至 8，但仍保留相同函数级 PIPELINE；面积仍高达 LUT 88312、FF 100210。
- 原始 Vitis `dotProduct_csynth.xml` 给出此前未被 parser 暴露的关键证据：starter 主循环 `TripCount=1024`、`Latency=1025`、`PipelineII=1`；`Interval-max=1025` 是 top-function transaction interval，不是 loop achieved II。
- 旧 `_diagnose()` 把 `interval_max=1025` 当成 loop II violation，错误建议 PIPELINE/ARRAY_PARTITION。函数级 PIPELINE 后，候选 csynth 的 `SummaryOfLoopLatency` 消失，Vitis 把函数整体 pipeline/flatten，正是 88k–104k LUT 的直接来源。
- 本轮假设：将真实 loop-level Vitis evidence 暴露给 Agent，并明确 pragma scope 与“先小 factor UNROLL、仅在 measured port pressure 后 partition”，可避免函数级 pipeline/顶层数组 banking，生成面积受控候选。

### 唯一改动组：loop-aware synthesis guidance

- `llm4hls/report.py`
  - 向后兼容地新增 `pipeline_type` 与 `loop_metrics`，从 current Vitis 2025.2 `csynth.xml` 的 `PipelineType` 和 `SummaryOfLoopLatency` 解析 loop name、trip count、latency、PipelineII、pipeline depth。
  - report summary 将 overall `Interval` 明确标为 `top_interval`，同时展示 loop-level metrics。
- `agent/agents/optimize.py`
  - `_report()` 把 `TopInterval`、pipeline type 和 loop metrics送入真实 API prompt。
  - `_diagnose()` 只依据 measured loop `PipelineII` 判断 loop II；不再从 top-function interval 推断 memory pressure。
  - 当长循环已经 PipelineII=1 时，建议唯一保守动作：loop body 内 partial UNROLL factor 2；不再建议重复 PIPELINE 或 speculative top-level ARRAY_PARTITION。
- `agent/prompts.py`
  - 明确 loop pragma 必须位于 loop opening brace 后；函数 body scope 的 PIPELINE 可能 flatten/auto-unroll contained loops。
  - 将“partial unroll + matching partition”改为“先 small loop-local unroll，只有 Vitis 明确报告 memory-port pressure 后才加 banking”。
- `tests/test_report_loop_metrics.py` 与 `tests/test_optimize_scoring.py`
  - 覆盖 Vitis loop XML 解析与 TopInterval/loop-II 语义，确保不再出现 `II=1025>1` 的错误诊断。
- 不变项：current `scoring_v3`、Q_HW 接受门、synth cache、reflection 回合数、tool/harness 接口和 LLM backend。

### 测试、真实 API/Vitis 配置与命令

- 回归（Docker）：

```bash
python3 -m pytest -q \
  tests/test_optimize_scoring.py \
  tests/test_report_loop_metrics.py \
  tests/test_llm_token_usage.py \
  scoring/test_scoring_v3.py
git diff --check
```

- 结果：`44 passed`，补丁格式检查通过；更新后的 parser 也实际读取 Iteration 4 starter XML，得到 `trip=1024, lat=1025, II=1`。
- API/model：custom `qwen3-coder-plus`，temperature `0.7`，max output tokens `4096`；所有 usage 均由真实 response usage 返回。
- DotProduct：6 CPU/8 GiB，official `dotProduct_optimize`，`--mode optimize --max-optimization-rounds 5`，输出 `runs/iter5_dot_loop_aware_20260716/`。
- 因统一 prompt 被修改，按当前 11.3 GiB available memory 并发运行两个隔离 official guards：projection 4 CPU/4 GiB；residual 6 CPU/7 GiB；没有启动第三容器。
- 命令骨架：

```bash
docker run --rm --cpus <N> --memory <LIMIT> \
  --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
  -v /home/chen1/projects/fpt26_new:/workspace \
  -v /tools/Xilinx:/tools/Xilinx:ro \
  -w /workspace fpt26-agent-v3:latest \
  bash -lc "source /tools/Xilinx/Vitis/2025.2/settings64.sh && \
    python3 -m agent.main \
      --task /workspace/fpt26-harness/tasks/<official-task> \
      --mode <optimize|repair|structural> --backend custom <attempt-limit> \
      --output-root /workspace/runs/<isolated-iter5-root>"
```

- 首次 dot 命令仅因容器没有 `/usr/bin/time` 在 Agent/API/Vitis 启动前退出；移除该非必要 wrapper 后才生成本轮真实结果，因此不计为 API 请求或评测。
- 最终评分入口均为 `agent/workflow.py::step_score()` → current `scoring/scoring_v3.py::grade()`；三份 `run_report.json` 均为 `schema_version=5`。

### 三项 fresh official 结果

| 指标 | projection_bugfix | residual_stream_deadlock | dotProduct_optimize |
|---|---:|---:|---:|
| hidden correctness | PASS | PASS | PASS |
| current score | 69.14 | 77.60 | 72.06 |
| latency ratio | 1.00x | 1.99x | 1.00x |
| final latency / II(top interval) | 0 / 1 | 68 / 64 | 1027 / 1025 |
| area growth | 1.14x | 0.93x | 1.00x |
| q_hw | 0.7329 | 0.8254 | 0.7500 |
| credits | 11/20 | 46/80 | 15/40 |
| Agent 工具时间 | 58.6 s | 116.0 s | 74.0 s |
| 端到端时间 | 125.1 s | 205.2 s | 138.7 s |
| API requests | 1 | 1 | 2 |
| prompt tokens | 2560 | 3325 | 5664 |
| completion tokens | 556 | 326 | 210 |
| total tokens | 3116 | 3651 | 5874 |

- fresh 三任务平均 current score 为 `(69.14 + 77.60 + 72.06) / 3 = 72.93`；总 credits `72`，Agent 工具时间 `248.6 s`，端到端时间之和 `469.0 s`，API tokens `12641`。
- 相比最近一次 full official Iteration 2 平均 `72.43`，fresh 平均增加 `0.50`；其中 dot 的 1.50 分主要已由 Iteration 4 synth cache 获得，本轮 loop-aware 改动本身没有改变最终 dot score。
- 与最近代码状态的真实对照（Iter2 projection/residual + Iter4 dot）相比：三个 final Q_HW/correctness 基本不变，credits 同为 72；总工具时间约 `408.5 → 248.6 s`、端到端 `629.3 → 469.0 s`，但 total tokens `11985 → 12641`（+656）。时间改善主要来自新候选 synthesis 规模大幅缩小，token 增加来自 loop evidence 与更明确 prompt。

### DotProduct 候选质量对照与结论

- Round 1 严格执行 loop-local `UNROLL factor=2`，没有 PIPELINE/ARRAY_PARTITION：latency `1027 → 515`、loop II 1、LUT `156 → 211`、FF `93 → 138`、DSP `2 → 4`；Q_HW `0.7026 < 0.7500`，正确拒绝。
- Round 2 将同一 UNROLL class 增加为 factor 4：latency 515、loop II 2、LUT 446、FF 179、DSP 4；Q_HW 0.6331，继续拒绝。
- 相比 Iteration 4 候选 Q_HW `0.0385/0.0417` 与 88k–104k LUT，本轮候选达到 Q_HW `0.7026/0.6331` 与 211/446 LUT；问题假设对“候选面积与 synthesis 时间”成立，但没有产生可接受的 Pareto/Q_HW 改善。
- 三项 official correctness 全 PASS、无回退；本轮最终平均 score 可归因提升不足 1 分且无 correctness 改善，记为一次低提升轮。Iteration 4 为 +1.50，因此尚未形成连续两轮低提升。
- generated tasks 仍不运行：dot 最终继续提交 starter，尚无 final Q_HW 改善。
- 当前最大瓶颈：rejection feedback 在 factor 2 已因资源增长被拒后仍写“try factor=2”，模型反而增加到 factor 4，产生确定性更差的第二次 C-sim/synth。下一轮只修正反馈方向：禁止增加同一并行 factor；没有有证据的 resource-neutral alternative 时返回 unchanged best 触发 convergence，以降低 credits/time/tokens。

## 2026-07-16 — Iteration 6：directional rejection feedback

### Trace、假设与唯一改动组

- Iteration 5 Round 1 的 `UNROLL factor=2` 将 latency 降至 515，但 DSP 2→4、Q_HW 0.7026，已证明增加并行度不能胜过 current best 0.7500。
- 旧 feedback 的 `required_next_action` 仍包含“try factor=2”，与“不要重复 prior candidate”矛盾；真实 Round 2 因此把 factor 增至 4，Q_HW 进一步降到 0.6331。
- 假设：将 scorer 方向写入 feedback，明确“speedup 被 area growth 抵消时禁止增大同一 UNROLL/partition factor；无 report-supported resource-neutral alternative 时返回 unchanged best”，可让模型安全收敛并省去第二候选工具调用。
- `agent/agents/optimize.py`
  - `_rejection_feedback()` 新增 current-best Q_HW。
  - 当 latency ratio >1 且 area growth >1 时生成 `directional_constraint`，禁止增加同一并行 factor；`required_next_action` 允许原样返回 current kernel。
- `agent/prompts.py`
  - previous feedback 指令明确 obey directional constraint，不得在 area 已抵消 speedup 时增大 factor，并允许无证据方案时返回 unchanged kernel。
- `tests/test_optimize_scoring.py`
  - 覆盖 current-best Q_HW、禁止增大 factor 和 convergence instruction。
- 未修改 parser、scorer、接受门、缓存、候选验证、回合上限或 harness。

### 测试、配置与真实命令

- 回归：`python3 -m pytest -q tests/test_optimize_scoring.py tests/test_report_loop_metrics.py tests/test_llm_token_usage.py scoring/test_scoring_v3.py`，`44 passed`；`git diff --check` 通过。
- 真实评测：official `dotProduct_optimize`；custom `qwen3-coder-plus`；temperature `0.7`；max output tokens `4096`；6 CPU/8 GiB；`--mode optimize --max-optimization-rounds 5`。
- 输出：`runs/iter6_dot_directional_reflection_20260716/`。
- Docker/Agent 命令与 Iteration 5 dot 完全相同，只替换 output root。
- 评分入口：`agent/workflow.py::step_score()` → current `scoring/scoring_v3.py::grade()`；最终 `run_report.json` 为 `schema_version=5`。

### 真实对照结果

| 指标 | Iteration 5 | Iteration 6 | 变化 |
|---|---:|---:|---:|
| hidden correctness | PASS | PASS | 无回退 |
| current score | 72.06 | 72.06 | +0.00 |
| final latency / top interval | 1027 / 1025 | 1027 / 1025 | 0 |
| final area growth / q_hw | 1.00x / 0.7500 | 1.00x / 0.7500 | 0 |
| credits | 15/40 | 15/40 | 0 |
| C-sim / synth calls | 3 / 3 | 3 / 3 | 0 |
| Agent 工具时间 | 74.0 s | 73.9 s | -0.1 s |
| 端到端时间 | 138.7 s | 138.5 s | -0.2 s |
| API requests | 2 | 2 | 0 |
| prompt tokens | 5664 | 5766 | +102 |
| completion tokens | 210 | 217 | +7 |
| total tokens | 5874 | 5983 | +109 |

- Round 1 稳定复现 loop-local factor 2：latency 515、loop II 1、LUT 211、FF 138、DSP 4、Q_HW 0.7026，拒绝。
- Round 2 没有再增大 factor，但仍生成 factor 2；两份源码仅注释、空白和 pragma 缩进不同。Vitis 指标完全相同（latency 515、top interval 513、LUT 211、FF 138、DSP 4），因此第二次 C-sim/synth 是语义重复。
- 假设仅部分成立：方向约束阻止 factor 4 退化，但没有触发 unchanged convergence；score、credits、工具调用均无改善，tokens 反而增加 109。
- 本轮改动只在 OptimizeAgent rejection feedback 存在时生效，因此只运行 dotProduct official；不复用其它任务结果作为本轮 score，也不运行 generated tasks。

### 阈值判断与下一步

- Iteration 5 与 Iteration 6 的 final dot score 都为 72.06，相对各自直接对照提升均为 0，correctness 均无新改善；已满足“连续两轮平均/任务 score 提升不足 1 分且无 correctness 改善”的转向条件。
- 按既定规则从纯提示词优化转向最小工作流细分。当前最大、可确定归因的瓶颈是 comment/whitespace-only 候选重复验证。
- 下一轮唯一改动：在 OptimizeAgent 中对已 synthesis/rejected candidate 建立忽略注释与布局的语义指纹；下一 API response 若重复已测 candidate，直接复用“rejected”结论并收敛，不调用 C-sim/Vitis synth。保留第二 API reflection，以区分模型推理成本与工具去重收益。

## 2026-07-16 — Iteration 7：rejected candidate 语义去重

### Trace、阈值响应与唯一改动组

- Iteration 6 两个真实候选 synthesis 指标完全一致；源码 diff 仅有注释、空白和 `#pragma` 缩进差异，硬件语义都为 loop-local `UNROLL factor=2`。
- Iteration 5/6 连续两轮 score 提升不足 1 且无 correctness 改善，按规则从纯 prompt 转入最小工作流细分。
- 假设：对已 synthesis 且被 Q_HW 拒绝的 candidate 建立保守 source-normalized fingerprint，可在模型仅改注释/布局时跳过重复 C-sim/synth；不尝试证明任意不同 C++ 程序等价。
- `agent/agents/optimize.py`
  - 新增 `_candidate_fingerprint()`：去除 block/line comments，归一化每行空白；保留表达式、常量、pragma factor 等程序内容。
  - 仅记录已经 C-sim PASS、synth PASS、且 Q_HW 被拒的指纹。
  - 后续 API response 命中指纹时打印明确日志，跳过 C-sim/synth 并收敛；记录 `semantic_duplicate_skips` metadata。
- `tests/test_optimize_scoring.py`
  - 验证注释/布局差异指纹相同而 factor 2/4 不同。
  - 用纯单元 fake state 验证两次语义重复 response 只调用一次 candidate C-sim 与一次 candidate synth；该 fake 仅用于代码回归，不作为 Agent task 评测或 score。
- 不变项：真实评测 backend、LLM requests/reflection、current scorer、候选接受门、Vitis 工具实现、回合上限和 harness。

### 测试、配置与真实命令

- 首次定向测试发现新增行为 fixture 缺少真实 Task 的 `headers/top/kernel_name`，在 prompt 构造前失败；仅补齐测试 fixture 后重跑，生产逻辑未因此修改。
- 最终回归：`python3 -m pytest -q tests/test_optimize_scoring.py tests/test_report_loop_metrics.py tests/test_llm_token_usage.py scoring/test_scoring_v3.py`，`46 passed`；`git diff --check` 通过。
- 真实评测：official `dotProduct_optimize`；custom `qwen3-coder-plus`；temperature `0.7`；max output tokens `4096`；6 CPU/8 GiB；`--mode optimize --max-optimization-rounds 5`。
- 输出：`runs/iter7_dot_candidate_dedup_20260716/`；命令仅相对 Iteration 6 替换 output root。
- 评分入口：`agent/workflow.py::step_score()` → current `scoring/scoring_v3.py::grade()`；最终 run_report `schema_version=5`。

### 真实对照结果

| 指标 | Iteration 6 | Iteration 7 | 变化 |
|---|---:|---:|---:|
| hidden correctness | PASS | PASS | 无回退 |
| current score | 72.06 | 73.00 | +0.94 |
| final latency / top interval | 1027 / 1025 | 1027 / 1025 | 0 |
| final area growth / q_hw | 1.00x / 0.7500 | 1.00x / 0.7500 | 0 |
| credits | 15/40 | 10/40 | -5 |
| C-sim / synth calls | 3 / 3 | 2 / 2 | -1 / -1 |
| Agent 工具时间 | 73.9 s | 49.7 s | -24.2 s |
| 端到端时间 | 138.5 s | 116.7 s | -21.8 s |
| API requests | 2 | 2 | 0 |
| prompt tokens | 5766 | 5766 | 0 |
| completion tokens | 217 | 216 | -1 |
| total tokens | 5983 | 5982 | -1 |

- Round 1 再次得到同一真实 Pareto 点：latency 515、loop II 1、LUT 211、FF 138、DSP 4、Q_HW 0.7026，正确拒绝。
- Round 2 API response 命中 rejected fingerprint，日志为 `semantic duplicate of measured rejected candidate — skip csim/synth and converge`；没有为该 response 创建第二份 candidate Vitis 目录。
- 最终提交仍为 starter，hidden correctness PASS；Q_HW 不变，score +0.94 完全来自 current scorer 的 cost/time efficiency 改善。减少 1 C-sim、1 synth 和 5 credits 是去重改动的直接归因。
- tokens 基本不变，因为本轮刻意保留第二次真实 API reflection，只隔离验证工具去重收益。
- 本轮仅影响 OptimizeAgent，故只评测 dot official；generated tasks 不运行，因 final Q_HW 未改善。

### 结论与下一步

- 工作流去重假设成立，提升稳定、预算效率和 score，但 +0.94 仍低于 1 分；连续低提升状态仍在，继续工作流细分而非返回纯 prompt 调优。
- 重新审视 Iteration 5 fresh official transcript：residual 的两次 cosim 分别用于复现 deadlock 和验证修复，均必要；dot 的重复 candidate 工具已消除；projection 的 pipeline baseline C-sim FAIL 后，RepairAgent 对未修改 starter 再跑一次相同 C-sim，确定性浪费 1 credit 与约 6.6 s。
- 下一轮唯一改动：像已验证的 StructuralAgent 一样，让 RepairAgent 复用 pipeline 最新 failed C-sim result；仅当 standalone 没有上游结果时保留原 C-sim fallback。优先评测 projection official。

## 2026-07-16 — Iteration 8：repair→pipeline successful synth 复用

### 完整 trace 与唯一改动组

- 继续检查 Iteration 5 projection fresh transcript 后发现，比重复 failed C-sim 更大的同源浪费是 successful synth：RepairAgent 在 candidate C-sim PASS 后 synth 一次，紧接着 pipeline `step_synth` 对同一 accepted kernel 再 synth 一次。
- 两次 agent synth 的资源/latency 完全相同，各消耗 4 credits；第二次约 20.5 s，且不是 current scorer 的 hidden synthesis。
- 为保持单轮归因，本轮只消除 duplicate synth；pipeline failed C-sim 仍由 RepairAgent 重跑，留到下一轮。
- `agent/workflow.py::step_synth()`
  - 仅当 `state.synth_ok=True` 且 transcript 最后一个紧邻 result 是 successful synth with report 时复用。
  - 邻接与 synth_ok 双门防止使用不同 kernel 的陈旧结果；其它 mode/standalone 没有 upstream synth 时保留真实 `server.synth()`。
- `tests/test_workflow_synth_reuse.py`
  - 验证邻接 upstream success 不调用 server；被其它 result 隔开时必须真实 synth。
- 不变项：RepairAgent 内部验证、baseline/candidate C-sim、API prompt/requests、scorer、hidden grading、harness 和其它 Agent。

### 测试、配置与真实命令

- 回归：`python3 -m pytest -q tests/test_workflow_synth_reuse.py tests/test_optimize_scoring.py tests/test_report_loop_metrics.py tests/test_llm_token_usage.py scoring/test_scoring_v3.py`，`48 passed`；`git diff --check` 通过。
- 真实评测：official `projection_bugfix`；custom `qwen3-coder-plus`；temperature `0.7`；max output tokens `4096`；4 CPU/4 GiB；`--mode repair --max-repair-attempts 3`。
- 输出：`runs/iter8_projection_synth_reuse_20260716/`。
- Docker 命令与 Iteration 5 projection guard 相同，仅替换 output root。
- 评分入口：`agent/workflow.py::step_score()` → current `scoring/scoring_v3.py::grade()`；run_report 为 `schema_version=5`。hidden grader 仍独立运行 candidate/starter synth，没有用 Agent cache 替代评分工具。

### 真实对照结果

| 指标 | Iteration 5 projection | Iteration 8 | 变化 |
|---|---:|---:|---:|
| hidden correctness | PASS | PASS | 无回退 |
| current score | 69.14 | 70.61 | +1.47 |
| latency ratio / q_hw | 1.00x / 0.7329 | 1.00x / 0.7329 | 0 |
| candidate LUT / area growth | 692 / 1.14x | 692 / 1.14x | 0 |
| credits | 11/20 | 7/20 | -4 |
| C-sim / synth calls | 3 / 2 | 3 / 1 | 0 / -1 |
| Agent 工具时间 | 58.6 s | 37.3 s | -21.3 s |
| 端到端时间 | 125.1 s | 103.7 s | -21.4 s |
| API requests | 1 | 1 | 0 |
| prompt / completion tokens | 2560 / 556 | 2588 / 556 | +28 / 0 |
| total tokens | 3116 | 3144 | +28 |

- 日志明确出现 `synth: reusing upstream successful synth report`；transcript 只有 1 次 synth，且该次是 RepairAgent 对 accepted kernel 的真实 Vitis synthesis。
- 最终代码、LUT、Q_HW 和 correctness 与对照一致；score +1.47 完全来自 current scorer cost/time efficiency，减少 1 synth 和 4 credits 可直接归因于本轮复用。
- token 小幅 +28 是 prompt 计数/模型输入波动，与 synth reuse 无因果收益；API request 与 completion tokens 不变。
- 本轮只改变 repair→synth 邻接路径，因此只运行 projection official；generated tasks 不运行。

### 结论与下一步

- 假设成立，且本轮 +1.47 超过 1 分；连续低提升计数重置，但仍保留工作流的确定性去重方向。
- 当前 projection transcript 仍有 baseline failed C-sim 后 RepairAgent 对未修改 starter 重跑同一 failed C-sim（1 credit、约 6.3 s）。
- 下一轮唯一改动：RepairAgent attempt 1 复用紧邻 pipeline failed C-sim；candidate 修改后仍必须真实 C-sim，standalone 没有上游 result 时保留 fallback。

## 2026-07-16 — Iteration 9：RepairAgent failed C-sim 复用

### Trace、假设与唯一改动组

- Iteration 8 已删除 duplicate synth；剩余 transcript 中 pipeline baseline C-sim 对 starter FAIL，RepairAgent attempt 1 在未修改 code 的情况下再次 C-sim，得到相同 failure。
- 假设：像 StructuralAgent 复用 failed cosim 一样，RepairAgent 复用紧邻 pipeline failed C-sim，可删除 1 次确定性重复工具；LLM candidate 仍必须真实 C-sim 和 synth。
- `agent/agents/repair.py`
  - attempt 1 仅在 transcript 最后一个紧邻 result 是 failed C-sim 时复用并记录日志。
  - attempt 2 及后续修改后的 code 继续真实 C-sim；standalone 无上游 failure 时保持原行为。
- `tests/test_repair_csim_reuse.py`
  - 验证上游 failure 不重跑，candidate 只执行一次 C-sim 和一次 synth，并保留结果序列。
- 不变项：successful synth 复用、prompt/API、修复代码、hidden scoring、budget 计价和 harness。

### 测试、配置与真实命令

- 回归：`python3 -m pytest -q tests/test_repair_csim_reuse.py tests/test_workflow_synth_reuse.py tests/test_optimize_scoring.py tests/test_report_loop_metrics.py tests/test_llm_token_usage.py scoring/test_scoring_v3.py`，`49 passed`；`git diff --check` 通过。
- 真实评测：official `projection_bugfix`；custom `qwen3-coder-plus`；temperature `0.7`；max output tokens `4096`；4 CPU/4 GiB；`--mode repair --max-repair-attempts 3`。
- 输出：`runs/iter9_projection_csim_reuse_20260716/`；命令仅相对 Iteration 8 替换 output root。
- 评分入口：`agent/workflow.py::step_score()` → current `scoring/scoring_v3.py::grade()`；run_report `schema_version=5`。

### 真实对照结果

| 指标 | Iteration 8 | Iteration 9 | 变化 |
|---|---:|---:|---:|
| hidden correctness | PASS | PASS | 无回退 |
| current score | 70.61 | 70.97 | +0.36 |
| latency ratio / q_hw | 1.00x / 0.7329 | 1.00x / 0.7329 | 0 |
| candidate LUT / area growth | 692 / 1.14x | 692 / 1.14x | 0 |
| credits | 7/20 | 6/20 | -1 |
| C-sim / synth calls | 3 / 1 | 2 / 1 | -1 / 0 |
| Agent 工具时间 | 37.3 s | 31.1 s | -6.2 s |
| 端到端时间 | 103.7 s | 96.4 s | -7.3 s |
| API requests | 1 | 1 | 0 |
| prompt / completion tokens | 2588 / 556 | 2588 / 559 | 0 / +3 |
| total tokens | 3144 | 3147 | +3 |

- 日志明确出现 `repair: reusing pipeline C-sim failure`；最终 transcript 只有 baseline failed C-sim、candidate passed C-sim、candidate successful synth 三次真实 agent tool calls。
- correctness、代码、资源与 Q_HW 不变；score +0.36 来自 current scorer cost/time efficiency。减少 1 credit/1 C-sim 是本轮直接归因。
- Agent 修复与 official reference 的硬件语义一致，仅注释/格式不同；LUT 607→692 来自补齐第三个正确除法/加法项，是正确性相对错误 starter 的不可避免面积，不是 LLM 冗余实现。
- 本轮只影响 RepairAgent，故只评测 projection official；generated tasks 不运行。

### 结论与下一步

- 假设成立，但本轮提升不足 1 分且无 correctness 新改善，记为 Iteration 8 重置后的第一次低提升轮。
- Projection agent 侧已接近安全最小工具集合：baseline C-sim、candidate C-sim、candidate synth；继续删除会牺牲功能或 synthesis 验证。
- 当前最大工具成本转为 residual structural：fresh transcript 使用 baseline synth 4 credits/12.7 s，随后 cosim 自身再次完成 synthesis 才复现 deadlock；StructuralRepairAgent prompt/acceptance 和 final scorer都不消费该独立 baseline synth report。
- 下一轮先 trace `step_synth → step_cosim → StructuralRepairAgent` 的数据依赖与报告字段，验证是否能让 structural mode 的 cosim 同时承担 synthesis gate；若不能保持 `synth_ok`/latency reporting，则不实施跳过。

## 2026-07-16 — Iteration 10：CoSimTool 透传 synthesis evidence

### 完整 trace 与唯一改动组

- `CoSimTool` 的 TCL 固定执行 `csynth_design` 后再执行 `cosim_design`；但旧 ToolResult 只返回 cosim status/latency，丢弃同一目录已经生成的 `csynth.xml`。
- Structural pipeline 因此在 cosim 前额外调用 standalone synth。该 report 不被 StructuralRepairAgent prompt/acceptance 或 final scorer消费；fresh residual 中浪费 4 credits、12.7 s。
- 假设：让 cosim 返回其内部真实 synth report，并由 structural-only mode 把它作为 synth gate/latency evidence，可删除 standalone synth，同时保持 `synth_ok`、baseline report 和实际 RTL cosim。
- `llm4hls/tools.py`
  - CoSimTool 在 timeout/cosim fail/pass 三条路径解析已有 `csynth.xml` 并附加 `SynthReport`；synthesis 本身失败时仍返回 `synth_error`。
- `agent/workflow.py`
  - `step_cosim()` 在 embedded report 存在时设置 `synth_ok=True` 和 baseline `best_latency`。
  - 仅 `mode=structural` 且 `requires_cosim=True` 时省略独立 `step_synth`；repair/optimize/full/baseline 路径保持原顺序。
- `tests/test_structural_cosim_synth_evidence.py`
  - 验证 structural pipeline 步骤不含 standalone synth，并验证 cosim report 传播 synth gate/latency。
- 不变项：两次真实 Vitis csynth+RTL cosim、StructuralRepairAgent、候选 C-sim、hidden scoring、API prompt/model、budget 单价与 harness。

### 测试、配置与真实命令

- 回归：`python3 -m pytest -q tests/test_structural_cosim_synth_evidence.py tests/test_repair_csim_reuse.py tests/test_workflow_synth_reuse.py tests/test_optimize_scoring.py tests/test_report_loop_metrics.py tests/test_llm_token_usage.py scoring/test_scoring_v3.py`，`51 passed`；`git diff --check` 通过。
- 真实评测：official `residual_stream_deadlock`；custom `qwen3-coder-plus`；temperature `0.7`；max output tokens `4096`；6 CPU/8 GiB；`--mode structural --max-structural-attempts 3`。
- 输出：`runs/iter10_residual_cosim_synth_evidence_20260716/`。
- Docker 命令与 Iteration 5 residual guard 相同，仅替换 output root 和使用 8 GiB 上限。
- 评分入口：`agent/workflow.py::step_score()` → current `scoring/scoring_v3.py::grade()`；run_report 为 `schema_version=5`。

### 真实对照结果

| 指标 | Iteration 5 residual | Iteration 10 | 变化 |
|---|---:|---:|---:|
| hidden correctness / cosim | PASS / PASS | PASS / PASS | 无回退 |
| current score | 77.60 | 78.01 | +0.41 |
| latency ratio / q_hw | 1.99x / 0.8254 | 1.99x / 0.8254 | 0 |
| candidate latency / top interval | 68 / 64 | 68 / 64 | 0 |
| candidate LUT / FF | 406 / 231 | 406 / 231 | 0 |
| credits | 46/80 | 42/80 | -4 |
| C-sim / standalone synth / cosim | 2 / 1 / 2 | 2 / 0 / 2 | 0 / -1 / 0 |
| Agent 工具时间 | 116.0 s | 101.7 s | -14.3 s |
| 端到端时间 | 205.2 s | 193.7 s | -11.5 s |
| API requests | 1 | 1 | 0 |
| prompt / completion tokens | 3325 / 326 | 3363 / 326 | +38 / 0 |
| total tokens | 3651 | 3689 | +38 |

- 首次真实 cosim 仍复现 deadlock，且同一 ToolResult 携带 baseline synth latency 135、top interval 136、LUT 539、FF 248。
- 修复后真实 cosim PASS，ToolResult 携带 candidate synth latency 68、top interval 64、LUT 406、FF 231，以及 measured RTL cosim latency 97。
- console/reporting 的 `synth=PASS` 保持正确；transcript 只删除独立 synth，两个 cosim 都实际执行 csynth 和 RTL simulation。
- Q_HW/correctness/latency/resources 不变；score +0.41 来自 current scorer cost/time efficiency，减少 4 credits 与 standalone synth 是本轮直接归因。
- run_report 顶层 `best_latency` 仍为 baseline 135，未更新为 candidate synth 68；schema-v5 scoring 使用独立 hidden candidate evidence，最终 latency ratio/score 正确。该项是 reporting metadata 问题，不影响本轮 final score。
- 本轮只影响 structural-only path，因此只评测 residual official；generated tasks 不运行。

### 阈值判断与下一步

- Iteration 9 +0.36、Iteration 10 +0.41，连续两轮提升不足 1 且无 correctness 新改善；再次满足工作流/专用反馈转向条件。
- 当前安全最小工具集合：projection 为 baseline C-sim + candidate C-sim + candidate synth；residual 为 baseline C-sim + failed cosim + candidate C-sim + passed cosim；dot 为 baseline C-sim/synth + factor-2 candidate C-sim/synth。
- Dot Iteration 7 的第二 API response 被去重后不再消耗工具/credits，但仍占 2/2 requests 与约一半 5982 tokens。多轮真实证据表明：starter dominant loop 已 PipelineII=1；candidate 只增加最小非平凡 `UNROLL factor=2`，Q_HW 下降；更大 factor 更差，而第二 reflection 重复 factor 2。
- 下一轮只实现 scorer/report-supported 的 minimum-factor frontier convergence：当 candidate 相对 best 仅新增单个 loop-local `UNROLL factor=2`、功能通过但 Q_HW 因 area growth 被拒，直接判定该 pragma class 无更小可探索 factor，跳过第二 API reflection。其它候选/pragma class 保持两轮策略。

## 2026-07-16 — Iteration 11：minimum-factor frontier convergence

### Trace、阈值响应与唯一改动组

- Iteration 7 已用工具去重消除第二 candidate C-sim/synth，但第二 API reflection 仍占 2/2 requests 与 5982 tokens 的约一半。
- 多轮真实 Vitis 证据一致：starter dominant loop 已 PipelineII=1；candidate 除 `UNROLL factor=2` 外代码逻辑不变；factor 2 是最小非 no-op parallel step，latency 1027→515 但 DSP 2→4、Q_HW 0.7026 < 0.7500；factor 4 更差。
- Iteration 9/10 连续低提升后，本轮继续工作流级专用 frontier feedback，不再只依赖第二次 LLM 自觉收敛。
- `agent/agents/optimize.py`
  - 新增 `_without_hls_pragmas_fingerprint()`，仅用于确认 best/candidate 除 standalone HLS directive 外程序一致。
  - 新增严格 `_is_minimum_unroll_frontier()`：必须且仅有一个 `UNROLL factor=2`、baseline 所有可见 loop PipelineII=1、程序其余逻辑一致、measured latency ratio >1、area growth >1，并且 candidate 已由 current scorer Q_HW 门拒绝。
  - 命中后在下一 API request 前收敛；其它 factor、其它 pragma、多项代码修改或 loop II>1 均保留原 reflection。
- `tests/test_optimize_scoring.py`
  - 覆盖严格 positive/negative gates，并验证 minimum frontier 只调用一次 API、一次 candidate C-sim/synth。
- 不变项：第一次真实 API、candidate C-sim/synth、current scorer、接受门、candidate fingerprint 去重、hidden grading、harness。

### 测试、配置与真实命令

- 回归：`python3 -m pytest -q tests/test_optimize_scoring.py tests/test_structural_cosim_synth_evidence.py tests/test_repair_csim_reuse.py tests/test_workflow_synth_reuse.py tests/test_report_loop_metrics.py tests/test_llm_token_usage.py scoring/test_scoring_v3.py`，`53 passed`；`git diff --check` 通过。
- 真实评测：official `dotProduct_optimize`；custom `qwen3-coder-plus`；temperature `0.7`；max output tokens `4096`；6 CPU/8 GiB；`--mode optimize --max-optimization-rounds 5`。
- 输出：`runs/iter11_dot_minimum_frontier_20260716/`；命令仅相对 Iteration 7 替换 output root。
- 评分入口：`agent/workflow.py::step_score()` → current `scoring/scoring_v3.py::grade()`；run_report `schema_version=5`。

### 真实对照结果

| 指标 | Iteration 7 | Iteration 11 | 变化 |
|---|---:|---:|---:|
| hidden correctness | PASS | PASS | 无回退 |
| current score | 73.00 | 73.00 | +0.00 |
| final latency / q_hw | 1027 / 0.7500 | 1027 / 0.7500 | 0 |
| credits / tool calls | 10/40 / 4 | 10/40 / 4 | 0 |
| Agent 工具时间 | 49.7 s | 50.2 s | +0.5 s |
| 端到端时间 | 116.7 s | 114.9 s | -1.8 s |
| API requests | 2 | 1 | -1 |
| prompt tokens | 5766 | 2656 | -3110 |
| completion tokens | 216 | 106 | -110 |
| total tokens | 5982 | 2762 | -3220（-53.8%） |

- 唯一 API candidate 完成真实 C-sim+synth：latency 515、top interval 513、loop II 1、LUT 211、FF 138、DSP 4、Q_HW 0.7026；被 current Q_HW 门拒绝。
- 日志随后明确 `minimum UNROLL factor=2 already loses Q_HW with loop II=1 — converge before another API round`，未发送第二 request。
- 最终 correctness/Q_HW/credits 与 Iteration 7 一致，因此 schema-v5 score 不变；tokens 减少 3220 是本轮直接归因。端到端仅下降 1.8 s，说明 custom API 第二 request 延迟在不同采样中不是稳定主项，但 token 节省稳定。
- 本轮只影响严格 OptimizeAgent frontier case，故只评测 dot official；generated tasks 不运行。

### 结论与下一步

- 假设成立：在不减少任何真实 Vitis candidate 验证、不改变最终选择的前提下，API requests 与 token 消耗约减半。
- 本轮 score +0 且无 correctness 新改善，为 Iteration 10 后又一次低 score 轮；但预算目标中的 API token efficiency 有显著改善。
- 当前三条 official Agent 路径均已达到安全工具下限附近。下一轮优先修复结果一致性：StructuralRepairAgent 的 passed cosim 现已携带 candidate synth latency 68，但顶层 `best_latency` 仍保留 baseline 135；非-cosim task console 还将 `cosim_ok=False` 显示为 FAIL，而 current scorer 正确为 N/A。只修 reporting/state propagation，不改 score 或工具。

## 2026-07-16 — Iteration 12：state/reporting consistency

### 问题与唯一改动组

- Iteration 10 的 passed candidate cosim 已携带 synth latency 68，但 StructuralRepairAgent 成功返回时没有传播 report，run_report 顶层 `best_latency` 仍为 baseline 135。
- Projection/dot 不要求 cosim，current scorer 正确记录 `cosim_pass=null`，但 state 默认 false 导致 console `cosim=FAIL` 和 run_report `cosim_ok=false`，容易误读正确性。
- 本轮只修状态/展示一致性，不改 current score、工具、prompt 或接受逻辑：
  - `agent/agents/structural.py` 在 passed cosim 有 embedded report 时传播 `synth_ok` 与 candidate synth latency。
  - `agent/reporting.py` 对 `requires_cosim=False` 明确输出 `cosim=N/A`，JSON 为 `null`；required task 保留真实 bool。
  - 新增 reporting status 与 StructuralRepairAgent candidate latency 测试。

### 测试与真实并发 guards

- 回归：`python3 -m pytest -q tests/test_reporting_state_consistency.py tests/test_structural_cosim_synth_evidence.py tests/test_optimize_scoring.py tests/test_repair_csim_reuse.py tests/test_workflow_synth_reuse.py tests/test_report_loop_metrics.py tests/test_llm_token_usage.py scoring/test_scoring_v3.py`，`56 passed`；`git diff --check` 通过。
- 当前 available memory 11.45 GiB；并发两个隔离容器，不启动第三个：
  - residual：6 CPU/7 GiB，输出 `runs/iter12_residual_reporting_guard_20260716/`。
  - projection：4 CPU/4 GiB，输出 `runs/iter12_projection_reporting_guard_20260716/`。
- 两项均用 custom `qwen3-coder-plus`、temperature 0.7、max output tokens 4096、真实 API 与 Vitis；命令延续此前同 task 模式/attempt limit。
- 评分入口：`agent/workflow.py::step_score()` → current `scoring/scoring_v3.py::grade()`；两份 run_report 均为 `schema_version=5`。

### 真实结果

| 指标 | projection Iter9 → Iter12 | residual Iter10 → Iter12 |
|---|---:|---:|
| hidden correctness | PASS → PASS | PASS → PASS |
| current score | 70.97 → 70.96 | 78.01 → 78.00 |
| q_hw | 0.7329 → 0.7329 | 0.8254 → 0.8254 |
| credits | 6 → 6 | 42 → 42 |
| Agent 工具时间 | 31.1 → 34.0 s | 101.7 → 105.2 s |
| 端到端时间 | 96.4 → 103.0 s | 193.7 → 197.4 s |
| API requests | 1 → 1 | 1 → 1 |
| total tokens | 3147 → 3144 | 3689 → 3679 |
| 顶层 cosim status | false（误导）→ N/A/null | true → true |
| 顶层 best_latency | 0 → 0 | 135 → 68 |

- Projection console 与 JSON 均正确表示 cosim N/A；scoring 原本即为 null，无分数语义变化。
- Residual run_report `best_latency=68` 与 passed candidate csynth 一致；scorecard latency ratio、candidate resources 和 hidden correctness保持不变。
- 两项 score 各 -0.01，来自并发运行下 hidden grading wall-time efficiency 舍入；cost、Q_HW、资源和功能均无回退。
- 本轮没有 final score 改善，且与 Iteration 11 连续构成低 score 轮；继续按规则做 workflow/prompt 职责细分。
- generated tasks 不运行：本轮只有 reporting 修复，没有 official scoring 的有效新改善。

### 下一步

- 当前 `REPAIR_SYSTEM`、`STRUCTURAL_REPAIR_SYSTEM`、`OPTIMIZE_SYSTEM` 全部指向约千词统一 `_SYS`。Projection repair request 携带无关的 DATAFLOW/array/optimization 章节；residual structural request 携带无关的 Q_HW/unroll/partition 章节。
- 下一轮唯一改动：按既有 Agent 职责边界拆分三个 system prompt；repair 仅保留 functional log-driven fix/no pragma，structural 仅保留 bounded FIFO/dataflow deadlock，optimize 保留完整 scorer-aware HLS discipline。用 projection+residual official real API guards 验证 correctness，并比较 prompt tokens。

## 2026-07-16 — Iteration 13：role-specific system prompts

### 假设与唯一改动组

- 旧 `REPAIR_SYSTEM`、`STRUCTURAL_REPAIR_SYSTEM`、`OPTIMIZE_SYSTEM` 均指向完整统一 `_SYS`，使 projection repair 携带 DATAFLOW/Q_HW/array 章节，residual structural 携带 unroll/partition/scorer 章节。
- 假设：按已存在的 Agent 职责边界拆分 system prompt，可降低 token 且保持 correctness/score。
- `agent/prompts.py`
  - Repair system 只保留 log-driven minimal functional fix、signature/header contract、禁止 pragma/optimization。
  - Structural system 只保留 bounded FIFO、DATAFLOW ordering/rate balance、interleave/depth 修复和 minimal structural change。
  - Optimize system 保留完整 scorer-aware `_SYS`。
- `tests/test_role_system_prompts.py` 覆盖职责隔离与共同输出 contract。
- 未修改 user payload builder、Agent 逻辑、工具、scorer、预算或 harness。

### 测试与真实并发命令

- 回归：`python3 -m pytest -q tests/test_role_system_prompts.py tests/test_reporting_state_consistency.py tests/test_structural_cosim_synth_evidence.py tests/test_optimize_scoring.py tests/test_repair_csim_reuse.py tests/test_workflow_synth_reuse.py tests/test_report_loop_metrics.py tests/test_llm_token_usage.py scoring/test_scoring_v3.py`，`58 passed`；`git diff --check` 通过。
- 与 Iteration 12 相同并发配置：residual 6 CPU/7 GiB，projection 4 CPU/4 GiB；custom `qwen3-coder-plus`，temperature 0.7，max output tokens 4096。
- 输出：`runs/iter13_residual_role_prompt_20260716/`、`runs/iter13_projection_role_prompt_20260716/`。
- 两项均真实 API + Vitis，评分入口均为 current `scoring/scoring_v3.py::grade()`，run_report `schema_version=5`。

### 真实结果与回退分析

| 指标 | projection Iter12 → Iter13 | residual Iter12 → Iter13 |
|---|---:|---:|
| hidden correctness/cosim | PASS → PASS | PASS/PASS → PASS/PASS |
| current score | 70.96 → 70.96 | 78.00 → 70.85 |
| q_hw | 0.7329 → 0.7329 | 0.8254 → 0.7497 |
| area growth | 1.14x → 1.14x | 0.93x → 1.54x |
| candidate LUT / FF | 692 / 0 → 692 / 0 | 406 / 231 → 586 / 381 |
| credits | 6 → 6 | 42 → 42 |
| Agent 工具时间 | 34.0 → 32.8 s | 105.2 → 104.6 s |
| 端到端时间 | 103.0 → 102.3 s | 197.4 → 196.3 s |
| prompt tokens | 2588 → 1708（-34.0%） | 3353 → 2506（-25.3%） |
| completion tokens | 556 → 558 | 326 → 344 |
| total tokens | 3144 → 2266（-27.9%） | 3679 → 2850（-22.5%） |

- Projection 假设成立：candidate/reference 语义、资源、Q_HW、score/correctness 全保持，total tokens 减少 878；精简 repair prompt 保留。
- Residual correctness仍 PASS，但 score 回退 7.15，不能接受。源码 diff 显示两版都正确 interleave sibling writes；唯一硬件差异是 stream depth `2 → 64`。新 structural prompt 将“interleave OR sufficient depth”并列，模型在已有 interleaving 之外又扩大所有 FIFO，造成 FF 1.54x。
- 因 residual score 明显回退，本轮整体不视为有效改善，不运行 generated tasks，也不保留当前 structural guidance 为最终策略。

### 下一步

- 下一轮只修 structural prompt 的缺失约束，repair specialization 与 optimize prompt保持不变：如果 streams 已有显式正 depth，不得扩大 depth 来掩盖 ordering deadlock；优先且仅修改 sibling write ordering/rate balance，保留现有 FIFO depth。只有 log/结构证明 interleaving 后仍存在不可避免 burst 时才考虑 depth。
- 用 residual official 相同真实 API/Vitis 配置验证；若 Q_HW/score未恢复至 Iteration 12 水平，则恢复完整 unified structural system，而不继续压缩。

## 2026-07-16 — Iteration 14：structural depth-preservation refinement

### Trace、假设与唯一改动组

- Iteration 13 高分/低分 residual 源码 diff 证明唯一硬件差异是 FIFO depth：高分版本 interleave writes 并保留 depth 2；低分版本同样 interleave，但把三个 stream 全改为 depth 64。
- 假设：在 concise structural system 中明确“已有正 depth 时原样保留，禁止用扩大 FIFO 掩盖 sequential ordering”，可恢复低面积架构，同时保留 token 节省。
- `agent/prompts.py` 只修改 structural system：
  - sibling burst 的 primary fix 明确为同 loop interleave。
  - 已有 depth pragma 必须原样保留；只有 ordering/rate 已平衡且结构证明不可避免 bounded burst 时才允许修改 depth。
- 更新 prompt boundary 测试；repair/optimize prompt、user payload、Agent/tool/scorer/harness均不变。

### 测试、配置与真实命令

- 回归：与 Iteration 13 相同定向集合，`58 passed`；`git diff --check` 通过。
- 真实评测：official `residual_stream_deadlock`；custom `qwen3-coder-plus`；temperature 0.7；max output tokens 4096；6 CPU/8 GiB；`--mode structural --max-structural-attempts 3`。
- 输出：`runs/iter14_residual_depth_preservation_20260716/`；本轮单容器运行，避免并发资源噪声。
- 评分入口：current `scoring/scoring_v3.py::grade()`，run_report `schema_version=5`。

### 真实对照结果

| 指标 | Iteration 13 回退 | Iteration 12 高分基线 | Iteration 14 |
|---|---:|---:|---:|
| hidden correctness / cosim | PASS / PASS | PASS / PASS | PASS / PASS |
| current score | 70.85 | 78.00 | 78.01 |
| q_hw | 0.7497 | 0.8254 | 0.8254 |
| area growth | 1.54x | 0.93x | 0.93x |
| candidate latency / top interval | 68 / 64 | 68 / 64 | 68 / 64 |
| candidate LUT / FF | 586 / 381 | 406 / 231 | 406 / 231 |
| stream depth | 64 | 2 | 2 |
| credits | 42 | 42 | 42 |
| Agent 工具时间 | 104.6 s | 105.2 s | 103.0 s |
| API requests | 1 | 1 | 1 |
| prompt tokens | 2506 | 3353 | 2559 |
| completion tokens | 344 | 326 | 308 |
| total tokens | 2850 | 3679 | 2867 |

- 修订后 candidate 真实 cosim PASS，并恢复 latency 68、LUT 406、FF 231、Q_HW 0.8254；相对回退版本 score +7.16。
- 相对 unified/high-score Iteration 12，score +0.01（时间舍入），total tokens `3679 → 2867`，减少 812（-22.1%）；因此保留 refined structural specialization。
- 顶层 `best_latency=68`、cosim/synth gates 与 schema-v5 scorecard一致。
- 本轮是对上一轮回退的恢复与 token efficiency 改善；generated tasks 尚未在本轮运行。

### 当前 official checkpoint 与下一步

- 最新各 relevant path 的真实结果：projection Iteration 13 `70.96`、residual Iteration 14 `78.01`、dot Iteration 11 `73.00`；三项 hidden correctness 全 PASS。
- 任务平均 current score 约 `73.99`，相对 Iteration 5 fresh `72.93` 提升 `1.06`；总 Agent credits `58`（Iteration 5 为 72），total API tokens `7895`（Iteration 5 为 12641）。这些是各 path 最新真实 API/Vitis run_report，不用旧评分字段；后续若需同轮总体结论，将重新 fresh 运行而非回放。
- official correctness 无回退且评分/预算出现有效改善，满足少量 generated 补充验证门。下一轮先只读列出 generated tasks，选择最多两个分别覆盖 role-specific repair/structural 或 optimize frontier，记录选择理由，不运行全集。

## 2026-07-16 — Generated Audit 1：三类 HLS-Eval 泛化质量

### 数据源、选择理由与任务适配

- 仓库中的 `fpt26-agent-v3/tasks -> ../tasks` 目标缺失，Git 历史也没有提交 generated 数据；因此没有把缺目录或伪造 case 计作 Agent 结果。
- 从公开 [HLS-Eval](https://github.com/sharc-lab/hls-eval) 固定提交
  `e628c0ad9b58d3890fbc350e9b37470cc92bf183` 恢复少量 benchmark。该数据源正好对应
  `AGENTS.md` 所列的 94 designs / 8 sources。本轮只适配 3 个强校验 testbench，不运行全集：
  - `machsuite__stencil_stencil2d`：无 pragma 的四层局部 stencil，覆盖通用 nested-loop 优化与资源门。
  - `pp4fpga__parallel_merge_sort`：已有 PIPELINE/DATAFLOW/UNROLL/partition，覆盖成熟架构非回退。
  - `chstone__df_shift64RightJamming`：无 loop 的分支/位运算，覆盖“无 report-supported 空间时停止”。
- 三项原始 testbench 都以非零退出码报告错误；排除了只打印输出或失败仍返回 0 的弱校验 case。
- 只新增 harness-native `task.toml`/description 和原始 kernel/header/testbench/data task 输入，没有修改 Agent、scorer 或只读 harness。
- MachSuite testbench 原本假设从 design root 运行；当前 `CSimTool` 从
  `csim_proj/sol/csim/build` 运行 executable。首次 stencil preflight 因找不到 `.data` 得到
  `SIGABRT`、0 API requests，属于 adapter infrastructure failure，不纳入质量表。仅将该 generated
  task 的两个 immutable data 相对路径改为 `../../../../{input,check}.data` 后 fresh 重跑通过。

### 配置、测试、真实 API/Vitis 与评分命令

- Docker daemon：18 CPU / 15.43 GiB；启动前 MemAvailable 11.31 GiB。按资源限制使用 2+1 调度，每个容器 `--cpus 4 --memory 4g`，没有 3 容器同时争用内存/license。
- Current 回归（Docker 内）：
  `python3 -m pytest -q tests/test_role_system_prompts.py tests/test_reporting_state_consistency.py tests/test_structural_cosim_synth_evidence.py tests/test_optimize_scoring.py tests/test_repair_csim_reuse.py tests/test_workflow_synth_reuse.py tests/test_report_loop_metrics.py tests/test_llm_token_usage.py scoring/test_scoring_v3.py`，`58 passed`。
- 额外全量 `tests/` 探测为 `78 passed, 7 failed`；7 项全来自已废弃
  `tests/test_scoring_v2.py` 的旧公式断言，与 current schema-v5 文档冲突，未用作评分或本轮改动依据。
- 三项均使用真实 custom OpenAI-compatible API：`qwen3-coder-plus`，temperature `0.7`，max output tokens `4096`；`--mode optimize --backend custom --max-optimization-rounds 5`。没有 mock、scripted backend 或历史回放。
- 真实运行命令模板：
  `docker run --rm --cpus 4 --memory 4g -v /home/chen1/projects/fpt26_new:/workspace -v /tools/Xilinx:/tools/Xilinx:ro --env-file /tmp/fpt26.env -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness -w /workspace fpt26-agent-v3:latest bash -lc 'source /tools/Xilinx/Vitis/2025.2/settings64.sh && python3 -m agent.main --task /workspace/tasks/generated/<task> --mode optimize --backend custom --max-optimization-rounds 5 --output-root /workspace/runs/<isolated-root>'`。
- 输出：`runs/generated_audit1_merge_20260716/`、
  `runs/generated_audit1_stencil_r2_20260716/`、
  `runs/generated_audit1_chstone_20260716/`。
- 唯一最终评分入口：`agent/workflow.py::step_score()` → current
  `scoring/scoring_v3.py::grade()`；下表 score 均直接读取 fresh
  `run_report.json.scoring.score`，且 `schema_version=5`。没有使用 HLS-Eval 外部分数、旧公式或手算替代分。

### Fresh generated 结果

| 指标 | MachSuite stencil2d | PP4FPGA merge sort | CHStone shift/jam |
|---|---:|---:|---:|
| hidden correctness / synth | PASS / PASS | PASS / PASS | PASS / PASS |
| current schema-v5 score | 73.07 | 73.06 | 74.00 |
| final latency / top interval | 39069 / 39070 | 75 / 16 | 0 / 1 |
| final clock | 3.170 ns | 10.607 ns | 3.458 ns |
| final LUT / FF / DSP / BRAM | 909 / 649 / 6 / 0 | 3131 / 1056 / 0 / 0 | 606 / 0 / 0 / 0 |
| final latency ratio / area growth / Q_HW | 1.00x / 1.00x / 0.7500 | 1.00x / 1.00x / 0.7500 | 1.00x / 1.00x / 0.7500 |
| credits / budget | 10 / 40 | 10 / 40 | 5 / 40 |
| C-sim / synth calls | 2 / 2 | 6 / 1 | 1 / 1 |
| Agent tool time | 39.7 s | 41.0 s | 17.5 s |
| approximate end-to-end time | 98 s | 112 s | 48 s |
| API requests | 2 | 5 | 1 |
| prompt / completion tokens | 197074 / 456 | 17075 / 2884 | 2603 / 119 |
| total server-reported tokens | 197530 | 19959 | 2722 |

### Transcript 分析、结论与下一步

- 三项最终都保持 valid starter，说明 current Q_HW acceptance gate 在 generated 上没有功能/QoR 回退；但平均 current score 为 `73.38`，所有 final Q_HW 都停在 baseline `0.7500`，本轮没有产生可接受硬件改善。
- Stencil round 1 的真实 candidate 只在 outer `r` loop 加 `PIPELINE II=1`：latency
  `39069 → 12105`（cycles 约 3.23x），但 LUT `909 → 4802`、FF `649 → 1724`、DSP
  `6 → 18`，Q_HW `0.7500 → 0.5259`，被 current scorer 正确拒绝；round 2 返回 unchanged。
- Merge Sort 的 5 个真实 API candidate 都引入 `hls::stream`，却没有包含 `hls_stream.h`；5 次真实 C-sim 均 compile error。最终 correctness/score 保持，但浪费 5 credits、约 20k tokens，说明 compile-failure log 没有进入下一轮 OptimizeAgent feedback，模型重复同一错误架构。
- CHStone 在 baseline latency 0 / top interval 1 时第一次 API 就返回 unchanged，无 candidate tool，证明简单 no-op convergence 正常。
- 当前最大且最可归因瓶颈是 prompt asset leakage：MachSuite 的 `input.data` + `check.data`
  共 95164 bytes，为了让 fixed harness assembly 携带数据而存在于 `task.headers`；
  `build_prompt()` 无差别串入所有 headers，导致两次请求服务端上报 197074 prompt tokens。
- 下一轮只实施一组 prompt-context 改进：向 LLM 仅暴露 C/C++ interface/source header，过滤 `.data` 等非代码附件；Vitis task assembly 和 testbench data 保持不变。用同一 stencil task、模型、参数 fresh 重跑，验证 correctness/Q_HW 不退且 prompt tokens 显著下降。之后再考虑把 normalized C-sim compile failure 反馈回 OptimizeAgent，避免 merge-sort 类重复失败。

## 2026-07-16 — Generated Iteration 2：过滤 prompt 中的非代码附件

### Trace、假设与唯一改动组

- Generated Audit 1 的 MachSuite task 为让 fixed harness 携带 testbench 数据，将
  `input.data` / `check.data` 放在 `Task.headers`；两文件共 95164 bytes。
- `agent/prompts.py::build_prompt()` 旧实现无差别串入 `task.headers`，使每次 LLM request
  都携带大段输入/expected data；两次响应的服务端真实 usage 为 197074 prompt tokens。
- 假设：LLM 只需要 C/C++ interface/source context，不需要 immutable raw test vectors；过滤非代码
  attachments 可显著降 token，同时 Vitis assembly 仍保留数据，correctness/Q_HW 不变。
- 唯一改动组：
  - `agent/prompts.py` 新增 code suffix allowlist，只把 `.c/.cc/.cpp/.cxx/.h/.hh/.hpp/.hxx/.inc/.ipp/.tpp`
    内容放入 prompt；只列出 omitted attachment 文件名，不序列化内容。
  - `tests/test_role_system_prompts.py` 验证 `.h/.inc` 仍可见、`.data` payload 完全不可见，并验证 omitted 名单。
- 不变项：`Task.headers`、`Task.assemble()`、public/hidden testbench、Vitis tool、OptimizeAgent candidate/acceptance、budget、scorer 和只读 harness。

### 测试、真实配置与命令

- Docker current 回归：与 Audit 1 相同定向集合，新增 attachment test 后 `59 passed`；`git diff --check` 通过。
- Fresh 对照任务：`machsuite__stencil_stencil2d`；custom `qwen3-coder-plus`；temperature
  `0.7`；max output tokens `4096`；4 CPU/4 GiB；
  `--mode optimize --backend custom --max-optimization-rounds 5`。
- 输出：`runs/generated_iter2_stencil_asset_filter_20260716/`。
- 真实命令与 Generated Audit 1 模板相同，仅替换 output root；真实 API 与 Vitis HLS 均执行，没有 mock/scripted/history replay。
- 评分入口仍为 `agent/workflow.py::step_score()` → current
  `scoring/scoring_v3.py::grade()`；score 直接读取 fresh schema-v5 `run_report.json`。

### Fresh A/B 结果

| 指标 | Audit 1（附件泄漏） | Iteration 2（过滤后） | 变化 |
|---|---:|---:|---:|
| hidden correctness / synth | PASS / PASS | PASS / PASS | 无回退 |
| current schema-v5 score | 73.07 | 73.07 | +0.00 |
| final latency / top interval | 39069 / 39070 | 39069 / 39070 | 0 |
| final LUT / FF / DSP | 909 / 649 / 6 | 909 / 649 / 6 | 0 |
| final Q_HW / area growth | 0.7500 / 1.00x | 0.7500 / 1.00x | 0 |
| credits / C-sim / synth | 10 / 2 / 2 | 10 / 2 / 2 | 0 |
| Agent tool time | 39.7 s | 34.3 s | -5.4 s |
| approximate end-to-end time | 98 s | 69 s | -29 s |
| API requests | 2 | 2 | 0 |
| prompt tokens | 197074 | 6699 | -190375（-96.6%） |
| completion tokens | 456 | 462 | +6 |
| total tokens | 197530 | 7161 | -190369（-96.4%） |

- 过滤后 candidate 真实 C-sim+synth PASS，但只增加注释，QoR 与 starter 完全相同，因 Q_HW 未严格改善而被拒；第二 API candidate 语义重复，现有 fingerprint 在再次执行工具前收敛。
- 本轮没有声称 score/correctness 提升；直接收益是 token 与端到端效率，且 final hardware/correctness 完全保持。

### 结论与下一步

- 假设成立，保留 attachment filtering。Generated Audit 1 与本轮连续两轮 average score 提升不足 1 且无 correctness 新改善，按目标规则转向 workflow/reflection feedback。
- 当前最大可操作瓶颈是 PP4FPGA Merge Sort：5 个 candidate 均因缺少 `hls_stream.h` 编译失败，而 OptimizeAgent 只记录 `csim FAIL — discard`，没有把 compiler evidence 带入下一 request。
- 下一轮只实现 OptimizeAgent candidate C-sim failure feedback：传递 concise phase/compiler evidence 和明确修复动作；不同时改变 scorer acceptance、prompt asset filter 或 tool budget。用同一 Merge Sort、模型和参数 fresh 验证 compile-failure 次数、correctness、score、tokens 与工具预算。

## 2026-07-16 — Generated Iteration 3：candidate C-sim failure reflection

### Trace、阈值响应与唯一改动组

- Audit 1 的 Merge Sort 连续 5 个 API candidate 都因 `hls::stream` 未声明而 compile error；OptimizeAgent 只写日志后进入下一 round，没有把任何 compiler evidence 发回 LLM，并且 failure branch 的 `continue` 绕过了底部 stagnant convergence。
- Generated Audit 1 + Iteration 2 连续两轮 score 提升不足 1 且无 correctness 新改善，本轮按规则转向 reflection feedback。
- 唯一改动组：
  - `agent/agents/optimize.py` 在 candidate C-sim failure 后用现有 `LogNormalizer` 保留最多 8 条关键行，附带不超过 4000 chars 的 failed-candidate diff、phase 和 required action；失败 fingerprint 进入 rejected 集。
  - `agent/prompts.py` 区分 `REJECTED_BY_CSIM_*` 与 scorer rejection：前者必须先处理真实 compiler/runtime evidence，后者继续遵守 Q_HW directional feedback。
  - `tests/test_optimize_scoring.py` 覆盖路径清洗/有界 diff，以及第二 round 读取 compiler evidence、修正 missing HLS include、再通过 C-sim+synth 的完整 loop。
- 不变项：最大 rounds、API/model 参数、Vitis tools/budget、current Q_HW 接受门、attachment filter、final scorer 和 harness。

### 测试与真实验证设计

- Docker current 回归：同一套定向命令，`61 passed`；`git diff --check` 通过。
- 任务/配置：`pp4fpga__parallel_merge_sort`；custom `qwen3-coder-plus`；temperature
  `0.7`；max output tokens `4096`；`--mode optimize --max-optimization-rounds 5`；每容器 4 CPU/4 GiB。
- 首个 post-change fresh run 输出：`runs/generated_iter3_merge_csim_reflection_20260716/`。
  本次随机样本的两个 candidate 都直接通过 C-sim，因此没有命中 failure feedback；final correctness/Q_HW 保持，但 3 次 synth 使 credits 15、score 72.13。该 run 只作非回退/随机性 guard，不能用于声称 reflection 有效。
- 为得到可归因证据，随后同时启动 paired guard：
  - baseline：只读挂载 `git archive HEAD` 的提交态旧流程，输出
    `runs/generated_iter3_pair_baseline_20260716/`。
  - reflection：当前改动，输出 `runs/generated_iter3_pair_reflection_20260716/`。
  - 两边同一时刻、同任务/model/temperature/max tokens/CPU/memory；均真实 API + Vitis，没有 mock、scripted 或 replay。
- 最终 score 均由各自 fresh `agent/workflow.py::step_score()` 调用 current
  `scoring/scoring_v3.py::grade()`，run_report `schema_version=5`。

### Paired fresh 结果

| 指标 | 提交态 baseline | C-sim reflection | 变化 |
|---|---:|---:|---:|
| hidden correctness / synth | PASS / PASS | PASS / PASS | 无回退 |
| current schema-v5 score | 73.06 | 72.88 | -0.18 |
| final latency / top interval | 75 / 16 | 75 / 16 | 0 |
| final LUT / FF / Q_HW | 3131 / 1056 / 0.7500 | 3131 / 1056 / 0.7500 | 0 |
| credits / budget | 10 / 40 | 11 / 40 | +1 |
| candidate compile errors | 5 | 1 | -4 |
| C-sim / synth calls | 6 / 1 | 3 / 2 | -3 / +1 |
| Agent tool time | 41.0 s | 40.6 s | -0.4 s |
| approximate end-to-end time | 113 s | 82 s | -31 s |
| API requests | 5 | 2 | -3 |
| prompt / completion tokens | 17075 / 3129 | 7442 / 947 | -9633 / -2182 |
| total tokens | 20204 | 8389 | -11815（-58.5%） |

- Paired baseline 重现 5 次相同类型 stream compile error。Reflection round 1 同样失败；round 2 收到真实 evidence 后放弃 stream architecture，返回 current best 加一行文件名注释，真实 C-sim+synth 都 PASS 且 QoR 与 baseline 完全相同，随后按 2 stagnant rounds 收敛。
- 因此 reflection 确实减少盲试、API/token 和端到端时间，但当前 score/credit 尚未过门：round 2 实际是 semantic no-op，原文比较因注释差异未识别；`_candidate_fingerprint()` 虽忽略注释，却只检查 rejected fingerprints，没有与 current best 比较，浪费 1 C-sim + 1 synth（5 credits），造成 paired score -0.18。

### 结论与下一步

- 本轮 correctness/Q_HW 无回退且 failure recovery/token stability 显著改善，但 current score 轻微回退，不能作为完整 score 改善结束。
- 下一轮只补 current-best semantic no-op convergence：LLM response fingerprint 与 current best 相同（仅注释/空白差异）时，在任何 candidate tool 前停止；不改变 failure feedback/scorer。先用单元测试覆盖，再用相同 Merge Sort fresh 运行验证省掉 5 credits 后 score、tokens 和 correctness。

## 2026-07-16 — Generated Iteration 4：current-best semantic no-op convergence

### Trace、假设与唯一改动组

- Iteration 3 paired reflection 的 round 2 实际只在 current best 前增加文件名注释；原文比较失败后仍执行 1 次 C-sim + 1 次 synth，浪费 5 credits 并使 score 回退 0.18。
- 现有 `_candidate_fingerprint()` 已忽略注释/空白，但只用于“是否重复已拒 candidate”，没有与动态 current best 比较。
- 假设：response fingerprint 等于 current best 时在任何 candidate tool 前收敛，可保持最终硬件/正确性并提高 current score、token 和时间效率。
- 唯一改动：`agent/agents/optimize.py` 增加 current-best fingerprint equality guard 和
  `semantic_current_best_skips` metadata；`tests/test_optimize_scoring.py` 验证 comment-only full source 不调用 C-sim/synth。
- 不变项：C-sim reflection、scorer rejection feedback、Q_HW 接受门、API prompt、最大 rounds、Vitis/budget/scoring/harness。

### 测试与真实验证

- Docker current 回归：同一套定向命令，`62 passed`；`git diff --check` 通过。
- 先冻结 Iteration 3 reflection 版本到只读 `/tmp/fpt26-iter4-baseline`，并与 guard 并行 fresh 运行 Merge Sort。两边均真实 API/Vitis、相同 `qwen3-coder-plus` / temperature 0.7 / max tokens 4096 / 4 CPU / 4 GiB。
- Merge paired 输出：`runs/generated_iter4_pair_baseline_20260716/` 与
  `runs/generated_iter4_pair_noop_guard_20260716/`。该采样中两边 response 不同且 guard 未命中；guard 侧 score 72.12、baseline 71.94，但差异不可归因，只作为 correctness/Q_HW 非回退 guard。
- 为命中目标路径，使用 Iteration 2 已真实出现 comment-only response 的
  `machsuite__stencil_stencil2d` 做一次 fresh（没有 replay）：
  `runs/generated_iter4_stencil_noop_guard_20260716/`。同模型/参数/容器限制，真实 API + Vitis。
- 最终 score 仍由 fresh `agent/workflow.py::step_score()` → current
  `scoring/scoring_v3.py::grade()` 产生，schema-v5 run_report 为唯一分数。

### Stencil 命中结果

| 指标 | Iteration 2（无 guard） | Iteration 4（guard 命中） | 变化 |
|---|---:|---:|---:|
| hidden correctness / synth | PASS / PASS | PASS / PASS | 无回退 |
| current schema-v5 score | 73.07 | 74.00 | +0.93 |
| final latency / top interval | 39069 / 39070 | 39069 / 39070 | 0 |
| final LUT / FF / DSP / Q_HW | 909 / 649 / 6 / 0.7500 | 909 / 649 / 6 / 0.7500 | 0 |
| credits / budget | 10 / 40 | 5 / 40 | -5 |
| C-sim / synth calls | 2 / 2 | 1 / 1 | -1 / -1 |
| Agent tool time | 34.3 s | 18.6 s | -15.7 s |
| approximate end-to-end time | 69 s | 50 s | -19 s |
| API requests | 2 | 1 | -1 |
| prompt / completion tokens | 6699 / 462 | 3208 / 231 | -3491 / -231 |
| total tokens | 7161 | 3439 | -3722（-52.0%） |

- Fresh 日志明确出现 `semantic no-op versus current best — skip csim/synth and converge`；只有 baseline C-sim+synth 两个真实 agent tools。最终 source/hardware 与 starter 相同。
- Merge paired 虽未命中 guard，current side 仍 hidden correctness PASS，并正确拒绝 synth failure 和一个 latency 75→56 但 LUT 3131→4561、FF 1056→5050、Q_HW 0.5127 的低质 candidate；没有 QoR 回退。

### 结论与下一步

- 假设成立，保留 semantic current-best guard。它与 failure reflection 合并后覆盖“失败→反馈→comment-only best”的安全收敛链路。
- Iteration 3 paired score -0.18、Iteration 4 target +0.93，连续两轮平均提升仍不足 1 且无 correctness 新改善；按规则继续转向专用证据/tool，而不是继续扩写通用 prompt。
- 两个 generated compute task 的 fresh synthesis 均显示 `Loops=[none]`：Stencil 源码有四层 loop，Merge Sort 也有多级 loops/dataflow，但 OptimizeAgent 看不到 loop latency/PipelineII，只能猜 outer PIPELINE 或 stream architecture。
- 下一轮先完整 trace Vitis 2025.2 的 generated `csynth.xml/csynth.rpt` 与
  `llm4hls/report.py::parse_csynth_xml()`，只在真实报告确有结构化 loop evidence 时做最小 parser 扩展；若报告本身没有，则不伪造指标，转向显式 report extraction tool。

## 2026-07-16 — Generated Iteration 5：Vitis 2025.2 nested loop evidence

### Trace、假设与唯一改动组

- 完整检查 Iteration 4 Stencil 与 Iteration 3 Merge Sort 的真实
  `agent/synth_*/synth_proj/sol/syn/report/csynth.xml`、console transcript 和
  `run_report.json`。根因不是 Vitis 缺少 loop 数据，而是当前
  `llm4hls/report.py::parse_csynth_xml()` 只读取顶层
  `PerformanceEstimates/SummaryOfLoopLatency`；Vitis 2025.2 将这两项 generated
  task 的 loop summary 放在
  `ModuleInformation/Module/PerformanceEstimates/SummaryOfLoopLatency`。
- 原始 Stencil XML 给出 loop `stencil_label1_stencil_label2`：trip count 7812、
  latency 39061、PipelineII 5、depth 7；Merge Sort 给出 `merge_arrays`：trip
  count 16、latency 16、PipelineII 1、depth 2。旧 parser 均错误显示 `Loops=[none]`。
- 假设：把真实 nested loop metrics 送入现有诊断/提示回环，可用综合器证据替代
  猜测，同时保持旧 Vitis 顶层格式兼容且不因 replicated modules 重复膨胀 prompt。
- 唯一改动组：`llm4hls/report.py` 同时收集顶层与 module-nested loop summary，
  优先使用 XML `<Name>`，按 name/trip/latency/II/depth 完整指纹去重；
  `tests/test_report_loop_metrics.py` 增加 Vitis 2025.2 nested + replicated-module
  fixture。没有改变优化 prompt、接受门、rounds、budget、scoring 或 harness。

### 测试、真实配置与命令

- Docker 定向回归：
  `python3 -m pytest -q tests/test_role_system_prompts.py tests/test_reporting_state_consistency.py tests/test_structural_cosim_synth_evidence.py tests/test_optimize_scoring.py tests/test_repair_csim_reuse.py tests/test_workflow_synth_reuse.py tests/test_report_loop_metrics.py tests/test_llm_token_usage.py scoring/test_scoring_v3.py`，结果 `63 passed`。
- 用当前 parser 在 Docker 内重新读取两份历史**原始 XML 文件**仅用于 parser
  诊断，不作评测/跑分：Stencil 正确显示
  `stencil_label1_stencil_label2(trip=7812,lat=39061,II=5)`；Merge 正确显示
  `merge_arrays(trip=16,lat=16,II=1)`，replicated modules 未重复输出。
- Fresh 评测命令：
  `docker run --rm --cpus 4 --memory 4g -v /home/chen1/projects/fpt26_new:/workspace -v /tools/Xilinx:/tools/Xilinx:ro --env-file /tmp/fpt26.env -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness -w /workspace fpt26-agent-v3:latest bash -lc 'source /tools/Xilinx/Vitis/2025.2/settings64.sh && python3 -m agent.main --task /workspace/tasks/generated/machsuite__stencil_stencil2d --mode optimize --backend custom --max-optimization-rounds 5 --output-root /workspace/runs/generated_iter5_stencil_nested_loop_evidence_20260716'`。
- 真实 API：custom OpenAI-compatible，`qwen3-coder-plus`，temperature 0.7，
  max output tokens 4096；API key 由 env-file 注入且未记录。任务仍为 U55C、5 ns、
  optimize budget 40；与前轮 Stencil 配置一致。
- 评分命令/路径：同一 fresh `agent.main` workflow 的 `step_score()` 调用当前
  `scoring/scoring_v3.py::grade()`；输出
  `runs/generated_iter5_stencil_nested_loop_evidence_20260716/machsuite__stencil_stencil2d/run_report.json`
  的 `scoring.schema_version=5` 与 `scoring.score` 是唯一最终 score，未手算或引用旧字段。

### Fresh Stencil 结果

| 指标 | Iteration 4 | Iteration 5 | 变化 |
|---|---:|---:|---:|
| hidden correctness / synth | PASS / PASS | PASS / PASS | 无回退 |
| current schema-v5 score | 74.00 | 74.00 | 0.00 |
| final latency / top interval | 39069 / 39070 | 39069 / 39070 | 0 |
| loop trip / latency / II | none | 7812 / 39061 / 5 | 真实证据可见 |
| final LUT / FF / DSP / Q_HW | 909 / 649 / 6 / 0.7500 | 909 / 649 / 6 / 0.7500 | 0 |
| credits / budget | 5 / 40 | 5 / 40 | 0 |
| C-sim / synth calls | 1 / 1 | 1 / 1 | 0 |
| Agent tool wall time | 18.6 s | 17.8 s | -0.8 s（噪声范围） |
| scoring wall time | 未单列 | 29.06 s | — |
| API requests | 1 | 1 | 0 |
| prompt / completion tokens | 3208 / 231 | 3225 / 231 | +17 / 0 |
| total tokens | 3439 | 3456 | +17 |

- Fresh transcript 的 baseline synth 行与 round-1 report 均明确含 nested loop；诊断变为
  `Measured loop PipelineII=5>1 — classify ... recurrence, timing, or memory ports`
  和基于 dominant loop evidence 的高延迟建议。模型返回 semantic current-best，guard
  在任何 candidate C-sim/synth 前安全收敛；最终 source/hardware 与 starter 相同。

### 结论与下一步

- Parser 假设成立，保留改动：它修复了专用证据通道，旧格式单测与全部定向回归通过，
  fresh correctness/Q_HW/预算无回退。但本次模型未利用证据生成新 candidate，score
  提升为 0，因此不能声称 QoR 改善。
- 当前最大瓶颈已从“看不到 loop”收敛为“只有 loop II 数字，没有 II=5 的具体限制原因；
  通用模型在不确定时返回 unchanged”。下一轮只扩展一组可验证的 loop bottleneck
  evidence：先 trace Vitis schedule/bind 报告与 XML 是否已有 dependence/memory-port
  reason；仅在报告含结构化、稳定字段时解析并反馈。若没有，则不猜测，转向最小的
  HLS log diagnostic extraction tool。

## 2026-07-16 — Generated Iteration 6：HLS 200-448 II resource diagnostic

### Trace、假设与唯一改动组

- Trace Iteration 5 的真实 `sol.log`、`hls_run_tcl.log`、主/子模块
  `csynth.rpt`、schedule/bind/ADB XML。主 `csynth.rpt` 将
  `stencil_label1_stencil_label2` 标成 `Issue=II / Violation=Resource Limitation`；
  synth log 的稳定消息 `HLS 200-448` 进一步给出：9 个 32-bit `orig` loads（源码
  `stencil_stencil2d.cpp:20`）访问 `RAM:orig`，II resource lower bound=5。
- 同一 `csynth.xml` 的 `SummaryOfLoopViolations` 却错误填 `IssueType=-`、
  `ViolationType=-`；因此不解析该不一致 XML 字段，也不靠易变的人类表格列。
- 假设：将稳定 message ID 的精简结构化证据加入现有 bottleneck feedback，会让模型
  从 unchanged/猜测 PIPELINE 转向针对真实 memory-port 限制的候选。
- 唯一改动组：新增 `agent/analysis/synth_diagnostics.py`，只识别
  `HLS 200-448`，抽取 II lower bound、operation、首个 array/source/core，去重并有界
  格式化；`OptimizeAgent::_diagnose()` 在 loop II>1 时优先使用该证据，无匹配消息时
  保持旧诊断。没有改 scorer、接受门、budget、rounds、task/harness。
- `tests/test_optimize_scoring.py` 覆盖真实消息形状、去重、字段抽取和诊断输出。

### 测试、配置、运行与评分

- Docker 定向回归与 Iteration 5 同命令，结果 `64 passed`；`git diff --check` 通过。
- 在 Docker 中读取 Iteration 5 的真实 log，专用诊断器输出：
  `array='orig'`、source `stencil_stencil2d.cpp:20`、core `RAM:orig`、
  `II lower bound=5`；完整重复 load 列表未进入 prompt。
- Fresh 运行：与 Iteration 5 相同 Docker mount、4 CPU、4 GiB、Vitis 2025.2、U55C、
  5 ns、budget 40、generated Stencil；输出
  `runs/generated_iter6_stencil_ii_diagnostic_20260716/`。
- 真实 API：custom OpenAI-compatible `qwen3-coder-plus`，temperature 0.7，
  max output tokens 4096；无 mock/replay，secret 仍只由 `/tmp/fpt26.env` 注入。
- 运行命令仅将 Iteration 5 output root 改为
  `/workspace/runs/generated_iter6_stencil_ii_diagnostic_20260716`；其余与上一节记录的
  fresh Docker 命令完全一致。
- 评分仍由同一 fresh workflow 的 `agent/workflow.py::step_score()` 调用当前
  `scoring/scoring_v3.py::grade()`；`run_report.json` 的
  `scoring.schema_version=5`、`scoring.score=73.06` 是唯一最终 score。

### 结果与完整候选归因

| 指标 | Iteration 5 | Iteration 6 | 变化 |
|---|---:|---:|---:|
| hidden correctness / final synth | PASS / PASS | PASS / PASS | 无回退 |
| current schema-v5 score | 74.00 | 73.06 | -0.94 |
| final latency / top interval / Q_HW | 39069 / 39070 / 0.7500 | 39069 / 39070 / 0.7500 | 最终硬件不变 |
| credits / budget | 5 / 40 | 10 / 40 | +5 |
| Agent C-sim / synth | 1 / 1 | 2 / 2 | +1 / +1 |
| Agent tool wall time | 17.8 s | 34.4 s | +16.6 s |
| scoring wall time | 29.06 s | 29.67 s | +0.61 s |
| API requests | 1 | 2 | +1 |
| prompt / completion / total tokens | 3225 / 231 / 3456 | 6969 / 485 / 7454 | +3744 / +254 / +3998 |

- Round 1 首次明确记录完整 `HLS 200-448` evidence，模型不再 unchanged，并生成仅含
  comment + `#pragma HLS UNROLL factor=2`（inner `k2`）的候选；真实 C-sim PASS。
- 候选真实 synth：latency `39069→86185`、top interval `39070→86186`、
  LUT `909→664`、FF `649→306`、DSP `6→6`、candidate Q_HW `0.7500→0.6284`；
  current scoring-v3 接受门正确拒绝。它没有处理 `orig` banking，反而增加并发 load，
  破坏原先 flatten/outer pipeline：新主报告显示外层 latency 86184，inner
  `stencil_label3` 又同时受 `filter` 与 `orig` resource lower bound=3。
- Round 2 使用 scorer rejection feedback 后返回 semantic current best，guard 跳过额外
  tools 并收敛。最终 source/hardware 是 starter，所以 correctness/Q_HW 无回退；score
  回退完全来自多一次错误方向候选的 5 credits/时间成本。

### 结论与下一步

- 专用诊断假设只部分成立：它成功把模型从 no-op 推到可编译、功能正确且与 loop 相关的
  候选，说明 evidence 已进入决策；但模型忽略“array/port”约束选择 standalone UNROLL，
  最终 score -0.94。保留 extractor，因为证据真实、稳定、兼容 fallback，但不能把本轮
  记为质量改善。
- 当前最大瓶颈是候选生成前缺少“动作是否响应已测瓶颈”的 workflow gate。下一轮只加
  一个 pre-tool intent check：当 `HLS 200-448` 已证明 memory-port 限制、candidate 与
  current best 的非 pragma 代码完全相同、且只新增 standalone PIPELINE/UNROLL 而未对
  报告数组做 banking/reshape 时，禁止浪费 C-sim/synth，注入结构化 reflection 后再给
  模型一次修正机会；真实代码级 line buffer/cache 方案不拦截。

## 2026-07-16 — Generated Iteration 7：pre-tool II intent gate

### Trace、假设与唯一改动组

- Iteration 6 的唯一被测 candidate 仅增加 `UNROLL factor=2`，没有改变
  `HLS 200-448` 指出的 `orig` storage bandwidth，真实 latency 反而 2.21× 变差；这类
  pragma-only intent 在工具前即可由已有证据判定为不响应瓶颈。
- 假设：在 candidate C-sim 前增加一个严格、窄范围 intent gate，并把拒绝原因送入
  reflection，可避免明显相反的工具成本，同时不拦截正确 banking 或 line-buffer 代码。
- 唯一改动组：
  1. `_ii_resource_intent_feedback()` 仅在非 pragma 源码 fingerprint 完全相同、所有新增
     pragma 均为 standalone PIPELINE/UNROLL、且已有 `HLS 200-448` 时返回结构化拒绝；
  2. Optimize workflow 在 C-sim/synth 前跳过该 candidate、记录 fingerprint/metadata，
     下一轮通过 `REJECTED_BY_SYNTH_EVIDENCE_INTENT` reflection 明确说明“未测量”；
  3. prompt 增加对应 feedback 语义，禁止把 pre-tool rejection 伪称 scorer 测量。
- 明确放行：新增 ARRAY_PARTITION/ARRAY_RESHAPE，或任何真实非 pragma locality/code
  变化。scoring、tool 计费、接受门、rounds、task/harness 均未修改。

### 测试、真实配置与评分版本

- Docker 定向回归：`66 passed`；新增单测覆盖 standalone UNROLL 被拦截、matched
  partition 和代码 locality 放行，以及“拒绝→reflection→semantic current best”全链路
  0 candidate tools；`git diff --check` 通过。
- Fresh 真实配置/命令与 Iteration 6 相同，仅 output root 改为
  `runs/generated_iter7_stencil_ii_intent_gate_20260716/`。真实
  `qwen3-coder-plus`、temperature 0.7、max output 4096、Vitis 2025.2、U55C 5 ns、
  4 CPU/4 GiB、budget 40；无 mock/replay。
- 最终评分代码版本：`scoring/__init__.py __version__=5.0.0`，schema 5，评分文件
  `scoring/scoring_v3.py`。执行路径仍是 fresh `python3 -m agent.main ...` →
  `agent/workflow.py::step_score()` → `scoring.scoring_v3.grade()`；唯一最终 score 来自
  `runs/generated_iter7_stencil_ii_intent_gate_20260716/machsuite__stencil_stencil2d/run_report.json`。

### Fresh 结果

| 指标 | Iteration 6 | Iteration 7 | 变化 |
|---|---:|---:|---:|
| hidden correctness / final synth | PASS / PASS | PASS / PASS | 无回退 |
| current V5 score | 73.06 | 73.07 | +0.01（无有效提升） |
| final latency / interval / Q_HW | 39069 / 39070 / 0.7500 | 39069 / 39070 / 0.7500 | final 不变 |
| credits / budget | 10 / 40 | 10 / 40 | 0 |
| Agent C-sim / synth | 2 / 2 | 2 / 2 | 0 |
| Agent wall / grading wall | 34.4 / 29.67 s | 34.7 / 28.67 s | 噪声范围 |
| 顺序阶段和（近似 E2E） | 64.1 s | 63.4 s | -0.7 s；未独立 instrument |
| API requests | 2 | 2 | 0 |
| prompt / completion / total tokens | 6969 / 485 / 7454 | 7136 / 510 / 7646 | +167 / +25 / +192 |
| cached / reasoning tokens | unavailable | unavailable | provider 未上报，未估算 |

- 本次随机采样没有命中 gate：round 1 同时新增
  `ARRAY_PARTITION variable=filter complete dim=1` 与 outer-context `UNROLL factor=2`，因此
  按规则放行。真实 C-sim PASS，真实 synth latency `39069→23439`（1.667× cycles
  speedup）、interval `39070→23436`、clock 3.17 ns 不变；LUT `909→1241`
  （1.365×）、FF `649→873`（1.345×）、DSP `6→9`（1.5×）。
- Candidate 主报告仍显示 `orig` memory resource lower bound，II `5→6`；filter complete
  partition 消除了 filter interface，但没有处理证据指定的 `orig`。当前 optimization-time
  V5 Q_HW 为 `0.7416`，低于 baseline `0.7500`，所以接受门拒绝；round 2 semantic no-op
  后收敛。最终 correctness/Q_HW 无回退，额外 5 credits 使 final V5 score 仅 73.07。
- 因采样未走到 intent rejection 分支，本次真实跑分只能证明 gate 对“非 standalone”
  candidate 无误拦截，不能宣称它节省了真实工具；保留单测，但下一次命中前不计收益。

### 结论与下一步：独立评分一致性审计

- 连续 Iteration 6/7 平均 score 改善远低于 1 且 correctness 无新增，继续扩 prompt 的
  边际价值低。Iteration 7 产生了一个新的真实 Pareto trade-off 证据：有效时间 1.667×
  改善、worst relative resource 1.5×，绝对占用仍远低于 U55C capacity，却被 V5
  Q_HW 排在 unchanged baseline 之后（0.7416 < 0.7500）。
- 这可能是 current formula 对 ratio utility 分别非线性压缩后再做几何平均造成的
  trade-off 边界偏置，也可能是有意的资源优先策略；证据尚不足以直接改公式。
- 下一轮严格作为**评分公式独立审计**：不再修改 Agent/gate。先记录失败案例与期望排序，
  用同一批真实 official/generated synth 产物计算 V5 分量，检查 reciprocal symmetry、
  Pareto/边界/异常值，并提出候选公式；只有多案例和边界测试证明与任务目标更一致时才
  修改 scoring。若修改，建立新 schema/version 分界，双重评分且不计为 Agent 提升。

## 2026-07-16 — Scoring Audit 1（修改前证据与预期行为）

### 审计边界

- 本轮是独立评分审计，不修改 Agent prompt、workflow、tool、task 或 harness；评分变化
  本身不计作 Agent 性能提升。
- 当前权威版本：`scoring/__init__.py __version__=5.0.0`、schema 5，文件
  `scoring/scoring_v3.py`。V5 核心为
  `q_hw = sqrt(ratio_quality(speedup) * ratio_quality(1/worst_growth))`，其中
  `ratio_quality(r)=1-1/(1+r)^2`。
- 审计只读复用已经由真实 API + Vitis 生成的原始 `csynth.xml`。这是新 goal 明确要求的
  same-artifact 双重评分，不是新的 Agent evaluation，不回放结果冒充 fresh run。

### 失败案例、公式问题与期望行为

- 真实 Iteration 7 Stencil candidate：speedup 1.666837×、worst growth 1.5×（DSP
  6→9），`speedup/growth=1.111225`，V5 Q_HW 0.741628，低于 unchanged baseline
  0.750000。绝对最大器件利用率只有 0.099734%。
- Reciprocal symmetry 审计发现，V5 对等比例交换并不中性：speedup 与 growth 同为
  1.25/1.5/2/4/10× 时，Q_HW 分别是
  0.744845/0.733212/0.702728/0.587878/0.414873，而不是 baseline 0.75。
- 更严重的是隐含硬上限：worst growth=2× 时，即使 speedup→∞，
  `sqrt(1 * ratio_quality(0.5))=0.74536 < 0.75`；任何翻倍某一资源的 candidate 都
  永远不可能胜过 starter。growth 1.5× 则至少需要 1.873685× speedup，而不是等权
  ratio 目标下自然的 1.5×。这与 V5 文档宣称的有限 ratio 无 hard cap 不一致，并形成
  容易驱动 Agent 投机/过度保守的边界。
- 预期评价行为：正确性仍为硬门；固定资源时更快严格更高，固定性能时更小严格更高；
  equal-log-weight 的 speedup==worst_growth 应与 baseline 中性；speedup/growth>1 应
  高于 baseline，<1 应低于；明显资源爆炸与性能回退仍必须低分；任何有限 growth 都不
  应制造“无穷性能也无法改善”的隐式 ceiling。

### 只读真实产物审计命令与结果

- 命令：
  `docker run --rm --cpus 1 --memory 1g -v /home/chen1/projects/fpt26_new:/workspace:ro -v /tmp:/host-tmp:ro -e PYTHONPATH=/workspace/fpt26-agent-v3 -w /workspace/fpt26-agent-v3 fpt26-agent-v3:latest python3 /host-tmp/scoring_tradeoff_audit.py`。
- 候选式仅用于审计，尚未写入 scorer：
  `hardware_ratio = sqrt(performance_ratio * (1/worst_growth))`，
  `q_hw = ratio_quality(hardware_ratio)`；这等价于在 log-ratio 域对性能与最差资源做
  等权几何折中，然后只映射一次。

| 真实 candidate | speedup | worst growth | speed/growth | V5 Q_HW | 候选 Q_HW | 期望排序 |
|---|---:|---:|---:|---:|---:|---|
| Generated Stencil near-Pareto | 1.6668 | 1.5000 | 1.1112 | 0.7416 | 0.7630 | 高于 baseline |
| Generated Stencil slow/smaller | 0.4533 | 1.0000 | 0.4533 | 0.6284 | 0.6428 | 低于 baseline |
| Generated Stencil outer bloat | 3.2275 | 5.2827 | 0.6110 | 0.5259 | 0.6850 | 低于 baseline |
| Official Dot factor=2 | 1.9942 | 2.0000 | 0.9971 | 0.7026 | 0.7496 | 略低于 baseline |
| Official Dot factor=4 | 1.9942 | 2.8590 | 0.6975 | 0.6331 | 0.7031 | 低于 factor=2/baseline |
| Generated Merge FF bloat | 1.4386 | 4.7822 | 0.3008 | 0.5127 | 0.5829 | 低于 baseline |

- 候选式保持这 6 个真实样例的功能无关 Pareto/方向排序，并只翻转问题样例：Stencil
  near-Pareto 从低于 baseline 变为高于；Dot factor=2 因 speedup 略小于 2× growth，
  仍略低；其它回退/膨胀点仍低。
- 证据充分，下一步把候选式作为新的权威 schema 6 独立实现，增加 reciprocal、ceiling、
  真实样例、极端值、有效性硬门测试，并更新版本/文档/report 字段。此前实验性 token
  V6 run 与本次无关；新 V6 明确命名为 log-symmetric hardware-ratio formula，token
  仍只观测不计分。
