# V5 统一评分 — 一致性保证

**版本：5.0 | 日期：2026-07-16**

## 核心公式

```python
def ratio_quality(r):   return 1 - 1/(1+r)**2     # unified utility
q_latency  = ratio_quality(anchor_time / candidate_time)
q_ii       = ratio_quality(anchor_ii / candidate_ii)  # if applicable
q_perf     = 0.85 * q_latency + 0.15 * q_ii
q_area     = ratio_quality(1 / max(growth_by_resource))
q_hw       = sqrt(q_perf * q_area)
efficiency = max(0.80, 1 - 0.10*cost_ratio - 0.10*time_ratio)
score      = 100 * validity * q_hw * efficiency
```

## 关键设计

- **无 task type 分支**：所有任务同一公式，task_type 仅为标签
- **统一 utility**：`1-1/(1+r)²`，baseline(1x)=0.75，无需逐任务锚点
- **Anchor 选择**：starter valid → starter；starter invalid → reference；none → reject
- **requires_cosim**：仅为验证门，不改变评分
- **Token 暂不计分**：API 服务端上报的 prompt/completion/total token 继续写入
  `run_report.json.llm.token_usage`，用于预算观察和工作流诊断，但不进入
  `efficiency` 或最终 score，避免抑制合理的多 Agent、reflection 和反馈回环
- **Schema**：当前权威 scorecard 保持 `schema_version=5`；实验性 V6/V7
  结果不得作为当前最终 score
