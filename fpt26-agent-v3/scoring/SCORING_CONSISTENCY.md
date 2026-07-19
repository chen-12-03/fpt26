# V10 统一评分 — calibrated weighted hardware ratio

**版本：10.0 | 日期：2026-07-19 | 当前权威 schema：10**

## 核心公式

```python
def ratio_quality(r):
    return 1 - 1 / (1 + r) ** 2

latency_ratio = anchor_effective_time / candidate_effective_time
performance_ratio = latency_ratio
# 仅在可靠 II 明确适用时：
# performance_ratio = latency_ratio**0.85 * ii_ratio**0.15

area_growth = max(growth_by_resource)
area_ratio = 1 / area_growth
hardware_ratio = performance_ratio**0.55 * area_ratio**0.45

q_perf = ratio_quality(performance_ratio)  # 诊断字段
q_area = ratio_quality(area_ratio)         # 诊断字段
q_hw = ratio_quality(hardware_ratio)       # 最终硬件质量

efficiency = max(0.80, 1 - 0.10*cost_ratio - 0.10*time_ratio)
score = 100 * validity * q_hw * efficiency
```

`W_PERFORMANCE=0.55`、`W_AREA=0.45` 且指数和严格为 1。reference 标准化
分数通过 `grade_standardized_qor()` 显式固定 `efficiency=1`；该入口不接受 cost/time
参数，并在 scorecard 标记 `score_mode=standardized_qor` 与
`efficiency_source=explicit_standardized_override`。production `grade()` 继续使用真实
cost/time，两类分数不得混用。

`validity` 还要求来自冻结 anchor synth report 的完整 device capacity：LUT、FF、DSP、
BRAM_18K、URAM 五项必须都是正整数。缺失/partial capacity 以
`required_metric_missing` fail closed；candidate 任一资源超过 total 时以
`resource_capacity_exceeded` 得 0。Area growth 使用 schema 9 起冻结的统一 1.0 count
floor；device capacity 只用于完整性与超容量 hard gate，不再改变各资源增长比的尺度。

对 `requires_cosim=True` 的 task，`candidate_effective_time` 中的 cycles 必须来自通过的
RTL co-simulation `latency_max`；synth report 只继续提供 clock、II、resources 与 synth
gate。Cosim gate 未明确 PASS 时以 `hidden_cosim_fail` 失败；PASS 但缺少 measured latency
时以 `required_metric_missing` fail closed。非 cosim task 仍使用 synthesis latency。

## V9 → V10 权重校准

- reference 语义在搜索权重前冻结：95 个 PPA reference（其中 94 个 generated
  starter/reference 源码相同）与 2 个 correctness-only reference；unknown 为 0。
- 99 份 fresh evidence 来自真实 Vitis 2025.2：97 个 task 全量一次，加上
  dotProduct 两次隔离 repeat。三次 dotProduct 的原始指标与 XML hash 完全一致，保守
  `P=1027/36`、`A=1/32`，约束下界为 `w>=0.5084248300102405`。
- 0.55 位于可行区间内部，距下界约 `0.04157517`；dotProduct standardized score
  为 `81.5426694494`，相对 75 有 `6.5426694494` 分余量。0.50/0.52/0.55/0.60
  对应分数为 73.5441/76.9327/81.5427/87.8325。
- 84 个可评分 identity reference 在所有权重下严格为 75；另 10 个 identity task 的
  Vitis 顶层 latency 不定，明确标记不可评分，不伪造 latency。PPA reference 中没有
  Pareto-dominated 项；correctness-only projection 的 reference 面积诊断被 starter
  支配，但不进入权重约束。

完整机器可读证据由 `scoring/analyze_reference_calibration.py` 生成；公式、边界和分数
均调用本 scoring 模块，未用外部手算代替。

## V7 → V8 变更理由

`CoSimTool` 同时返回 synthesis estimate（`ToolResult.report`）与 RTL measured result
（`ToolResult.cosim`）。V7 的 `step_score()` 错把前者的 `latency_worst` 写进
`QoREvidence.cosim_latency`，导致 scorecard 虽声明 `acceleration_source=cosim`，实际按
synth estimate 计分。

V8 不改变公式、权重、utility、capacity 或效率策略，只把 required-cosim 的 evidence
路由到 `cosim.latency_max`，缺失时 fail closed，并在 `run_report` 记录
`acceleration_source` 与 `cosim_latency_used`。这是评分证据一致性修复，不是 Agent 性能
提升；V7/V8 必须以同一真实 artifact 双评分，不能直接作为连续趋势。

## V6 → V7 capacity 历史

V6 的 scorer 已实现容量 hard gate，但最终 workflow 与 optimization-time proxy 构造
`Anchor` 时显式传入 `available={}`。真实 Vitis `csynth.xml` 已包含完整 device totals，
集成层却丢弃该字段，导致 `check_capacity()` 从不执行，resource-floor 也退化。

V7 不改变 V6 的任何公式、权重、utility、correctness gate 或效率策略，只完成三件事：

- 验证并传播 anchor synth report 的五项 device totals；
- 缺失 capacity 时 fail closed，超容量时保留独立 gate reason；
- 在 `Scorecard`/`run_report` 中记录 `available_resources` 与
  `resource_capacity_pass`，使判定可审计。

V6 → V7 是 capacity 集成修复；其同产物双评分和 fresh V7 基线记录在
`docs/iteration-log.md`。

## V5 → V6 公式历史

V5 先分别压缩 performance/area ratio，再做
`sqrt(q_perf*q_area)`。这破坏 reciprocal symmetry：等比例 speedup 与 resource
growth 会低于 baseline；当 worst growth 达到 2× 时，即使 speedup 趋于无穷，
Q_HW 也无法超过 baseline 0.75，形成意外 hard ceiling。

V6 先在 log-ratio 域做等权几何折中，再映射一次。它保证：

- `speedup == area_growth` 时与 baseline 中性；
- `speedup / area_growth > 1` 时 Q_HW 高于 baseline，反之低于；
- 固定资源时更快严格更高，固定性能时更小严格更高；
- 任意有限 resource growth 都可被足够大的真实 performance improvement 超越；
- 极端 area bloat、性能回退仍连续、单调地受罚。

V5 → V6 是公式一致性修复；其同产物双评分和 V6 基线记录在
`docs/iteration-log.md`，不得与 V7 趋势混用。

## 保持不变

- 所有 task 使用同一 `valid_then_optimize` 目标，task type 仅为标签。
- hidden functional、synthesis、required cosim、capacity 等 validity gates 是硬约束；
  任一 required gate 失败，score 为 0。
- Effective latency 使用 `max(task_clock, estimated_clock) * cycles`；required cosim
  可用时以 measured latency 为准。
- Area 继续使用相对 anchor 的最差显著资源增长，防止单一资源成为实现瓶颈。
- Efficiency 仅对 tool credits 与 grading wall time 做有界扣分。
- API prompt/completion/total token 以及 provider 可选 cached/reasoning token 继续只作
  可观测性记录，不进入 score，避免抑制合理 reflection/multi-agent；未上报字段必须记
  `unavailable`，不得估算。

## 版本边界

- `scoring/__init__.py`: `__version__ = "10.0.0"`
- `scoring/scoring_v3.py`: 当前实现文件（文件名为兼容 harness 保持不变）
- `Scorecard.schema_version = 10`
- Schema 10 是 0.55/0.45 raw-ratio 加权几何聚合，并增加显式 standardized QoR
  score mode 与未舍入 QoR 组件入口；schema 9 是相同 validity/resource 语义但 0.5/0.5
  权重的旧基线。
- Schema 7 是相同公式/capacity 但 required-cosim 仍路由 synth estimate 的旧基线；
  schema 6 是未集成 capacity 的旧基线；schema 5 是更早的 pre-composition 公式。此前
  实验性 token V6/V7 run 与这些权威 schema 无关，不得混用。当前 schema 的识别特征是
  `hardware_ratio`、`available_resources`、`resource_capacity_pass`、
  `acceleration_source`、`cosim_latency_used`、`score_mode`、
  `efficiency_source`、`performance_weight` 和 `area_weight` 字段。
