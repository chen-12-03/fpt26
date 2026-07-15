# FPT26 LLM4HLS Agent 评分规范 V3.0

**状态：研究支撑的设计评审稿**  
**日期：2026-07-15**  
**适用对象：FPT26/LLM4HLS 类 agent 竞赛中，由 agent 生成、修复或优化的 HLS/RTL 产出物**  
**前序版本：`scoring-redesign-proposal.md`（V2）**

---

## 0. 结论摘要

V3 不再把评分理解为“给 correctness、latency、area、II、budget 各分配一个经验权重”，而是明确分成四个互不混淆的层次：

1. **有效性门控（Validity Gate）**：隐藏功能验证、必要的 RTL co-simulation、综合/实现和资源可行性只要有一项失败，正式单任务分数为 0。语法、C 仿真、综合进度仍报告，但只作为诊断，不进入正式榜分。
2. **硬件产出物质量（Hardware QoR）**：用实际 workload 下的端到端时间统一 latency 与 II；用增广资源增长函数同时考虑多资源平均变化和最坏资源瓶颈；再以严格单调的归一化效用函数映射到 0..1。
3. **Agent 效率（Agent Efficiency）**：成本和 wall-clock runtime 只构成有界扣减，不把预算耗尽直接乘成 0，也不再按失败次数重复扣分。
4. **竞赛聚合（Leaderboard Aggregation）**：主榜优先比较有效任务率，再比较 difficulty-weighted 总分；同时发布 bootstrap 置信区间、pass@1、pass@k 和统计并列组。

正式单任务分数为：

$$
\boxed{
Score_i = 100\;V_i\;Q_{HW,i}\;E_i
}
$$

其中：

$$
Q_{HW}=q_{perf}^{w_{perf}}q_{area}^{w_{area}},\qquad
E=\max(E_{min},1-\lambda_c u_c-\lambda_t u_t)
$$

默认值：

| 参数 | 默认值 | 含义 |
|---|---:|---|
| $w_{perf}$ | 0.60 | workload 级性能质量权重 |
| $w_{area}$ | 0.40 | 多资源与器件余量质量权重 |
| $\lambda_c$ | 0.10 | 满成本预算最多扣 10% |
| $\lambda_t$ | 0.10 | 满时间预算最多扣 10% |
| $E_{min}$ | 0.80 | agent 效率因子下限 |

这套结构直接吸收了 FPL'26 官方竞赛的“无效为 0 + 质量乘有界成本/时间扣减”思路 [R1][R2]，同时遵循 AMD 对 latency、II、throughput、resource utilization 的并列定义 [R4][R5]，并结合 HLS/RTL LLM benchmark 的递进验证模式 [R6]-[R10] 与 HLS 多目标 Pareto DSE 文献 [R11]-[R14]。

---

## 1. 对 V2 的正式审计

### 1.1 V2 中应保留的设计

V2 已正确建立以下基础：

- hidden testbench 和必要 co-simulation 是功能硬门；
- latency 使用有效时钟周期换算，不只看 cycle 数；
- LUT、FF、DSP、BRAM、URAM 不能被简单折算成一个未经验证的“面积单位”；
- 需要考虑器件余量；
- 高加速收益应递减但不得在有限比率处硬封顶；
- scorecard 应记录证据来源、配置和中间项；
- difficulty 不应改变单任务 0..100 量尺。

这些结论与 AMD HLS 指标、HLS-Eval、RTLLM、VerilogEval、HLStrans、Bench4HLS 以及多目标 DSE 文献一致 [R4]-[R13]。

### 1.2 V2 必须修改的九项问题

| 编号 | V2 问题 | 风险 | V3 处理 |
|---|---|---|---|
| M1 | hidden 功能通过但综合失败仍可得最高 20 分 | 正式榜分混入不可部署产出物，与 FPL/ISPD 有效性规则冲突 | 正式分为 0；另报 `progress_stage` |
| M2 | completion 在硬门之后仍占 30% | 对“已经通过同一硬门”的候选重复奖励，压缩 QoR 区分度 | 删除 completion 维度 |
| M3 | latency 与 II 分开加权 | 对同一性能现象可能双重计分，且没有体现一次性与流式 workload 差异 | 合成为 $T=P(L+(N-1)II)$ |
| M4 | budget 用 $(1-u)^\gamma$ | 用满允许预算时效率项为 0，可能让优秀产出物被预算完全抹除 | 改为最多 20% 的有界扣减 |
| M5 | 失败次数可能再次进入效率评价 | 工具调用成本和 wall time 已包含失败，额外 attempt penalty 会双重计数 | attempts 仅诊断，不进公式 |
| M6 | 简单资源几何平均会稀释单类资源爆炸 | 一个 500 倍 FF 增长可能被多个未使用资源平均掉 | 加入 $\max z_r$ 的瓶颈项 |
| M7 | 通用 `missing_metric=0.25` | agent 可能通过破坏报告解析获得可预测的非零分 | 必需指标缺失视为无效或 evaluation invalid |
| M8 | 环境变量可覆盖正式评分参数 | 若提交环境可影响变量，构成直接评分攻击面 | 正式参数来自签名/哈希的 evaluator config |
| M9 | 额外 ADP 或 Pareto bonus 的诱惑 | ADP 与 performance/area 会双重计数；离散 bonus 造成不连续跳变 | ADP 仅诊断；Pareto 性由单调聚合保证 |

### 1.3 对此前“A+B”草案中若干建议的纠正

本 V3 **不采用**下列方案：

- 不采用 `Score = Quality^0.85 * Efficiency^0.15` 这类无法解释满预算行为的双幂乘积；
- 不采用 `1/(1+log(1+attempt))`，因为 attempt 与成本/时间高度重合；
- 不额外添加 1.1 倍 Pareto bonus，因为连续单调评分已经保证 Pareto 优势，离散 bonus 反而会产生边界刷分；
- 不把 raw ADP 同时放入 latency、area 之外，因为这会重复计算同一变化；
- 不以“代码看起来像参考实现”代替隐藏功能验证。

---

## 2. 研究依据矩阵

| 评分决策 | 官方规则/论文依据 | V3 采用方式 |
|---|---|---|
| 无效产出物正式得分为 0 | FPL'26 [R1][R2]；ISPD'17 [R15]；RTLLM/HLS-Eval [R6][R7] | hidden functional/co-sim/synth/implementation 任一必需门失败，`Score=0` |
| 成本与运行时间不应压倒产出物质量 | FPL'26 对质量施加各 10% 的成本、时间扣减 [R1]；ISPD runtime factor 有界 [R15] | $E=\max(.8,1-.1u_c-.1u_t)$ |
| latency、II、throughput、资源必须同时分析 | AMD UG1399 [R4][R5] | workload 时间统一 latency 与 II，资源独立构成 area quality |
| 生成式硬件评估必须分阶段验证 | HLS-Eval、RTLLM、VerilogEval、Bench4HLS [R6]-[R10] | `progress_stage` 与正式 `valid` 分离 |
| HLS 优化本质是多目标 Pareto 问题 | Chimera、HyperMapper、IronMan [R11]-[R13] | 各目标先归一化，再用严格单调几何聚合；不使用单一 raw latency |
| hypervolume 适合评价设计集合而非单一最终产出物 | Hypervolume survey [R14] | 单次提交不用 hypervolume；若 agent 可提交 Pareto set，则另设 portfolio track |
| 跨 benchmark 应使用参考比率与几何聚合 | SPEC CPU [R16] | hidden case 性能比率使用加权几何平均；重复运行取保守统计量 |
| 竞赛排名需要置信区间和稳健并列 | robust solver ranking [R17] | 10,000 次分层 task bootstrap，报告 95% CI 和 tied groups |
| agent search scaling 本身会提升结果 | Agent Factories、AgRefactor [R18][R19] | 不惩罚 raw attempts；只评价统一预算下的成本、时间和最终产出物 |

---

## 3. 评分对象、术语和证据层级

### 3.1 评分对象

每个任务 $i$ 的 agent 最终提交一个候选产出物 $x_i$。正式评分只评价 **截止时刻保存的 best-so-far 候选**。agent 的中间候选、日志和失败工具调用用于成本计量、诊断与审计，不直接形成额外质量分。

### 3.2 三类报告字段

| 类别 | 例子 | 是否进入正式分 |
|---|---|---|
| Gate evidence | hidden CSim、hidden co-sim、synth、route/DRC、resource capacity | 是，作为 0/1 门 |
| QoR evidence | clock、latency、II、LUT/FF/DSP/BRAM/URAM、可选 power | 是 |
| Agent evidence | API cost、tool credits、wall time、calls、失败次数 | cost/time 进入；calls/失败次数仅诊断 |

### 3.3 证据优先级

性能证据按以下顺序选择：

1. post-route 或可信 RTL 仿真的实测周期/时钟；
2. hidden C/RTL co-simulation；
3. HLS synthesis report；
4. 任何缺失或无法确认来源的字段均不得被默认为“中性”。

对于 `requires_cosim=true` 的 structural/dataflow/stream 任务，hidden co-simulation 失败直接归零，禁止回退到 synth latency 获取正式 QoR 分。

---

## 4. 有效性门控

定义：

$$
V_i = \prod_g \mathbf{1}[g\text{ passes}]
$$

默认必需门：

| Gate | 规则 |
|---|---|
| hidden C functional | 输出与 golden 在冻结容差内一致 |
| hidden RTL functional | `requires_cosim=true` 时必须通过 |
| synthesis | 候选必须生成可解析、完整的 RTL 与综合报告 |
| interface/protocol | AXI/stream/handshake 等任务约束必须满足 |
| resource capacity | 每类资源不得超过 target device available |
| implementation tier | 若赛道要求实现，则 route、DRC、hold、pulse-width 均需通过 |
| timeout | 截止时保存的 best-so-far 候选必须独立通过以上所有门 |

正式规则：

```text
if evaluator_infrastructure_error:
    evaluation_invalid -> retry; do not score
elif any_required_gate_fails:
    score = 0
else:
    continue to QoR scoring
```

`parse_ok / compile_ok / csim_ok / synth_ok / cosim_ok` 仍写入报告，用于研究中的 progressive metrics 和 pass@k，但不得形成 10、20、30 分等正式“安慰分”。

---

## 5. Workload 级性能质量

### 5.1 为什么不再单独加权 latency 与 II

AMD 将 latency 定义为完成一次 transaction 所需周期，将 II 定义为可以启动下一次 transaction 的间隔 [R5]。因此同一个设计在单次请求和长流式 workload 下，性能重点不同。

对 hidden case $c$，冻结 transaction 数 $N_c\ge 1$：

$$
T_{x,c}=P_{x,c}^{eff}\left(L_{x,c}+(N_c-1)II_{x,c}\right)
$$

其中：

$$
P_{x,c}^{eff}=\max(P_{task,c},P_{report,x,c})
$$

- $N_c=1$ 时只评价一次性 latency；
- $N_c\gg 1$ 时 II 自然主导；
- 不再额外增加独立 II 权重，避免双重计分；
- 若非流水模块没有单独 II，任务 manifest 必须声明合法替代语义，例如 `II=L` 或 `N=1`，不能由 grader 猜测。

### 5.2 多 hidden case 聚合

每个 case 权重 $\pi_c>0$ 且 $\sum_c\pi_c=1$：

$$
R_{perf}=\exp\left(\sum_c\pi_c\ln\frac{T_{anchor,c}}{T_{candidate,c}}\right)
$$

这采用参考比率与几何平均，类似 SPEC 对不同 benchmark ratio 的聚合原则 [R16]。它避免某个极大绝对周期数的 case 完全吞没其他 case，同时保持每个 case 的相对改善方向。

### 5.3 通用双锚点效用函数

对任意“比率越大越好”的 $r>0$：

$$
U(r;q_0,r_1,q_1)=\frac{1}{1+\frac{1-q_0}{q_0}r^{-a}}
$$

$$
a=\frac{\operatorname{logit}(q_1)-\operatorname{logit}(q_0)}{\ln r_1}
$$

满足：

- $U(1)=q_0$；
- $U(r_1)=q_1$；
- 当锚点方向一致时严格单调；
- 对任何有限 $r$ 不出现硬 cap；
- 参数由“基准点得多少分、期望目标得多少分”解释，而不是抽象 `beta`。

### 5.4 三种 objective policy

#### Improve

用于 optimize/structural 等任务：

```text
q_perf = U(R_perf;
           q0=0.50 at baseline,
           r1=task.performance_good_ratio,
           q1=0.85)
```

`performance_good_ratio` 必须在 benchmark 冻结前由专家 reference、公开 Pareto 点或 pilot 分布确定。默认 8x 仅供开发，正式任务若仍使用默认值需标记 `uncalibrated_default=true`。

#### Preserve

用于 repair/synth_fix：

$$
q_{perf}=\begin{cases}
1,&T_c\le (1+\tau)T_b\\
x^{-a_p},&x>1
\end{cases}
$$

其中 $x=T_c/((1+\tau)T_b)$，默认 $\tau=2\%$；$a_p$ 由“2x baseline slowdown 得 0.5”确定。正确修复且不回归性能可获得完整性能质量，不再因 baseline latency 为 0 或任务没有优化目标而被限制在低分。

#### Target/Reference

用于 generate：reference match 默认得到 0.85，2x 慢得到 0.5；优于 reference 继续严格提升但有限输入不硬封顶。

---

## 6. 多资源面积与器件余量

### 6.1 不把 FPGA 资源伪装成单一物理面积

LUT、FF、DSP、BRAM、URAM 不可完全互换。V3 只定义“资源代价指数”，并在报告中保留每类原始计数，不声称它是硅面积。

对资源 $r$：

$$
z_r=\ln\frac{C_r+\epsilon_r}{A_r+\epsilon_r}
$$

其中 $C_r$ 为 candidate，$A_r$ 为 anchor，默认 $\epsilon_r=1$ 个物理资源单元。

### 6.2 增广资源增长

$$
z_A=(1-\kappa)\sum_r v_r z_r+\kappa\max_r z_r
$$

$$
G_A=e^{z_A}
$$

默认：

- $\kappa=0.35$；
- 五类资源 $v_r=0.20$；
- 正式任务可冻结 task-specific $v_r$，但所有权重必须为正。

含义：

- 平均项奖励多类资源整体改善；
- 最大项阻止 FF、DSP 或 BRAM 的极端爆炸被其他零资源类别稀释；
- 该结构与 augmented achievement/Tchebycheff 思路一致，且对每类资源单调不减；
- `G_A=1` 表示等效资源保持，`G_A<1` 表示改善。

### 6.3 Relative area utility

对 improve policy：

```text
q_area_rel = U(1/G_A;
               q0=0.75 at G_A=1,
               r1=1/16,
               q1=0.25 at G_A=16)
```

这样默认参数具有直接解释：资源保持获得 0.75；增广资源代价达到 16x 时面积质量为 0.25。该 16x 锚点应在 pilot 后校准，而不是赛后调整。

repair/synth_fix 使用 preserve policy：资源在 2% 容差内不回归时 `q_area_rel=1`；超过后连续下降，2x 增长默认得 0.5。

### 6.4 Absolute headroom

$$
u_r=\frac{C_r}{Available_r}
$$

- 若任意 $u_r>1$，有效性门失败；
- soft limit 默认 LUT/FF 为 0.70，DSP/BRAM/URAM 为 0.80。

对 $u_r>s_r$：

$$
h_r=\exp\left(\ln h_{cap}\left(\frac{u_r-s_r}{1-s_r}\right)^2\right)
$$

否则 $h_r=1$。默认 $h_{cap}=0.10$，并取：

$$
H=\min_r h_r
$$

最终：

$$
q_{area}=q_{area,rel}\cdot H
$$

该函数在 soft limit 处连续且一阶导数为 0，低利用率不罚；接近器件容量时由瓶颈资源平滑降低分数。

---

## 7. 硬件 QoR 聚合

默认：

$$
Q_{HW}=q_{perf}^{0.60}q_{area}^{0.40}
$$

选择加权几何平均而非线性和，原因如下：

1. 严格单调：在另一维不变时，任何性能或面积改善都会提高 $Q_{HW}$；
2. Pareto 一致：同成本下，若 A 在所有硬件维度不差于 B 且至少一维更好，则 A 的 $Q_{HW}$ 更高；
3. 限制完全补偿：极差 area 不能被极高 speedup 线性“买回”；
4. 无离散 bonus：同时更快、更小会自然获益，不需要 1.1x Pareto 奖励；
5. generalized ADP：它已是归一化 performance-area 乘积，因此 raw ADP 只报告、不再次加分。

### 7.1 可选 power/energy 维度

只有当统一实现流程能提供可信 power 时才启用：

$$
Q_{HW}=q_{perf}^{w_p}q_{area}^{w_a}q_{energy}^{w_e}
$$

若当前 `SynthReport` 没有 power，正式名称应为 **Performance-Area QoR**，不得声称测得完整 PPA。

### 7.2 可选 Pareto-set 赛道

若比赛允许 agent 提交一组非支配设计，而非单一 best artifact，可另设 `portfolio_track`：

- 每个设计都必须通过有效性门；
- 用固定 reference point 的 hypervolume 评价集合；
- 集合大小、总生成成本和重复设计需受限。

Hypervolume 对集合支配具有严格单调性 [R14]，但不适合给单一候选凭空制造“Pareto bonus”。

---

## 8. Agent 成本与运行时间

### 8.1 有界效率因子

$$
u_c=\operatorname{clamp}(cost/cost\_limit,0,1)
$$

$$
u_t=\operatorname{clamp}(wall\_time/time\_limit,0,1)
$$

$$
E=\max(0.80,1-0.10u_c-0.10u_t)
$$

这直接对应 FPL'26 官方公式中质量受 API 成本和 runtime 各 10% 扣减的结构 [R1][R2]。不同点是 V3 先把成本和时间归一化到每任务上限，从而适应 difficulty/task type 的不同预算。

### 8.2 不使用 raw attempt penalty

不得加入：

```text
1 / (1 + log(1 + attempts))
failed_calls_penalty
retry_penalty
```

因为：

- 每次调用已增加 cost 与 wall time；
- 失败调用同样计入；
- 多 agent/多候选搜索本身可能是合理算法策略 [R18][R19]；
- 再按 attempts 扣分会双重计数并偏向把多个内部步骤合并成一次不透明调用。

`calls_by_tool`、`failed_calls_by_tool`、`time_to_first_valid`、`time_to_best` 仍完整报告，用于 agent 行为分析。

---

## 9. 最终单任务公式

```text
if evaluator infrastructure failure:
    evaluation_invalid and retry
elif any mandatory validity gate fails:
    Score = 0
else:
    q_perf = performance_quality(evidence, task.scoring)
    q_area = area_quality(evidence, task.scoring)
    Q_hw   = q_perf ** w_perf * q_area ** w_area
    E      = max(E_min, 1 - lambda_cost*u_cost - lambda_time*u_time)
    Score  = 100 * Q_hw * E
```

边界：

- $0\le Score<100$ 对有限 improve 输入成立；
- preserve 任务在 PPA 保持且成本/时间为 0 时允许达到 100；
- 正式 score 不乘 difficulty；
- 所有浮点结果在 scorecard 保存未舍入值，展示时才保留两位。

---

## 10. Task-type 默认策略

| task type | performance policy | resource policy | 默认 $w_{perf}/w_{area}$ | 必需 metadata |
|---|---|---|---:|---|
| optimize | improve | improve | 0.60 / 0.40 | workload cases、anchor、good ratio |
| structural | improve 或 preserve，由任务目标冻结 | improve/preserve | 0.60 / 0.40 | requires_cosim、workload cases |
| repair | preserve | preserve | 0.50 / 0.50 | regression tolerance |
| synth_fix | preserve 或 target | preserve 或 target | 0.50 / 0.50 | valid reference/target |
| generate | target/reference | target/reference | 0.55 / 0.45 | reference metrics 或 aspiration targets |

任务类型不能在运行时由 agent 修改；最终 policy 必须写入 benchmark manifest 并纳入 SHA256。

---

## 11. 缺失指标、异常和可信执行

| 场景 | 处理 |
|---|---|
| 必需 latency/II/resource 字段缺失 | 候选证据不完整，正式分 0；若确认是 parser/infrastructure 缺陷则 evaluation invalid |
| available resources 缺失 | evaluation invalid，不允许假设 headroom=1 |
| cost metering 失败 | evaluation invalid 或采用预先公开的最保守上限；不可悄悄记 0 cost |
| wall time 超限 | 评价截止时保存的 best-so-far；不存在有效候选则 0 |
| baseline/reference 失败 | benchmark invalid，禁止临时更换 anchor |
| 零 latency | 按 task semantics 处理；组合逻辑可定义 $L=0,II=1$，禁止通用 epsilon 猜测 |
| 多时钟 | 只使用 manifest 指定 clock domain；报告其他时钟但不混入 |
| 工具版本漂移 | evaluator image、工具版本、validator SHA 写入 scorecard |

---

## 12. Leaderboard 聚合

### 12.1 主榜排序键

建议使用以下 lexicographic tuple：

```text
1. difficulty-weighted valid rate, descending
2. difficulty-weighted mean task score (invalid tasks already score 0), descending
3. macro mean task score, descending
4. normalized total cost, ascending
5. normalized total wall time, ascending
```

其中：

$$
ValidRate_d=\frac{\sum_i d_i V_i}{\sum_i d_i}
$$

$$
MeanScore_d=\frac{\sum_i d_i Score_i}{\sum_i d_i}
$$

这样 correctness/implementability 优先，不允许少量高 QoR 样本掩盖大量功能失败。difficulty 只用于跨任务聚合，不改变单任务量尺。

### 12.2 为什么不直接采用平均名次作为唯一主值

FPL'26 和 ISPD'17 都使用 per-benchmark rank 聚合 [R1][R15]，适合不同 benchmark 原始量尺难以统一的竞赛。但 rank：

- 丢失分差幅度；
- 依赖参赛队伍集合；
- 新增/退出参赛者会改变历史得分。

V3 已把每任务标准化到 0..100，因此主榜使用原始标准化分；同时可发布 `mean_benchmark_rank` 作为辅助视图。

### 12.3 随机 agent

研究报告默认每个 agent/model 至少 5 个独立 seed：

- 主值：每任务 seed score 的中位数；
- pass@1：单次运行有效率；
- pass@k：固定总预算下至少一个有效候选的概率，仅作搜索潜力指标；
- best-of-k 不作为主榜硬件分，除非所有队伍拥有完全相同的 k、成本和时间预算。

VerilogEval 当前版本强调 pass@1，HLS-Eval 报告 pass@k [R6][R8]；两者应并列而非互相替代。

### 12.4 置信区间和稳健排名

- 对 task 做 difficulty/domain 分层 bootstrap；
- 10,000 个 bootstrap replicate；
- 发布 aggregate score 的 95% percentile CI；
- 对 podium 参赛者做 paired bootstrap 与 Holm-Bonferroni 校正；
- 无显著差异者标为统计并列组。

该流程直接采用 solver competition 稳健排名研究的建议 [R17]。

---

## 13. 参数校准协议

### 13.1 冻结前 pilot

每次 major benchmark 版本至少：

- 3 个能力层次不同的 agent/model；
- 每任务 5 个 seed；
- 每个 difficulty 至少 10 个任务；
- 记录所有 gate、QoR、成本和时间原始证据。

### 13.2 参数不是“拍脑袋权重”，而是锚点

必须校准的不是抽象 beta，而是可解释目标：

| 参数 | 校准问题 |
|---|---|
| `performance_good_ratio` | 对该任务，专家/Pareto reference 的现实良好 speedup 是多少？ |
| `q_perf_good` | 达到该目标应获得 0.80、0.85 还是 0.90？ |
| `area_bad_growth` | 多少增广资源增长应被视为不可接受但仍可综合？ |
| soft utilization | 目标平台保留多少部署余量？ |
| workload $N_c$ | 实际使用场景是单次、微批还是长流？ |
| $w_{perf},w_{area}$ | 任务声明的工程优先级是什么？ |

### 13.3 校准验收

1. 明显 Pareto 支配的候选不得反向排序；
2. 参数上下浮动 10% 时，明显优劣对的排序翻转率低于 5%；
3. 任一维度在有效样本中的 Spearman 相关不应接近 0 或绝对支配总分；
4. 有效 agent 的 cost/time 中位数目标为上限的 40%-70%，P90 不超过 95%；
5. 评分参数在隐藏最终评估前冻结并发布 hash，禁止根据参赛结果追调；
6. 开发环境变量可以方便本地实验，但正式 evaluator 忽略 submission-provided score overrides。

---

## 14. Anti-gaming 清单

| 攻击/刷分方式 | 防护 |
|---|---|
| 破坏 XML 让 metric missing | 必需字段缺失不再给固定 0.25；无效或重评 |
| 只降 cycles、牺牲时钟 | 使用 effective period 计算真实时间 |
| 用极端 unroll 换 speedup | 增广资源瓶颈 + 几何 QoR 聚合 |
| 省略 II 逃避吞吐评价 | $N>1$ 时 II 是必需证据 |
| 反复失败后隐藏 calls | evaluator 侧计量 cost/time；calls 仅审计 |
| 修改评分环境变量 | signed evaluator config + config hash |
| 只针对公开 testbench | hidden tests、hidden workloads、benchmark hash |
| timeout 前未保存最好候选 | 要求原子更新 best-so-far 路径；截止后只验证该文件 |
| 使用参考代码相似度伪装正确 | 只看功能与工具证据，不看表面相似度 |
| 多 seed 只报最好一次 | 固定 seed 数，主值取中位数，best-of-k 仅诊断 |

---

## 15. Scorecard V3 schema

```json
{
  "schema_version": 3,
  "benchmark_sha256": "...",
  "validator_git_sha": "...",
  "evaluator_config_sha256": "...",
  "task": {
    "name": "dotProduct_optimize",
    "difficulty": 3,
    "type": "optimize",
    "requires_cosim": false,
    "scoring_profile_sha256": "..."
  },
  "validity": {
    "valid": true,
    "gate_reason": "passed",
    "hidden_csim_pass": true,
    "hidden_cosim_pass": null,
    "synth_pass": true,
    "implementation_pass": null,
    "metric_completeness_pass": true
  },
  "progress": {
    "stage": "synthesized",
    "parse_ok": true,
    "compile_ok": true,
    "csim_ok": true,
    "synth_ok": true,
    "cosim_ok": null
  },
  "performance": {
    "cases": [],
    "ratio_geomean": 26.33,
    "quality": 0.939,
    "policy": "improve"
  },
  "resources": {
    "raw_candidate": {},
    "raw_anchor": {},
    "raw_available": {},
    "log_growth_by_resource": {},
    "augmented_growth": 56.11,
    "headroom": 1.0,
    "quality": 0.110
  },
  "agent_efficiency": {
    "cost": 15,
    "cost_limit": 40,
    "wall_time_s": 1200,
    "time_limit_s": 3600,
    "calls_by_tool": {},
    "failed_calls_by_tool": {},
    "factor": 0.929
  },
  "score": {
    "hardware_qor": 0.398,
    "value": 36.98,
    "max": 100.0,
    "version": "v3.0"
  },
  "config_snapshot": {}
}
```

所有字段必须标记数据来源和单位。原始字段保留完整精度，scorecard 作为可复核的权威记录 [R2]。

---

## 16. `grade()` Python-like 伪代码

```python
def grade(task, candidate, budget, runtime, evaluator_cfg):
    cfg = load_signed_evaluator_config(evaluator_cfg)

    gates = run_required_hidden_validation(task, candidate)
    if gates.infrastructure_error:
        raise EvaluationInvalid(gates.reason)

    progress = build_progress_diagnostics(gates)
    if not gates.all_required_pass:
        return scorecard(score=0.0, validity=False,
                         gate_reason=gates.first_failure,
                         progress=progress)

    evidence = collect_qor_evidence(task, candidate)
    if evidence.infrastructure_error:
        raise EvaluationInvalid(evidence.reason)
    if not evidence.required_metrics_complete:
        return scorecard(score=0.0, validity=False,
                         gate_reason="required_metric_missing",
                         progress=progress)

    # Performance: latency and II are combined using frozen workload cases.
    case_ratios = []
    for case in task.scoring.workload_cases:
        cand_time = effective_period(case, evidence.candidate) * (
            candidate_latency(case, evidence)
            + (case.transactions - 1) * candidate_ii(case, evidence)
        )
        anchor_time = effective_period(case, evidence.anchor) * (
            anchor_latency(case, evidence)
            + (case.transactions - 1) * anchor_ii(case, evidence)
        )
        case_ratios.append((case.weight, anchor_time / cand_time))

    perf_ratio = exp(sum(w * log(r) for w, r in case_ratios))
    q_perf = apply_objective_policy(
        ratio=perf_ratio,
        policy=task.scoring.performance_policy,
        anchors=task.scoring.performance_anchors,
    )

    # Resources: mean change plus worst resource bottleneck.
    z = {}
    for r in RESOURCES:
        z[r] = log((evidence.candidate.resources[r] + cfg.epsilon[r]) /
                   (evidence.anchor.resources[r] + cfg.epsilon[r]))

    z_area = ((1 - cfg.resource_bottleneck_weight)
              * sum(task.scoring.resource_weights[r] * z[r] for r in RESOURCES)
              + cfg.resource_bottleneck_weight * max(z.values()))
    growth = exp(z_area)

    q_area_rel = apply_objective_policy(
        ratio=1.0 / growth,
        policy=task.scoring.resource_policy,
        anchors=task.scoring.resource_anchors,
    )
    headroom = device_headroom(evidence.candidate, evidence.available, cfg)
    q_area = q_area_rel * headroom

    q_hw = q_perf ** task.scoring.w_perf * q_area ** task.scoring.w_area

    u_cost = clamp(budget.spent / budget.limit, 0.0, 1.0)
    u_time = clamp(runtime.seconds / runtime.limit_seconds, 0.0, 1.0)
    efficiency = max(
        cfg.efficiency_min,
        1.0 - cfg.lambda_cost * u_cost - cfg.lambda_time * u_time,
    )

    score = 100.0 * q_hw * efficiency
    return scorecard(
        score=score,
        validity=True,
        progress=progress,
        q_perf=q_perf,
        q_area=q_area,
        q_hw=q_hw,
        efficiency=efficiency,
        evidence=evidence,
        config_snapshot=cfg.public_snapshot(),
    )
```

---

## 17. 验收标准

### 17.1 Gate 与证据

| AC | 场景 | 必须结果 |
|---|---|---|
| AC-01 | hidden functional fail | `Score=0` |
| AC-02 | requires_cosim 且 hidden cosim deadlock | `Score=0` |
| AC-03 | hidden CSim pass 但 synth fail | `Score=0`，progress 显示 csim passed |
| AC-04 | evaluator license/network/parser infrastructure error | evaluation invalid，重试，不伪装为 design fail |
| AC-05 | $N>1$ 且候选 II 缺失 | `Score=0` 或 benchmark invalid，不能给 missing neutral |

### 17.2 数学性质

| AC | 性质 |
|---|---|
| AC-06 | 固定其他项，performance ratio 严格增加时 score 严格增加 |
| AC-07 | 固定其他项，任一资源减少且无其他资源增加时 score 严格增加 |
| AC-08 | 候选 A 在 performance 与所有资源上 Pareto 支配 B，且效率相同，则 A 分数高于 B |
| AC-09 | 任何有限 speedup 不触发硬 cap；8x < 27x < 100x |
| AC-10 | 资源平均相同但单类最大增长更大时，瓶颈项使 score 更低 |
| AC-11 | soft limit 以下 headroom=1；接近 capacity 连续下降；超过 capacity gate fail |
| AC-12 | 使用满成本和时间预算时效率因子为 0.8，不是 0 |

### 17.3 Anti-double-counting

| AC | 性质 |
|---|---|
| AC-13 | 同一 workload 不再额外加入独立 II 权重 |
| AC-14 | ADP 只输出诊断，不与 performance/area 同时计分 |
| AC-15 | failed calls 已进入成本/时间，不再按 failure count 扣分 |
| AC-16 | completion 不在通过硬门后重复占分 |

### 17.4 聚合与统计

| AC | 性质 |
|---|---|
| AC-17 | 单任务 score 始终 0..100，与 difficulty 无关 |
| AC-18 | invalid task 在 aggregate 中为 0，valid rate 单独报告 |
| AC-19 | 5 seeds 主值取中位数，pass@1/pass@k 单独报告 |
| AC-20 | 10,000 次分层 bootstrap 可复现，随机种子和代码版本写入报告 |

---

## 18. 三个现有案例的 V3 示意重算

**说明：** 这些数值用于检查公式方向，不是正式最终成绩。正式值仍缺 wall time、完整 hidden workload metadata，以及 `residual_stream_deadlock` 的候选 II。默认参数：performance baseline=0.50，8x=0.85；area 保持=0.75，增广增长 16x=0.25；$w_p/w_a=.60/.40$；成本扣减上限 10%，time ratio 暂取 0。

### 18.1 `projection_bugfix`

repair preserve：功能、综合通过，latency/II/resources 均未回归，10/20 credits。

```text
q_perf = 1
q_area = 1
E = 1 - 0.1*(10/20) = 0.95
Score = 95.00
```

更少调用的同一修复（5/20）为 97.50；hidden fail 或 synth fail 均为 0。相较 V2，正式榜不再给不可综合候选 12.31 分。

### 18.2 `dotProduct_optimize`

以下使用 $N=16$，使 latency 与 II 同时进入真实 workload 时间；candidate B/C/D 的 II/DSP 延续 V2 验证假设。

| 候选 | workload speedup | $q_{perf}$ | 增广资源增长 $G_A$ | $q_{area}$ | V3 示意分 |
|---|---:|---:|---:|---:|---:|
| A 真实运行 | 26.33x | 0.939 | 56.11x | 0.110 | **38.29** |
| B 面积高效 | 10.23x | 0.874 | 2.06x | 0.629 | **73.75** |
| C 均衡 | 53.17x | 0.965 | 5.17x | 0.449 | **68.41** |
| D 极端展开 | 649.07x | 0.996 | 144.61x | 0.055 | **30.09** |


排序为 **B > C > A > D**。A 的 27x 改善仍被完整识别，但 84.5x LUT、582.7x FF、32x DSP 使增广资源增长达到约 56x，因此不应仍保持 70 分以上。D 的性能极高，但资源瓶颈更严重，仍最低。

### 18.3 `residual_stream_deadlock`

暂按 $N=1$，baseline 135 cycles，hidden cosim 97 cycles，LUT 539→406、FF 248→231，66/80 credits：

```text
q_perf ≈ 0.569
q_area ≈ 0.757
E = 1 - 0.1*(66/80) = 0.9175
Score ≈ 58.48
```

该分低于 V2 的 73.88，主要因为 V3 删除 30% completion 基础分，且正式 QoR 更强调“相对 baseline 仅 1.39x”的性能事实。若该任务本质是 deadlock repair 而非 optimize，应把 performance/resource policy 冻结为 preserve；则成功修复且不回归可获得更高分。**任务 policy 的定义比事后调权重更重要。**

---

## 19. Benchmark manifest 建议

```toml
[scoring]
version = "v3.0"
profile = "optimize"
requires_cosim = false
w_performance = 0.60
w_area = 0.40

[scoring.performance]
policy = "improve"
good_ratio = 8.0
quality_at_baseline = 0.50
quality_at_good_ratio = 0.85

[[scoring.workload_cases]]
name = "single"
transactions = 1
weight = 0.25

[[scoring.workload_cases]]
name = "stream16"
transactions = 16
weight = 0.75

[scoring.resources]
policy = "improve"
bottleneck_weight = 0.35
bad_growth = 16.0
quality_at_same = 0.75
quality_at_bad_growth = 0.25
weights = { LUT=0.20, FF=0.20, DSP=0.20, BRAM_18K=0.20, URAM=0.20 }

[scoring.efficiency]
lambda_cost = 0.10
lambda_time = 0.10
minimum_factor = 0.80
```

正式 evaluator 必须记录该节的 hash；提交包中的同名配置不能覆盖它。

---

## 20. 实施路线

### Phase 0：规范与任务语义冻结

- 逐任务确认 `improve/preserve/target`；
- 冻结 workload transaction 数与 case 权重；
- 建立可信 anchor/reference reports；
- 冻结 evaluator config、schema 和哈希策略。

### Phase 1：纯数学内核

实现无 I/O helper：

```text
ratio_utility()
preserve_utility()
workload_time()
performance_quality()
augmented_resource_growth()
device_headroom()
hardware_qor()
efficiency_factor()
combine_score()
```

所有 AC-06 至 AC-16 可用 property-based tests 验证，不依赖 Vitis。

### Phase 2：可信证据与 scorecard

- evaluator 侧收集成本和 runtime；
- hidden tool evidence 带 provenance；
- 所有原始字段、单位、选择路径、config hash 写入 schema v3；
- infrastructure failure 与 design failure 使用不同状态机。

### Phase 3：pilot 校准

- 运行多 agent、多 seed；
- 生成 Pareto 图、敏感性矩阵和排序翻转测试；
- 调整锚点，不根据参赛队伍身份或最终隐藏成绩调整。

### Phase 4：V2/V3 shadow scoring

一个 benchmark 版本同时计算 V2 与 V3：

- 主榜仍读旧版；
- 比较 invalid rate、缺失字段率、task-type 排序和 top-k 翻转；
- 公开 V3 配置和示例 scorecard；
- 下一个 major version 切换。

---

## 21. 最终建议

V3 的核心不是把 V2 的 30/30/28/8/4 换成另一组数字，而是建立以下不可破坏的结构：

```text
valid artifact
    -> workload-based hardware QoR
    -> bounded agent-efficiency deduction
    -> correctness-first leaderboard aggregation
    -> statistical uncertainty report
```

最重要的四项落地优先级：

1. 正式榜中 synth/co-sim/implementation 失败全部归零；
2. 用 workload time 合并 latency 与 II；
3. 用“平均资源变化 + 最坏资源瓶颈”替代简单资源几何平均；
4. 把所有参数从 submission environment 移到带 hash 的 evaluator config。

完成这四项后，评分公式才具备接近正式竞赛规则所需的有效性、公平性、可解释性和反刷分能力。

---

## 参考资料

- **[R1] FPL 2026 Agentic FPGA Backend Optimization Competition — Scoring Criteria.** Official competition rule. Validity failure gives zero; benchmark quality is reduced by OpenRouter cost and wall-clock runtime; per-benchmark ranking is aggregated. https://xilinx.github.io/fpl26_optimization_contest/score.html
- **[R2] FPL 2026 Scorecard Reference.** Official scorecard schema. Every gating check and score input is exposed; validator version, hashes, raw timing, cost and runtime are recorded. https://xilinx.github.io/fpl26_optimization_contest/scorecard.html
- **[R3] FPL 2026 Runtime Environment and Benchmark Details.** Official evaluation environment. Fixed hardware/software environment, one-hour per-benchmark limit, best-so-far output, and hidden benchmarks reduce brute-force and overfitting. https://xilinx.github.io/fpl26_optimization_contest/runtime.html
- **[R4] AMD Vitis HLS User Guide UG1399 — Process Overview.** Vendor official documentation. HLS QoR analysis jointly examines latency, initiation interval, throughput and resource utilization, followed by C/RTL co-simulation. https://docs.amd.com/r/2021.2-English/ug1399-vitis-hls/Vitis-HLS-Process-Overview?contentId=90fNT5GfJL_MFNiMc01UDg
- **[R5] AMD Vitis HLS UG1399 — Performance Metrics Example.** Vendor official documentation. Defines latency and II as different timing concepts: latency to complete a transaction and II before a new transaction can start. https://docs.amd.com/r/2021.2-English/ug1399-vitis-hls/Performance-Metrics-Example?contentId=0VR3GDjUzgfdy5y_xKV27w
- **[R6] HLS-Eval: A Benchmark and Framework for Evaluating LLMs on HLS Design Tasks.** Peer-reviewed / primary benchmark. Uses progressive parseability, compilability, runnability and synthesizability metrics and reports pass@k. https://arxiv.org/abs/2504.12268
- **[R7] RTLLM: An Open-Source Benchmark for Design RTL Generation with LLMs.** Peer-reviewed / primary benchmark. Separates syntax, functionality and design quality as progressive goals. https://arxiv.org/abs/2308.05345
- **[R8] VerilogEval: Evaluating LLMs for Verilog Code Generation.** Peer-reviewed / primary benchmark. Functional correctness is determined by automated testbench execution and comparison with a golden implementation. https://arxiv.org/abs/2309.07544
- **[R9] HLStrans: Dataset for C-to-HLS Hardware Code Synthesis.** Primary benchmark preprint. Pairs testbenches with synthesis-based latency and resource annotations. https://arxiv.org/abs/2507.04315
- **[R10] Bench4HLS: End-to-End Evaluation of LLMs in HLS Code Generation.** Primary benchmark preprint. Combines compilation, functional simulation, synthesis feasibility and pluggable PPA analysis across HLS toolchains. https://arxiv.org/abs/2601.19941
- **[R11] Chimera: Multi-Objective DSE for FPGA HLS.** Peer-reviewed / primary research. Treats latency/resource exploration as a Pareto-front problem and demonstrates useful elbow-point tradeoffs. https://arxiv.org/abs/2207.07917
- **[R12] Practical Design Space Exploration / HyperMapper 2.0.** Peer-reviewed / primary research. Handles feasibility-constrained multi-objective hardware DSE and evaluates Pareto fronts with hypervolume. https://arxiv.org/abs/1810.05236
- **[R13] IronMan: GNN-assisted HLS Design Space Exploration.** Peer-reviewed / primary research. Targets flexible Pareto solutions across resources, area and latency under constraints. https://arxiv.org/abs/2102.08138
- **[R14] The Hypervolume Indicator: Problems and Algorithms.** Survey / primary theory. Hypervolume is a set-quality indicator with strict monotonicity under set dominance; appropriate for evaluating a set of designs, not a single submitted artifact. https://arxiv.org/abs/2005.00515
- **[R15] ISPD 2017 Clock-Aware FPGA Placement Contest — Evaluation Criteria.** Official competition rule. Requires legal/routable outputs, assigns failed jobs the lowest rank, and applies only a bounded runtime factor to quality. https://www.ispd.cc/contests/17/evaluation.html
- **[R16] SPEC CPU 2017 Overview.** Official benchmark methodology. Uses reference-machine ratios, repeated runs and geometric mean aggregation; stresses correctness, reproducibility, comparability and explicit run rules. https://www.spec.org/cpu2017/Docs/overview.html
- **[R17] Competitions in AI — Robustly Ranking Solvers Using Statistical Resampling.** Peer-reviewed / primary methodology. Shows rankings can be unstable to benchmark sampling and proposes bootstrap confidence intervals and statistically robust tied groups. https://arxiv.org/abs/2308.05062
- **[R18] Agent Factories for High Level Synthesis.** Primary 2026 agent study. Demonstrates that scaling agent search increases HLS performance, reinforcing the need to measure cost/runtime rather than penalize raw attempt count twice. https://arxiv.org/abs/2603.25719
- **[R19] AgRefactor: Self-Evolving Agentic Workflow for HLS Compatibility and Performance.** Primary 2026 agent study. Reports synthesizability, performance gain, resource overhead and agent cost/scalability as distinct outcomes. https://arxiv.org/abs/2606.30949
