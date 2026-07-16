# V6 统一评分 — log-symmetric hardware ratio

**版本：6.0 | 日期：2026-07-16 | 当前权威 schema：6**

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

## V5 → V6 变更理由

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

这次版本变化是评价一致性修复，不是 Agent 性能提升。V5 与 V6 score 不得直接作为
连续趋势；切换轮必须双重评分并建立 V6 新基线。

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

- `scoring/__init__.py`: `__version__ = "6.0.0"`
- `scoring/scoring_v3.py`: 当前实现文件（文件名为兼容 harness 保持不变）
- `Scorecard.schema_version = 6`
- 2026-07-16 之前的 schema 5 是旧基线；此前实验性 token V6/V7 run 不是本公式，
  不得混用。当前 V6 的识别特征是 `hardware_ratio` 字段和本文件所述公式。
