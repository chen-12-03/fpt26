# FPT26 LLM4HLS 评分标准 V2 设计提案

状态：设计评审稿  
日期：2026-07-15  
依据：`docs/scoring-redesign-brief.md`

## 0. 结论摘要

建议将单任务主分数统一为 `0..100`，不再乘 `difficulty`。功能正确性是不可配置的硬门：hidden TB 失败，或要求 RTL 验证的任务 hidden cosim 失败，最终分数恒为 `0`。hidden TB 通过但综合失败时走降级分支，默认最高 `20` 分。

功能和综合均通过后，使用五维加权分数：

```text
Score = 100 * (
    0.30 * completion
  + 0.30 * latency_quality
  + 0.28 * area_quality
  + 0.08 * throughput_quality
  + 0.04 * budget_quality
)
```

其中 `completion=1`。latency、area 和 II 都基于候选相对基准的比率；加速收益使用严格单调、无硬封顶的 `atan(log(ratio))` 映射；面积使用平滑的相对增长函数并叠加器件余量惩罚；预算按剩余比例的幂函数计分。所有可调常量均由环境变量覆盖，功能失败归零这一安全规则不可覆盖。

默认参数下，Brief 中三次真实运行的重算结果为：

| 任务 | 旧分数百分比 | V2 分数 | 主要变化 |
|---|---:|---:|---|
| `projection_bugfix` | 70.0 | **91.46** | repair 的延迟/II 保持被视为完成目标，且预算有效率 |
| `dotProduct_optimize` | 100.0 | **71.62** | 27.03x 加速仍获高延迟分，但 84.5x LUT、582.7x FF 膨胀显著扣分 |
| `residual_stream_deadlock` | 77.5 | **73.88** | 使用 cosim 的 97 cycles，面积改善获奖，66/80 预算受罚 |

`residual_stream_deadlock` 的 transcript 没有给出候选 II，因此上表仅在数学验证中假设 `throughput_quality=0.5`。生产实现必须从候选 `SynthReport` 读取真实 II；XML 本身缺失时使用可配置的保守缺失值。

---

## 1. Web 研究结论

检索日期为 2026-07-15。以下四组检索按 Brief §5 的查询意图执行。

### 1.1 Search 1: HLS PPA / QoR 指标

检索式：`high-level synthesis PPA quality metric area-delay product FPGA design space exploration scoring`

主要来源与提取结果：

1. [AMD Vitis HLS Synthesis Summary, UG1702](https://docs.amd.com/r/en-US/Vitis-Reference-Guide-UG1702/Synthesis-Summary) 将 latency、initiation interval、timing slack、BRAM/DSP/FF/LUT 资源估计并列为综合结果核心字段。由此可见，只用 latency 不能代表 HLS QoR，II 和资源必须独立进入评分。
2. [AMD Vitis HLS Process Overview, UG1399](https://docs.amd.com/r/2021.2-English/ug1399-vitis-hls/Vitis-HLS-Process-Overview?contentId=90fNT5GfJL_MFNiMc01UDg) 明确要求结合 latency、II、throughput 和 resource utilization 分析方案，并指出展开会以更多 PL 资源换取并行度。
3. [Chimera: Multi-Objective DSE for FPGA HLS](https://arxiv.org/abs/2207.07917) 将 HLS pragma 搜索建模为多目标问题并考察 Pareto frontier，而不是只优化单一延迟值。
4. [Exploiting area/delay tradeoffs in high-level synthesis](https://doi.org/10.1109/DATE.2012.6176646) 和后续 HLS 文献使用 area-delay trade-off/ADP 评价硬件效率。

设计结论：ADP 是有用的诊断指标，但不应直接成为唯一分数。FPGA 的 LUT、FF、DSP、BRAM、URAM 不可用一个固定“面积单位”无损折算，而且 II 与单次 latency 是不同性能维度。本提案保留可解释的分维度分数，并用几何资源比率表达面积变化。

当前 `SynthReport` 没有功耗字段，因此本提案严谨地称其为 QoR 评分，不声称测得了完整的 Power-Performance-Area。未来得到实现后功耗时，可增加 power 维度或报告 energy-delay product。

### 1.2 Search 2: FPGA 厂商/竞赛评分规则

检索式：`Xilinx Vitis HLS design contest scoring rubric acceleration area tradeoff benchmark`

主要来源与提取结果：

1. [AMD/Xilinx FPL 2026 Agentic FPGA Backend Optimization Competition](https://xilinx.github.io/fpl26_optimization_contest/score.html) 规定：设计未完成 place-and-route 或仿真发现逻辑行为不一致时，单 benchmark 得分为 `0`；有效设计的收益还要扣除 OpenRouter 成本和 wall-clock runtime。
2. 同一规则按每个 hidden benchmark 评分，再按 benchmark 排名聚合；并要求 scorecard 暴露所有参与计算的字段。
3. [ISPD 2017 Clock-Aware FPGA Placement Contest](https://www.ispd.cc/contests/17/evaluation.html) 使用质量指标乘 runtime factor，并把非法或不可路由结果置于最低排名，体现了“有效性门槛 + 质量 + 运行成本”的结构。

设计结论：功能/实现有效性应先做门控，不能靠其他维度抵消；agent 成本应该进入成绩；每个中间项和数据来源必须写入报告，便于复核。

### 1.3 Search 3: LLM4HLS / RTL benchmark

检索式：`LLM4HLS benchmark evaluation metric VerilogEval RTLLM agent scoring 2024 2025`

主要来源与提取结果：

1. [HLS-Eval](https://arxiv.org/abs/2504.12268) 报告 parseability、compilability、runnability、synthesizability 四个递进指标和 pass@k，强调 HLS 生成需要分阶段验证。
2. [RTLLM](https://arxiv.org/abs/2308.05345) 明确采用 syntax、functionality、design quality 三层递进目标。功能正确不是 PPA 的可替代项，而是进入设计质量比较的前提。
3. [VerilogEval](https://arxiv.org/abs/2309.07544) 用自动 testbench 与 golden simulation 输出比较功能正确性；其[官方评估仓库](https://github.com/NVlabs/verilog-eval)报告 pass@1 等统计，而非用代码表面相似度代替功能测试。
4. [HLStrans](https://arxiv.org/abs/2507.04315) 为样本提供 testbench 以及 synthesis-based latency/resource annotations，说明 HLS LLM benchmark 需要同时保存功能和综合 QoR 证据。
5. [Bench4HLS](https://arxiv.org/abs/2601.19941) 进一步把端到端 HLS 评估与可插拔 PPA 分析结合，并用 pass@k 处理 LLM 输出的随机性。

设计结论：单次运行使用硬功能门和连续 QoR 分数；模型级比较同时报告 pass@1/pass@k、有效样本上的 QoR、全任务宏平均和置信区间，避免一个平均分掩盖功能失败率。

### 1.4 Search 4: 递减收益函数

检索式：`diminishing returns scoring function log scale sublinear reward optimization benchmark`

主要来源与提取结果：

1. [NIST Dictionary of Algorithms and Data Structures: logarithmic](https://xlinux.nist.gov/dads/HTML/logarithmic.html) 将 logarithmic growth 归为 sublinear growth。
2. [NIST Engineering Statistics Handbook: transformations](https://www.itl.nist.gov/div898/handbook/pmd/section6/pmd624.htm) 将 `ln` 列为处理正值尺度差异的常见变换。
3. 递减边际收益通常由单调凹函数表达。本提案不直接使用会无限增长的裸 `log(r)`，而使用 `atan(beta * log(r))`：它保留比率尺度、严格单调、在高加速区边际收益递减，并渐近接近边界但永不在有限加速处封顶。

设计结论：`8x < 27x < 100x` 在任何有限输入下都严格成立；不存在 `ACCEL_CAP` 或参考点后的 `min(..., 1)`。

---

## 2. D-1: 新评分公式规范

### 2.1 输入与证据优先级

| 公式输入 | 数据来源 | 使用方式 |
|---|---|---|
| hidden 功能结果 | grader 的 hidden `CSimTool` | 失败直接 `Score=0` |
| hidden RTL 功能结果 | `CoSimResult.status` | `requires_cosim=true` 时失败直接 `Score=0` |
| synth 状态 | 候选 `ToolResult.ok` | 失败进入最高 20 分的降级分支 |
| latency | `CoSimResult.latency_max/avg/min` 或 `SynthReport.latency_worst/avg/best` | structural 优先 cosim；其他任务使用 synth |
| clock | `SynthReport.clock_period_ns`、`Task.clock_ns` | 用有效周期换算 latency time，并惩罚未达到目标时钟的结果 |
| II | `SynthReport.interval_max/min` | 相对基准 II 和绝对 II 共同计分 |
| resources | `SynthReport.resources` | 计算相对几何资源增长 `G` |
| device totals | `SynthReport.available` | 计算器件 headroom 惩罚 `H` |
| budget | `Budget.spent/total` | 计算预算质量 `B` |
| attempts | `Budget.calls`、tool transcript | 每次调用已按可配置 cost 增加 `spent`；不重复扣分，单独报告失败次数 |
| task policy | `Task.type`、`requires_cosim`、可选 scoring target | 选择 improve、preserve 或 reference-match 路径 |
| difficulty | `Task.difficulty` | 不乘单任务分数，只用于跨任务 difficulty-weighted aggregate |

Latency 证据优先级：

```text
requires_cosim=true:
  cosim.latency_max -> latency_avg -> latency_min -> synth latency with fallback penalty

requires_cosim=false:
  synth.latency_worst -> latency_avg -> latency_best
```

structural 任务的 cosim 没通过时已经触发功能门，不允许回退到 synth latency 继续拿 QoR 分。

### 2.2 不可覆盖的门控规则

```text
if hidden_tb_pass is false:
    Score = 0

if task.requires_cosim and hidden_cosim_pass is false:
    Score = 0

if hidden functionality passes but candidate synthesis fails:
    Score = SYNTH_FAIL_MAX * budget_quality
    0 <= SYNTH_FAIL_MAX <= 20
```

工具/基础设施自身失败应标记为 `evaluation_invalid` 并重试，不应伪装成设计功能失败。只有确认由候选设计导致的 hidden test/cosim fail 才执行归零。

### 2.3 通用无硬封顶比率函数

对任意正比率 `r` 定义：

```text
D_beta(r) = 1/2 + atan(beta * ln(r)) / pi,    beta > 0
```

性质：

- `0 < D_beta(r) < 1`，但任何有限 `r` 都不会碰到人为 cap。
- `D_beta(1)=0.5`。
- 一阶导数恒正，因此严格单调；`100x > 27x > 8x`。
- 对 `r>1`，相对于 `ln(r)` 的边际收益递减。
- `r<1` 自动给出低于 0.5 的回归分，不需要额外分支封顶。

默认 `beta=0.75`：

| 比率 | `D_0.75(r)` |
|---:|---:|
| 0.5x | 0.348 |
| 1x | 0.500 |
| 8x | 0.819 |
| 27x | 0.878 |
| 100x | 0.910 |

### 2.4 Latency quality `L`

先把周期数换算成保守的时间：

```text
effective_period = max(task.clock_ns, report.clock_period_ns)
latency_time = selected_latency_cycles * effective_period
r_L = baseline_latency_time / candidate_latency_time
```

这样候选即使通过 HLS synthesis，但估计时钟比目标慢，也不能仅靠较少 cycles 获得虚高加速。对于零周期组合逻辑，使用以下明确规则而非计算 `0/0`：

```text
base=0, cand=0  -> r_L=1
base>0, cand=0  -> r_L=(base+LATENCY_EPS_CYCLES)/LATENCY_EPS_CYCLES
base=0, cand>0  -> r_L=LATENCY_EPS_CYCLES/(cand+LATENCY_EPS_CYCLES)
```

任务类型映射：

| task type | latency anchor | `L` |
|---|---|---|
| `optimize` | starting kernel | `D_beta(r_L)` |
| `structural` | starting kernel；候选优先 cosim latency | `D_beta(r_L)` |
| `repair` | starting kernel | 若不回归则 `1`，回归时 `D_beta(r_L)` |
| `synth_fix` | reference 或显式 target | 若达到/保持 target 则 `1`，否则比率计分 |
| `generate` | reference kernel 或显式 target | `R_q(r_L)`，默认 reference-match 得 0.85 |

reference-match 映射为：

```text
R_q(r) = 1 / (1 + ((1-q)/q) * r^(-beta))
```

它同样严格单调且无有限点硬封顶，并满足 `R_q(1)=q`。默认 `q=0.85`，所以达到参考实现的 generate 候选有现实路径取得高分。

repair 的“不回归”默认容差为 2%。`projection_bugfix` 的 `0 -> 0` 明确属于保持，不再因 `0/0` 丢失性能项。

### 2.5 Area quality `A`

对每种资源 `r in {LUT, FF, DSP, BRAM_18K, URAM}`：

```text
g_r = (candidate_r + epsilon_r) / (anchor_r + epsilon_r)
G   = exp(sum_r(resource_weight_r * ln(g_r)))
```

`resource_weight_r` 先归一化为和 1。默认权重：

```text
LUT=0.30, FF=0.20, DSP=0.20, BRAM_18K=0.20, URAM=0.10
epsilon_r=1
```

`epsilon_r` 使“基准和候选均为 0”得到比率 1，也让“基准为 0、候选新增资源”得到有限但明确的惩罚。几何聚合避免单个资源种类完全吞没其他资源，同时保留每类资源的相对变化。

相对面积质量：

```text
A_rel = 1 / (1 + ((1-A_NEUTRAL)/A_NEUTRAL) * G^AREA_ALPHA)
```

默认 `A_NEUTRAL=0.75`、`AREA_ALPHA=0.75`：

- `G=1` 时 `A_rel=0.75`，资源保持得到大部分面积分。
- `G<1` 时 `A_rel>0.75`，面积改善获得奖励。
- `G>1` 时 `A_rel<0.75`，面积膨胀受到惩罚。
- 函数平滑且没有 `AREA_FLOOR` 或 `AREA_BONUS_CAP`。

器件余量：

```text
M = max_r((candidate_r / available_r) / soft_util_limit_r)
H = (1 + exp(-HEADROOM_K)) / (1 + exp(HEADROOM_K * (M - 1)))
A = A_rel * H
```

默认 LUT/FF soft limit 为 70%，DSP/BRAM/URAM 为 80%，`HEADROOM_K=6`。低利用率时 `H` 接近 1；达到 soft limit 时约为 0.5；继续接近器件容量时快速降低。因而同样的相对面积增长，在只用器件 1% 与已经使用 80% 时不会得到相同评价。

area anchor 与 latency anchor 一致：optimize/structural/repair 使用 starting kernel；generate/synth_fix 在 starting kernel 不可综合时使用 reference 或显式 target。没有 anchor 时必须写入 `metric_status`，并使用保守缺失值，不能假装 `G=1`。

### 2.6 Throughput quality `T`

II 既有相对改进，也有绝对工程意义。默认组合二者：

```text
T_abs(II) = 1 / (1 + ln(max(II, 1)) / ln(II_ABS_REF))
T = II_RELATIVE_WEIGHT * D_beta(base_II / candidate_II)
  + (1-II_RELATIVE_WEIGHT) * T_abs(candidate_II)
```

默认 `II_RELATIVE_WEIGHT=0.70`、`II_ABS_REF=1024`。`II=1` 的绝对项为 1；II 越大，绝对项越低。generate 的相对项使用 `R_q`；repair/synth_fix 在 II 无回归时设置 `T=1`。因此相同 latency 下 `II=1` 严格高于 `II=100`，II 回归也会受罚。

### 2.7 Budget quality `B`

```text
u = clamp(budget.spent / budget.total, 0, 1)
B = (1-u)^BUDGET_GAMMA
```

默认 `BUDGET_GAMMA=0.70`。每个 csim/synth/cosim 已按 `CREDIT_COST` 计入 `spent`，所以失败重试自动降低 `B`：

- 10/40：`B=0.818`
- 38/40：`B=0.123`
- 66/80：`B=0.295`

不再单独按失败次数重复扣分，否则同一次失败会被 tool cost 和 failure count 双重计算。报告仍应保存 `failed_csim/synth/cosim`，用于解释和 agent 诊断。

### 2.8 最终分数与聚合

功能和综合均通过时：

```text
Score = 100 * (
    w_completion * 1
  + w_latency    * L
  + w_area       * A
  + w_ii         * T
  + w_budget     * B
) / sum(weights)
```

默认：

| 维度 | 权重 | 设计理由 |
|---|---:|---|
| completion | 0.30 | hidden functionality + synth 已经是门，过门后仍保留基础完成分 |
| latency | 0.30 | 首要连续优化目标，并计入 clock |
| area | 0.28 | 与 latency 接近但略低，强力抑制暴力展开 |
| throughput/II | 0.08 | 独立识别流水吞吐能力 |
| budget | 0.04 | 严格区分效率，但不让搜索成本压倒最终硬件质量 |

权重优先级符合 `correctness -> synthesizability -> latency -> area -> throughput -> budget`。correctness 和 structural cosim 是硬门，synth failure 最高 20，因此它们的优先级不依赖普通加权和。

单任务分数始终为 `0..100`，与 difficulty 无关。跨任务同时报告：

```text
macro_score      = mean(task_score)
difficulty_score = sum(difficulty_i * task_score_i) / sum(difficulty_i)
functional_rate  = functional_passes / tasks
synth_rate       = synth_passes / tasks
```

主 leaderboard 建议先比较 functional pass rate，再比较 difficulty-weighted score；或至少并列报告两者，避免少量高 QoR 样本掩盖大量功能失败。

### 2.9 环境变量

所有可调参数集中在 `llm4hls/config.py` 解析和校验，不在 `scoring.py` 模块导入时散落读取。

| 环境变量 | 默认值 |
|---|---:|
| `LLM4HLS_SCORE_W_COMPLETION` | `0.30` |
| `LLM4HLS_SCORE_W_LATENCY` | `0.30` |
| `LLM4HLS_SCORE_W_AREA` | `0.28` |
| `LLM4HLS_SCORE_W_II` | `0.08` |
| `LLM4HLS_SCORE_W_BUDGET` | `0.04` |
| `LLM4HLS_SCORE_RATIO_BETA` | `0.75` |
| `LLM4HLS_SCORE_LATENCY_EPS_CYCLES` | `1.0` |
| `LLM4HLS_SCORE_REFERENCE_MATCH` | `0.85` |
| `LLM4HLS_SCORE_REPAIR_REGRESSION_TOL` | `0.02` |
| `LLM4HLS_SCORE_AREA_ALPHA` | `0.75` |
| `LLM4HLS_SCORE_AREA_NEUTRAL` | `0.75` |
| `LLM4HLS_SCORE_RESOURCE_WEIGHTS` | `LUT=.30,FF=.20,DSP=.20,BRAM_18K=.20,URAM=.10` |
| `LLM4HLS_SCORE_RESOURCE_EPS_LUT` 等五项 | `1` |
| `LLM4HLS_SCORE_SOFT_UTIL_LUT`、`FF` | `0.70` |
| `LLM4HLS_SCORE_SOFT_UTIL_DSP`、`BRAM_18K`、`URAM` | `0.80` |
| `LLM4HLS_SCORE_HEADROOM_K` | `6.0` |
| `LLM4HLS_SCORE_II_RELATIVE_WEIGHT` | `0.70` |
| `LLM4HLS_SCORE_II_ABS_REF` | `1024` |
| `LLM4HLS_SCORE_BUDGET_GAMMA` | `0.70` |
| `LLM4HLS_SCORE_SYNTH_FAIL_MAX` | `20.0`，校验范围 `[0,20]` |
| `LLM4HLS_SCORE_COSIM_FALLBACK_FACTOR` | `0.90` |
| `LLM4HLS_SCORE_MISSING_METRIC` | `0.25` |
| `LLM4HLS_SCORE_VERSION` | `v2` |

tool costs 已由 `LLM4HLS_COST_CSIM/SYNTH/COSIM` 覆盖。target part、clock、timeout 继续使用现有 `LLM4HLS_PART`、`LLM4HLS_CLOCK_NS` 和 timeout 环境变量。

配置校验必须拒绝非正权重、权重和为 0、非正的 beta/alpha/gamma、不在 `(0,1)` 的 neutral/reference 参数，以及大于 20 的 synth-fail 上限。覆盖后的普通维度仍必须满足 `w_latency > w_area > w_ii > w_budget > 0`，每类 resource weight 也必须为正；这样参数可调而验收标准的优先级不会被误配置破坏。hidden functional fail 归零不是参数，不允许环境变量关闭。

### 2.10 11 个缺陷的修复映射

| Brief 缺陷 | V2 修复 |
|---|---|
| 1. 面积未入公式 | `A_rel` 占 28%，并覆盖五类资源 |
| 2. `ACCEL_CAP` 天花板 | `D_beta` 对所有有限正比率严格单调，无 `min` cap |
| 3. repair 被封顶在 70% | preserve policy：正确且 PPA 不回归时 `L=T=1` |
| 4. 无预算效率 | `B=(1-spent/total)^gamma` |
| 5. 无 II/吞吐 | 相对 II + 绝对 II 独立占 8% |
| 6. 忽略 cosim latency | structural 使用 `latency_max -> avg -> min` |
| 7. 不感知器件余量 | `H` 根据候选/available 与 soft limit 惩罚高利用率 |
| 8. cosim 失败成本不可见 | 每次 cosim 的 20 credits 进入 `spent`，降低 `B` |
| 9. 实测 latency 未进入加速 | `r_L` 对 structural 使用 cosim measured latency |
| 10. 面积改善无奖励 | `G<1 -> A_rel>A_NEUTRAL` |
| 11. 预算耗尽不受罚 | `spent/total` 越大，`B` 严格越小，满预算时预算项为 0 |

---

## 3. D-2: `grade()` Python-like 伪代码

```python
def grade(task, candidate_kernel, work_root, budget, config) -> ScorecardV2:
    cfg = validate_score_config(config)  # env already resolved in config.py

    # 1. Hidden validation. Infrastructure errors invalidate/retry the eval.
    hidden_csim = run_hidden_csim(task, candidate_kernel, work_root)
    if hidden_csim.infrastructure_error:
        raise EvaluationInvalid(hidden_csim.error)
    if not hidden_csim.ok:
        return zero_scorecard(reason="hidden_tb_fail")

    hidden_cosim = None
    if task.requires_cosim:
        hidden_cosim = run_hidden_cosim(task, candidate_kernel, work_root)
        if hidden_cosim.infrastructure_error:
            raise EvaluationInvalid(hidden_cosim.error)
        if not hidden_cosim.ok or not hidden_cosim.cosim.passed:
            return zero_scorecard(reason="hidden_cosim_fail")

    # 2. Synthesize candidate and scoring anchors.
    cand = synth(candidate_kernel)
    anchor = choose_anchor(task)  # starting code, reference code, explicit target, or None
    base = None
    if anchor is not None:
        base = synth_or_load_cached(anchor) if anchor.has_code else anchor.report

    budget_q = budget_quality(
        spent=budget.spent,
        total=budget.total,
        gamma=cfg.budget_gamma,
    )

    # 3. Correct C behavior but no hardware implementation: AC-8 branch.
    if not cand.ok or cand.report is None:
        score = cfg.synth_fail_max * budget_q
        return ScorecardV2(
            score=score,
            score_max=100.0,
            functional_pass=True,
            synth_pass=False,
            gate_reason="synth_fail_partial_credit",
            budget_quality=budget_q,
        )

    # 4. Latency source and clock-aware ratio.
    cand_cycles, latency_source = select_candidate_latency(
        task=task,
        synth_report=cand.report,
        cosim_result=hidden_cosim.cosim if hidden_cosim else None,
        priority=("cosim_max", "cosim_avg", "cosim_min", "synth_worst"),
    )
    base_cycles = select_anchor_latency(base) if base is not None else None
    if base_cycles is None or cand_cycles is None:
        latency_q = cfg.missing_metric
        latency_status = "missing"
    else:
        r_latency = clock_aware_ratio(
            base_cycles=base_cycles,
            cand_cycles=cand_cycles,
            base_period=effective_period(task.clock_ns, base.clock_period_ns),
            cand_period=effective_period(task.clock_ns, cand.report.clock_period_ns),
            zero_cycle_epsilon=cfg.latency_eps_cycles,
        )

        if task.type in {"repair", "synth_fix"} and no_regression(
            r_latency, cfg.repair_regression_tol
        ):
            latency_q = 1.0
        elif task.type == "generate":
            latency_q = reference_quality(
                r_latency, cfg.reference_match, cfg.ratio_beta
            )
        else:
            latency_q = diminishing_ratio(r_latency, cfg.ratio_beta)
        latency_status = "measured"

    if latency_source == "synth_fallback_for_cosim":
        latency_q *= cfg.cosim_fallback_factor

    # 5. Area growth plus device headroom.
    if base is None or base.resources is None:
        area_q = cfg.missing_metric * device_headroom(cand.report, cfg)
        area_status = "anchor_missing"
    else:
        growth = {}
        for resource in RESOURCES:
            growth[resource] = (
                cand.report.resources[resource] + cfg.resource_epsilon[resource]
            ) / (
                base.resources[resource] + cfg.resource_epsilon[resource]
            )

        geometric_growth = exp(sum(
            cfg.resource_weights[r] * log(growth[r]) for r in RESOURCES
        ))
        area_relative = 1.0 / (
            1.0
            + ((1.0 - cfg.area_neutral) / cfg.area_neutral)
            * geometric_growth ** cfg.area_alpha
        )
        headroom = device_headroom(cand.report, cfg)
        area_q = area_relative * headroom
        area_status = "measured"

    # 6. Throughput. Missing XML data is conservative, not silently neutral.
    base_ii = worst_ii(base)
    cand_ii = worst_ii(cand.report)
    if cand_ii is None:
        throughput_q = cfg.missing_metric
        ii_status = "missing"
    elif task.type in {"repair", "synth_fix"} and ii_no_regression(
        base_ii, cand_ii, cfg.repair_regression_tol
    ):
        throughput_q = 1.0
        ii_status = "preserved"
    else:
        absolute_q = absolute_ii_quality(cand_ii, cfg.ii_abs_ref)
        if base_ii is None:
            throughput_q = absolute_q
        else:
            relative_ratio = base_ii / cand_ii
            if task.type == "generate":
                relative_q = reference_quality(
                    relative_ratio, cfg.reference_match, cfg.ratio_beta
                )
            else:
                relative_q = diminishing_ratio(relative_ratio, cfg.ratio_beta)
            throughput_q = (
                cfg.ii_relative_weight * relative_q
                + (1.0 - cfg.ii_relative_weight) * absolute_q
            )
        ii_status = "measured"

    # 7. Normalized 0..100 score. Difficulty is intentionally absent.
    values = {
        "completion": 1.0,
        "latency": latency_q,
        "area": area_q,
        "ii": throughput_q,
        "budget": budget_q,
    }
    numerator = sum(cfg.weights[k] * values[k] for k in values)
    score = 100.0 * numerator / sum(cfg.weights.values())

    return ScorecardV2(
        scoring_version="v2",
        score=score,
        score_max=100.0,
        functional_pass=True,
        synth_pass=True,
        cosim_pass=hidden_cosim.cosim.passed if hidden_cosim else None,
        dimensions=values,
        latency_source=latency_source,
        latency_status=latency_status,
        area_status=area_status,
        ii_status=ii_status,
        baseline_report=base,
        candidate_report=cand.report,
        budget_spent=budget.spent,
        budget_total=budget.total,
        config_snapshot=cfg.to_public_dict(),
    )
```

---

## 4. D-3: 验收标准与真实数据验证

所有数值使用 §2 默认参数，器件利用率很低的案例取 `H≈1`。表中分数四舍五入到两位。

### 4.1 AC-1 至 AC-8

| AC | 场景与中间值 | 结果 | 判定 |
|---|---|---:|---|
| AC-1 | 同为 27.03x、II=39、15/40；小面积 LUT/FF=500/200，其他资源保持相同：`A=0.565`；真实大面积：`A=0.212` | **81.51 > 71.62** | PASS |
| AC-2 | 资源、II、预算相同；8x/27x/100x 的 `L=0.819/0.878/0.910` | **69.85 < 71.62 < 72.60** | PASS |
| AC-3 | repair hidden pass、synth pass、0->0 latency、II=1、面积不变、10/20：`L=1,A=.75,T=1,B=.616` | **91.46 >= 85** | PASS |
| AC-4 | 同一最终 kernel，10/40 与 38/40：`B=.818/.123` | **85.37 > 82.59** | PASS |
| AC-5 | 同 latency/area/budget，baseline II=1025；candidate II=1/100：`T=.958/.764` | **87.87 > 86.32** | PASS |
| AC-6 | structural baseline=135，synth=100，cosim=150；选择 150，`r_L=.9,L=.475`，而非 synth 的 `r_L=1.35,L=.570` | **使用 cosim 150** | PASS |
| AC-7 | hidden TB fail | **0.00** | PASS |
| AC-8 | hidden CSim pass、synth fail；即使预算未使用也最高 20；若 10/40 则 `20*.818` | **16.35 <= 20** | PASS |

AC-2 的分数差会随加速增加而缩小，但永远保持严格顺序；这正是递减收益，不是硬封顶。

器件余量缺陷也做了独立边界检查：在其他条件和 `A_rel=.75` 相同时，LUT 使用率 1% 得到 `H=.9998,A=.7498`；LUT 使用率 80%（soft limit=70%）得到 `H=.2987,A=.2240`。因此高占用候选即使仍可综合，也会为缺少部署余量付出明确代价。

### 4.2 `projection_bugfix` 真实运行与坏候选

真实数据：repair、latency `0->0`、II=1、资源无回归、hidden/synth pass、10/20 credits。

| 候选 | hidden | synth | PPA | budget | V2 |
|---|---|---|---|---:|---:|
| 真实修复 | PASS | PASS | latency/II/area 保持 | 10/20 | **91.46** |
| 同一修复，更少验证调用 | PASS | PASS | 相同 | 5/20 | **92.27** |
| 修错 `angle==0` 分支 | FAIL | 可综合 | 任意 | 任意 | **0.00** |
| CSim 正确但写入不可综合结构 | PASS | FAIL | 无 | 10/20 | **12.31** |

最后一行按 `20 * (1-10/20)^0.7 = 12.31`。真实修复超过 85 分，并且不再因组合逻辑 latency=0 被锁死在 70%。

### 4.3 `dotProduct_optimize` 真实运行与四个候选

共同基准：latency=1027、II=1025、LUT=156、FF=93、DSP=2；所有候选假设 hidden/synth pass、15/40 credits、低器件利用率。

Brief 只给了反事实候选的 latency 和 LUT/FF。为验证 II 维度，这里明确加入假设：B/C/D 的 II 分别为 100/16/1，DSP 分别为 4/8/200；这不改动真实候选 A 的数据。

| 候选 | accel | II | LUT / FF / DSP | `L` | `A` | `T` | V2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| A 真实运行 | 27.03x | 39 | 13189 / 54194 / 64 | .878 | .212 | .810 | **71.62** |
| B 面积高效 | 10x | 100 | 500 / 200 / 4 | .833 | .656 | .764 | **82.36** |
| C 均衡 | 15x | 16 | 2000 / 800 / 8 | .854 | .510 | .845 | **79.55** |
| D 极端展开 | 100x | 1 | 50000 / 200000 / 200 | .910 | .121 | .958 | **71.25** |

新公式给出 `B > C > A > D`。解释如下：

- A 的 27x 加速被完整识别，没有在 8x 截断；但几何资源增长 `G=24.92`，面积分明显下降。
- B 虽然只有 10x，但资源成本低得多，整体工程质量最好。
- C 以更高性能和吞吐换取中等面积，位于 B 与 A 之间。
- D 的 100x 和 II=1 仍比 A 获得更高性能项，但极端面积成本使总分最低。性能贡献没有被 cap，只是被独立面积维度抵消。

对于 AC-1 的严格隔离场景，保持 accel、II、DSP、BRAM、URAM、budget 全部相同，只把 LUT/FF 从 `13189/54194` 改成 `500/200`，总分从 `71.62` 上升到 `81.51`。

### 4.4 `residual_stream_deadlock` 真实运行与对照

真实数据：structural、hidden CSim/cosim pass、baseline synth latency=135、candidate synth latency=68、cosim max=97、LUT `539->406`、FF `248->231`、66/80 credits。

| 场景 | latency source | `L` | `A` | `B` | V2 |
|---|---|---:|---:|---:|---:|
| 真实运行 | cosim 97 | .577 | .764 | .295 | **73.88** |
| 相同 kernel，首次结构修复即通过，26/80 | cosim 97 | .577 | .764 | .759 | **75.74** |
| 错误地沿用 synth 68 | synth 68 | .651 | .764 | .295 | **76.10**，禁止使用 |
| hidden cosim 仍死锁 | 无 | 任意 | 任意 | 任意 | **0.00** |

面积几何比 `G=0.906<1`，所以 `A=.764>.75`，明确奖励面积改善。真实运行两次失败 cosim 消耗 40 credits，使预算项下降；同一最终 kernel 若在第一次修复后通过，严格得到更高分。

上表因 Brief 未提供候选 II，暂以中性假设 `T=.5` 做离线数学比较。正式 grader 读取候选 `interval_max` 后重算，不允许把这个假设写死。

---

## 5. D-4: Difficulty / Budget 校准

### 5.1 Difficulty 不再改变单任务量尺

difficulty 表示任务先验复杂度，只用于任务抽样、预算分配和 aggregate 权重。每个任务的 `score_max` 都是 100，因此“90 分 repair”和“90 分 structural”都表示该任务目标完成质量很高，不再出现 max=2/max=4 的不可比量尺。

建议 rubric：

| difficulty | 典型特征 | 预期验证复杂度 |
|---:|---|---|
| 1 | 单点语法/常量/pragma 修正，故障定位明确 | 1-2 次低成本验证 |
| 2 | 局部功能修复或单循环优化 | 2-4 次 csim/synth |
| 3 | 多循环、数据类型、pipeline/unroll 权衡 | 4-7 次混合验证 |
| 4 | 跨函数 dataflow、stream、需要 cosim 的结构问题 | 至少一次昂贵 RTL 验证 |
| 5 | 架构级重写、多阶段优化、多个有效 Pareto 路径 | 多轮 synth/cosim 与候选竞争 |

difficulty 由两位任务设计者独立标注，再用 pilot 数据校准。若相邻等级的基线成功率/成本分布大量重叠，应修改标签而不是调评分权重去“补偿”。

### 5.2 默认预算

先按 difficulty 给 base credits，再乘 task-type 系数，并向上取整到可支付一次最贵必需工具的单位：

| difficulty | base credits |
|---:|---:|
| 1 | 12 |
| 2 | 20 |
| 3 | 40 |
| 4 | 64 |
| 5 | 96 |

| task type | multiplier |
|---|---:|
| repair | 1.00 |
| optimize | 1.00 |
| synth_fix | 1.25 |
| generate | 1.25 |
| structural / requires_cosim | 1.25 |

这给出 Brief 中三个实例的自然预算：difficulty-2 repair 为 20，difficulty-3 optimize 为 40，difficulty-4 structural 为 80。

环境变量：

```text
LLM4HLS_BUDGET_D1..D5=12,20,40,64,96
LLM4HLS_BUDGET_MULT_REPAIR=1.0
LLM4HLS_BUDGET_MULT_OPTIMIZE=1.0
LLM4HLS_BUDGET_MULT_SYNTH_FIX=1.25
LLM4HLS_BUDGET_MULT_GENERATE=1.25
LLM4HLS_BUDGET_MULT_STRUCTURAL=1.25
```

task.toml 的显式 `budget` 仍优先于默认表，以支持特殊任务。

### 5.3 数据驱动校准

每次 benchmark 版本冻结前，至少用 3 个 agent/model、每任务 5 个随机种子做 pilot：

1. 成功运行的预算使用中位数目标为 40%-65%，P90 不超过 90%。
2. 每个 difficulty 至少包含 10 个任务，检查功能成功率随等级大体下降。
3. 检查每个维度的分布和 Spearman 排序，防止某一项几乎恒定或支配总分。
4. 对权重做敏感性分析，参数在建议范围内变化 10% 时，明显优劣候选不应翻转。
5. 冻结 benchmark 后固定参数和配置 snapshot，不按参赛结果追调。

模型级报告建议包含：pass@1、pass@k、所有任务 macro mean、difficulty-weighted mean、仅功能通过任务的 QoR mean、预算均值，以及按 task bootstrap 的 95% CI。至少报告 5 个随机种子；leaderboard 主值优先使用 pass@1 与全任务 aggregate，pass@k 作为搜索潜力补充。

---

## 6. D-5: 实施路线图

本仓库 `AGENTS.md` 规定 `llm4hls/` 是官方 harness 的只读镜像。因此正式评分变更必须先进入上游 `fpt26-harness`，再整体同步到 agent 仓库；不能只在本 agent 私自替换权威 grader。未接入的 `llm4hls/scoring_v2.py` 和 `tests/test_scoring_v2.py` 原型因仍含 acceleration/reference cap、area floor/bonus cap、repair 特殊上限和 difficulty multiplier，且不满足本规范，现已删除；生产评分只使用当前 `scoring/scoring_v3.py`。

### Phase 0: 规范冻结

- 评审本文件的默认权重、task-type policy 和 generate/reference 语义。
- 为每个任务冻结 `task.toml` 的 `scoring` metadata：可选 latency/II/resource target、anchor policy、是否 requires_cosim。
- 冻结环境变量名、范围和 scorecard schema v2。

### Phase 1: 上游纯数学内核

- 在上游 `llm4hls/config.py` 增加 `ScoreConfig`，集中解析、归一化、范围校验和配置 snapshot。
- 在上游 `llm4hls/scoring.py` 增加无 I/O 的 helper：`diminishing_ratio()`、`reference_quality()`、`area_quality()`、`throughput_quality()`、`budget_quality()`、`combine_score()`。
- `grade()` 继续负责 hidden tools，但把解析后的证据传给纯数学 `score_evidence()`，使 AC 测试不需要 Vitis。
- 不在 module import 时捕获环境变量；在每次 run 启动时构造不可变 config，保证测试可覆盖且报告可复现。

### Phase 2: 数据模型与报告

- `llm4hls/task.py`：支持可选 `[scoring]` target/anchor 字段；旧 task.toml 无该节时按 task type 推导。
- `llm4hls/report.py`：保持现有 SynthReport/CoSimResult 字段；增加 latency/II 选择 helper 和 evidence provenance，不改变原 parser 兼容字段。
- `llm4hls/budget.py`：Budget 结构无需破坏性修改；向 score evidence 传入 `spent/total/calls`。
- `agent/workflow.py`：仍只调用官方 `llm4hls.scoring.grade()`；同步上游后传入 metered budget snapshot。不要在 workflow 内复制公式。
- `agent/reporting.py`：写入 `scoring.version="v2"`、`score/score_max=100`、五维分数、latency source、area growth、headroom、budget quality、config snapshot 和 metric status。
- `agent/eval.py`：按 `score_max` 聚合，不再假设 max=difficulty；同时输出 macro/difficulty-weighted、pass rate 和 schema version。

### Phase 3: 测试

- 将 AC-1 至 AC-8 写成对 `score_evidence()` 的真实断言，不允许 `pass` 占位。
- 增加数学性质测试：`D_beta` 在随机正比率上严格单调；不存在 8、31 或任意参考点后的相等区间。
- 增加 area 单调性、`G<1` 奖励、80% headroom、零基准资源、missing metric、零 latency、timing regression 测试。
- 用 §8 固定 fixture 锁定 `91.46/71.62/73.88` 附近的默认结果；浮点断言使用小容差。
- 仅运行纯数学/JSON 测试即可完成本轮迁移验证，不要求 Vitis。集成发布前再由上游 CI 做 hidden tool smoke test。

### Phase 4: 双写与切换

1. 一个 benchmark 版本内同时计算 v1 和 v2，leaderboard 仍读 v1，报告双写 `scoring_v1`、`scoring_v2`。
2. 比较排序变化、缺失字段率和 task-type 分布；公开所有默认参数。
3. 下一 benchmark major version 切换 `LLM4HLS_SCORE_VERSION=v2` 为唯一主分，保留 v1 reader，不再运行 v1 grader。

### `run_report.json` schema 迁移

建议新增：

```json
{
  "schema_version": 2,
  "task_difficulty": 3,
  "scoring": {
    "version": "v2",
    "score": 71.62,
    "score_max": 100.0,
    "functional_pass": true,
    "synth_pass": true,
    "cosim_pass": null,
    "gate_reason": "passed",
    "dimensions": {
      "completion": 1.0,
      "latency": 0.878,
      "area": 0.212,
      "ii": 0.810,
      "budget": 0.720
    },
    "latency_source": "synth_worst",
    "resource_geomean_growth": 24.925,
    "headroom": 0.999,
    "config": {}
  }
}
```

reader 兼容策略：

- `schema_version` 缺失视为 v1。
- v1 的 `score_pct = score/task_difficulty*100` 仅用于历史展示，禁止与 v2 原始 `score` 直接相加。
- 跨版本比较统一转换为百分比，并明确标记 formula version；正式 leaderboard 不混合版本。
- 迁移脚本只能把 v1 报告标注为 v1，不能在缺少 II、available resources、cosim measured latency、budget snapshot 时伪造 v2 分数。
- 若旧报告保存了完整 SynthReport/CoSimResult/Budget 证据，可离线重算并写入 `scoring_recomputed_v2`，同时保留原始 v1 字段。

---

## 7. 最终验收清单

| 要求 | 证据 |
|---|---|
| §5 四个 Web 搜索 | §1，含来源和设计结论 |
| 修复 11 个缺陷 | §2.10 逐项映射 |
| AC-1 至 AC-8 | §4.1 全部 PASS，含数值 |
| 三次真实数据 + 假设候选 | §4.2 至 §4.4 |
| D-1 公式规范 | §2 |
| D-2 伪代码 | §3 |
| D-3 验证表 | §4 |
| D-4 难度/预算校准 | §5 |
| D-5 实施路线 | §6 |
| 参数可由环境变量覆盖 | §2.9、§5.2 |
| hidden fail 一票否决 | §2.2 |
| 面积膨胀罚、改善奖 | §2.5、§4 |
| 无 acceleration 硬封顶 | §2.3、AC-2 |
| repair 可得高分 | `projection_bugfix=91.46` |
