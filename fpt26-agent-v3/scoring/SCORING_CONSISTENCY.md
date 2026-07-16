# V8 统一评分 — measured-cosim, capacity-integrated hardware ratio

**版本：8.0 | 日期：2026-07-16 | 当前权威 schema：8**

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
hardware_ratio = sqrt(performance_ratio * area_ratio)

q_perf = ratio_quality(performance_ratio)  # 诊断字段
q_area = ratio_quality(area_ratio)         # 诊断字段
q_hw = ratio_quality(hardware_ratio)       # 最终硬件质量

efficiency = max(0.80, 1 - 0.10*cost_ratio - 0.10*time_ratio)
score = 100 * validity * q_hw * efficiency
```

`validity` 还要求来自冻结 anchor synth report 的完整 device capacity：LUT、FF、DSP、
BRAM_18K、URAM 五项必须都是正整数。缺失/partial capacity 以
`required_metric_missing` fail closed；candidate 任一资源超过 total 时以
`resource_capacity_exceeded` 得 0。相同 capacity 同时用于显著资源 floor，避免把器件
规模信息丢失后用无设备默认值评价 area growth。

对 `requires_cosim=True` 的 task，`candidate_effective_time` 中的 cycles 必须来自通过的
RTL co-simulation `latency_max`；synth report 只继续提供 clock、II、resources 与 synth
gate。Cosim gate 未明确 PASS 时以 `hidden_cosim_fail` 失败；PASS 但缺少 measured latency
时以 `required_metric_missing` fail closed。非 cosim task 仍使用 synthesis latency。

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

- `scoring/__init__.py`: `__version__ = "8.0.0"`
- `scoring/scoring_v3.py`: 当前实现文件（文件名为兼容 harness 保持不变）
- `Scorecard.schema_version = 8`
- Schema 7 是相同公式/capacity 但 required-cosim 仍路由 synth estimate 的旧基线；
  schema 6 是未集成 capacity 的旧基线；schema 5 是更早的 pre-composition 公式。此前
  实验性 token V6/V7 run 与这些权威 schema 无关，不得混用。当前 V8 的识别特征是
  `hardware_ratio`、`available_resources`、`resource_capacity_pass`、
  `acceleration_source` 和 `cosim_latency_used` 字段。
