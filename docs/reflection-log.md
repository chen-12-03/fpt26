# Agent 缺陷反思日志

> 基于 30 个 generated task 的系统性诊断，每 task 四维分析：诊断准确性、LLM 相关性、Gate 行为、资源浪费。

---

## 1. polybench__doitgen

**最终 score: 74.42 | Q_HW: 0.771 | credits: 20/60 | LLM rounds: 4**

### 诊断准确性 ⚠️
- 正确识别了 `PipelineII=6>1` 和 `PipelineII=None` 的循环
- 但诊断信息过于模糊：`"classify the reported loop violation (recurrence, timing, or memory ports) before adding a matching directive"` — agent 不知道具体瓶颈类型
- `II=None` 出现 3 次（嵌套循环），未解释

### LLM 相关性 ⚠️
- R1: 几乎 no-op（9941→9921），20 cycle 差异可能是 noise
- R2: PIPELINE → latency 9941→1075，但 LUT 2828→14004 (5x)，**资源开始失控**
- R3: 继续激进 → latency 119, LUT 109520, DSP 1548, **70x 面积增长**
- LLM 看到了 latency 大幅下降就继续加码，完全无视资源爆炸

### Gate 行为 ❌ **严重问题**
- **capacity gate 未触发**：`capacity = None`，70x LUT 增长未被拦截
- Q_HW gate 放行了 R2 (0.7572) 和 R3 (0.771)，因为 Q_HW 只看综合分，资源惩罚不够
- 最终提交了 LUT 109520 的方案，这是不可部署的
- **Bug: capacity gate 对 70x 资源增长返回 None**

### 资源浪费
- 4 LLM rounds + 4 C-sim + 4 synth = 20 credits
- R4 是 semantic no-op，浪费 1 次 LLM
- R3 的 synth 完全可以在 pre-synth 阶段被容量检查拦住

---

## 2. polybench__durbin

**最终 score: 72.98 | Q_HW: 0.75 | credits: 15/60 | LLM rounds: 2**

### 诊断准确性 ⚠️
- 识别了 `PipelineII=4>1`
- 循环 trip count 显示 `trip=None` — Vitis 无法静态推算，可能是 data-dependent bound
- 诊断未区分 recurrence vs timing vs memory
- `trip=None` 未被传递给 LLM 作为警告

### LLM 相关性 ❌
- R1: PIPELINE → clock 6.179→17.399ns (2.8x)，latency 11585→7022，Q_HW 降到 0.4846
- R2: 同样 PIPELINE → clock 仍 17.399ns，同样的方向，Q_HW 0.6374
- **LLM 不理解 clock degradation**：加了 PIPELINE 后 clock 恶化 3 倍，即使 latency 降低也救不回来
- 两次尝试都是同一个方向，没有从 R1 失败中学习

### Gate 行为 ✅
- Q_HW gate 两次都正确拒绝
- 最终正确回退 starter

### 资源浪费
- 2 LLM rounds + 3 C-sim + 3 synth = 15 credits
- **如果能 pre-synth 估算 clock impact，可以省 2 次 synth**

---

## 3. polybench__atax

**最终 score: 72.98 | Q_HW: 0.75 | credits: 15/60 | LLM rounds: 2**

### 诊断准确性 ⚠️
- `PipelineII=21>1`，是三个中最严重的 II violation
- 同样的模糊诊断
- 未区分这是 recurrence（依赖循环传递）还是 memory port

### LLM 相关性 ❌
- R1: 几乎 no-op（949→949），仅 `UNROLL factor=2` 在某些地方，latency 完全没变
- R2: PIPELINE → clock 3.854→17.399ns (4.5x)，latency 949→4112 (**反而更差**)，Q_HW 0.5286
- II=21 说明有强 recurrence，PIPELINE 不是正确答案，LLM 没有这个判断力

### Gate 行为 ✅
- Q_HW gate 正确拒绝
- 最终正确回退 starter

### 资源浪费
- 2 LLM rounds + 3 C-sim + 3 synth = 15 credits
- R1 的 `UNROLL` 在 II=21 的循环上毫无意义（瓶颈不在 loop body 宽度）
- R2 的 PIPELINE 导致 clock 灾难，应被 pre-synth 诊断预防

---

## 4. polybench__gesummv

**最终 score: 72.98 | Q_HW: 0.75 | credits: 15/60 | LLM rounds: 2**

### 诊断准确性 ⚠️
- `PipelineII=15>1`，只有一个 dominant loop
- 同样的模糊诊断模板
- 没有分析 II=15 是 recurrence（循环内积累依赖）还是 memory port

### LLM 相关性 ❌
- R1: PIPELINE II=1 → latency 520→71 (7.3x)，但 LUT 5610→48260 (8.6x)、DSP 52→673 (13x)。**典型的资源换 latency 失控**
- R2: 不同策略 → latency 520→2277 (**反而慢了 4 倍**)，Q_HW 0.6881
- 两次尝试分别过了 resource explosion 和 latency degradation，LLM 在两个极端摇摆

### Gate 行为 ✅
- Q_HW gate 两次正确拒绝
- 最终正确回退 starter

### 资源浪费
- 2 LLM rounds + 3 C-sim + 3 synth = 15 credits
- R1 的 48260 LUT 方案明显不可部署，应在 pre-synth 被容量检查拦住

---

## 5. polybench__cholesky

**最终 score: 72.98 | Q_HW: 0.75 | credits: 15/60 | LLM rounds: 2**

### 诊断准确性 ⚠️
- `PipelineII=11>1`，多个 `trip=None` 循环
- 基础 latency 713881 cycles（极长），说明有深层嵌套循环
- 诊断没有区分 recurrence vs timing

### LLM 相关性 ❌
- R1: PIPELINE → clock 3.625→17.399ns (4.8x)，latency 713881→700241（仅降 1.9%），Q_HW 0.6245
- R2: 几乎 no-op，latency/资源完全相同
- **clock 恶化 4.8x 但 latency 几乎不变** — PIPELINE 对 recurrence 主导的循环无效
- R2 浪费：完全重复 R1 的无效方向

### Gate 行为 ✅
- Q_HW gate 正确拒绝
- 最终正确回退 starter

### 资源浪费
- 2 LLM rounds + 3 C-sim + 3 synth = 15 credits
- R2 是 R1 的无效变体，可以用语义指纹去重

---

## 6. polybench__heat_3d

**最终 score: 72.98 | Q_HW: 0.75 | credits: 15/60 | LLM rounds: 2**

### 诊断准确性 ⚠️
- `PipelineII=4>1` 在两个嵌套循环中
- 基础 latency 83281 cycles，高延迟
- 诊断增加了 `"identify the dominant loop from loop-level evidence"` 但没有实际分析

### LLM 相关性 ❌
- R1: PIPELINE → II 从 4 变成 21 (**更差了**)，LUT 4909→8856，Q_HW 0.6677
- R2: 几乎 no-op，回到几乎相同的指标
- **加了 PIPELINE 反而让 II 恶化 4→21**，LLM 不理解这违反了优化意图

### Gate 行为 ✅
- Q_HW gate 正确拒绝两次
- 最终正确回退 starter

### 资源浪费
- 2 LLM rounds + 3 C-sim + 3 synth = 15 credits

---

## 7. polybench__mvt

**score: 72.98 | Q_HW: 0.75 | credits: 10/60 | rounds: 2**

### 诊断 ⚠️
- II=20，同样模糊诊断
- 未区分两个对称循环（各 trip=40, II=20）的关系

### LLM ❌ → Gate ✅
- R1: 几乎 no-op（1713→1713），Q_HW 不变，正确拒绝
- R2: 语义重复，被指纹去重跳过了 C-sim/synth
- 最终安全回退

### 亮点
- 语义去重（semantic duplicate detection）正确工作：R2 0 tools

---

## 8. polybench__correlation

**score: 72.98 | Q_HW: 0.75 | credits: 15/60 | rounds: 2**

### 诊断 ⚠️
- 混合场景：II=16 的循环 + II=1 的 dominant loop (trip=896)
- Agent 正确识别 II=1 的 dominant loop 并建议 UNROLL
- 但同时 II=16 的循环被忽略了

### LLM ❌
- R1: UNROLL → latency **从 15209 增加到 60758 (4x)**！资源反而减少。**完全搞反了方向**
- 说明 LLM 对 UNROLL 的 latency 效果没有基本判断力

### Gate ✅
- Q_HW gate 正确拒绝（0.5557）

---

## 9. polybench__trmm

**score: 72.98 | Q_HW: 0.75 | credits: 15/60 | rounds: 2**

### 诊断 ⚠️
- II=11, trip=None — data-dependent bound
- 极长 latency 132041 cycles

### LLM ❌
- R1: PIPELINE → latency **增加**（132041→133201），资源翻倍，clock 恶化。完全反效果
- R2: no-op，被拒绝

### Gate ✅
- 正确拒绝，安全回退

---

## 10. polybench__floyd_warshall ⭐ **HLS 200-448!**

**score: 73.93 | Q_HW: 0.75 | credits: 5/60 | rounds: 3 | tokens: 8859**

### 诊断 ✅ **好案例**
- 正确识别 HLS 200-448 on `path` array，II lower bound=2
- action_contract 正确生成 `targets=['path']`
- 是继 Stencil 之后第二个命中 HLS 200-448 的 task！

### LLM ❌
- R1: pragma-only → contract gate 静态拒绝（0 tools）
- R2: 同样 pragma-only → 再次拒绝（0 tools）
- R3: 语义重复 → 收敛
- **3 轮 LLM 全部在 C-sim 前被拦住，但 LLM 始终没有生成 `ARRAY_PARTITION variable=path` 的 matched action**

### Gate ✅✅ **优秀**
- Contract gate 每次都在工具前拒绝 pragma-only actions
- 语义去重识别 R3 重复
- 只消耗了 1 C-sim + 1 synth = 5 credits，效率极高

### 关键发现
- **action_contract 的静态门能拦住错误候选但无法引导 LLM 生成正确 action**
- 3 轮 LLM 都不理解 "必须对 `path` 做 partition"
- 这正是 Stencil 拿到 DSE 前反复遇到的问题！floyd_warshall 是 DSE 可以发挥作用的第二个 task

---

## 15-18.  chstone countLeadingZeros64/float64_abs + c2hlsc monobit/aes

**全部 Q_HW 0.75, 安全回退**

### 同质模式
- countLeadingZeros64: no loops, interval=3 — agent 仍跑了 2 轮浪费 10 credits
- float64_abs: no loops, latency=0, interval=1 — 2 轮浪费 10 credits
- monobit: no loops, pipeline=yes — 2 轮浪费 10 credits
- aes: II=8 loop, LLM 首轮 semantic no-op → 直接收敛 → **5 credits，高效**

### 新发现：aes 快速收敛
- aes 有 II=8 的循环但 LLM 选择了 no-op
- 可能是 prompt 建议"先分类再 action" + "不要随便 PIPELINE"的效果
- 比之前 10 个 task 的无脑 PIPELINE 更合理

### 累计统计（18/30）
- 产生硬件改善: 1 task（doitgen，70x 面积爆炸）
- 纯浪费: 14 task（全部 Q_HW 0.75，credits 全部无效）
- 有 HLS 200-448 但 LLM 不会用: 2 task（Stencil, floyd_warshall）
- 快速收敛: 1 task（aes，5 credits）
- **平均 Q_HW 改善: 接近 0**

---

## 19-20. c2hlsc__des / block

**Q_HW 0.75, 安全回退**

- des: II=5 loop, 2 rounds LLM 都生成无效 candidate, 去重拦截 R2
- block: `II=None`, LLM 首轮 no-op → 5 credits, 高效收敛

---

## 21-22. machsuite__nw_nw / bfs_queue ❌ **Baseline C-sim 失败**

**credits: 1/60 each, 无 score**

### 严重缺陷
- 两个 task 在 **baseline C-sim 阶段就 runtime_fail (rc=-6)**
- Testbench 本身有问题（或 Docker 资源不足）
- Agent 无法继续，1 credit 后停止
- **没有明确的错误信息帮助诊断 rc=-6**

### 期望行为
- 区分 "testbench 有 bug" vs "Docker 资源不足" vs "代码不兼容"
- 给出 actionable 错误信息

---

## 23-25. machsuite gemm_blocked / sort_radix / viterbi_viterbi ❌ C-sim failure

**全部 rc=-6 runtime_fail, 1 credit each, VALID=FAIL**

- **5/5 machsuite 非 Stencil task 全部在 baseline C-sim 失败**
- rc=-6 需要被诊断：是数据文件缺失？超时？testbench bug？
- 当前 agent 无任何诊断信息

---

## 26. rosetta rendering_3d__projection
**Q_HW 0.75, no loops, combinational — 标准不可优化模式**

## 27. rosetta digit_recognition__popcount
**Q_HW 0.75, loop II=1, 2 rounds → 10 credits 浪费**

## 28. pp4fpga block_mm
**Q_HW 0.75, DATAFLOW design, 2 rounds → 11 credits 浪费**

## 29. gnnbuilder compute_neighbor_tables ⭐ **真实改善!**
**score: 75.28 | Q_HW: 0.75→0.82 | credits: 10/50 | latency: 1555→559 (2.78x)**

### 分析
- 诊断说 `PipelineII=1 已最优`，但 LLM 仍找到 latency 从 1555→559 的优化
- LUT 504→629 (+25%), FF +51%，面积增长可控
- Q_perf 0.9301, Q_area 0.6381
- **这是 30 个 task 中唯一真实、合理的硬件改善！**

### 关键差异
- II=None → II=1：LLM 把未 pipelined 的循环变成 pipelined
- baseline 的 `PipelineII=None` 说明循环没有被 Vitis 自动 pipeline
- LLM 加了合适的 pragma 使循环被 pipeline

## 30. flowgnn fgnn_linear_output_stationary
**Q_HW 0.75, 大设计 (LUT 39103, FF 55631, DSP 640), 2 rounds → 10 credits 浪费**

---

# 30 Task 缺陷汇总

## 总体统计

| 类别 | 数量 | 占比 |
|---|---|---|
| **零改善**（Q_HW 0.75，安全回退） | 21 | 70% |
| **Baseline C-sim 失败**（rc=-6） | 5 | 17% |
| **虚假"改善"**（资源爆炸，capacity gate 漏过） | 1 | 3% |
| **真实改善**（gnnbuilder Q_HW +0.07） | 1 | 3% |
| **HLS 200-448 但 LLM 不会用** | 2 | 7% |

## 按缺陷类型分类

### 🔴 P0: Capacity Gate 未触发 (doitgen)
- 70x LUT 增长未被拦截，`capacity=None`
- 可能导致不可部署的"优化"方案被提交

### 🔴 P0: 不可优化 task 不识别 (14 task)
- `loops=none` + `interval≤2` 的组合逻辑函数仍然跑 LLM 优化
- 浪费 ~100 credits
    
### 🔴 P0: Machsuite C-sim 系统性失败 (5 task)
- 5/5 非 Stencil machsuite task 在 baseline C-sim rc=-6
- testbench 需要 input data 或 Docker 资源不足

### 🟡 P1: LLM 对 II>1 循环一律 PIPELINE (15+ task)
- 导致 clock 恶化 2-5x 或 latency 反而增加
- 诊断只说 "classify the violation" 但不提供分类
- LLM 从 failure 中不学习，重复同样策略

### 🟡 P1: HLS 200-448 → LLM 不生成 ARRAY_PARTITION (2 task)
- floyd_warshall 3 轮 LLM 全部 pragma-only，全被 gate 拦
- action_contract 能识别 target 但无法引导 LLM 生成正确 action

### 🟡 P1: Clock degradation 未被预判 (10+ task)
- PIPELINE 导致 clock 恶化 3-5x，但只在 synth 后才发现
- 浪费大量 synth credits

### 🟢 P2: 语义去重工作正常
- 多个 task 显示 "semantic duplicate — skip csim/synth"
- 有效节省了重复测试

### 🟢 P2: Q_HW gate 基本正确
- 除 doitgen 外，所有无效 candidate 都被正确拒绝
- 最终全部安全回退 starter

## 结论

**当前 agent 对 93%（28/30）的 generated task 无法产生有效硬件改善。**

核心问题不是 gate 或 scorer，而是：
1. **诊断层太薄**：`PipelineII>1` 不分 recurrence/timing/memory，LLM 只能盲猜 PIPELINE
2. **无 pre-synth 估算**：clock impact 要到 synthesis 后才知道
3. **不可优化 task 不识别**：combinational 逻辑仍浪费 credits
4. **Machsuite testbench 兼容性**：5/5 失败

