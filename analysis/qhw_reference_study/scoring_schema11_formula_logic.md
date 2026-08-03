# QHW Schema 11：评分公式基础逻辑（论文可引用版）

> 状态：实现已写入评分器；单元与回归测试通过；10 个真实 API/Vitis 任务验证完成  
> 版本：schema-11，2026-08-03  
> 对应实现：`fpt26-agent-v3/scoring/scoring_v3.py`  
> 真实实验：`analysis/schema11_ali_real10/results.md`  
> 适用对象：任意候选代码的生产评分；文末另列冻结 reference 的验证公式

## 一页版公式

令锚点实现为 \(b\)，候选实现为 \(c\)。锚点优先选有效 starter；starter 无效时使用有效 reference；两者都无效时拒绝评分，不允许候选代码与自身比较。

### 1. 有效性门控

\[
V=
\begin{cases}
1, & \text{候选通过全部规定的功能、接口、综合、容量及必要的协同仿真检查},\\
0, & \text{其他情况}.
\end{cases}
\]

任一硬门控失败，最终得分直接为 0。

### 2. 性能比

\[
T_x=\max(T_{\mathrm{target}},T_{x,\mathrm{achieved}})\max(L_x,1),
\qquad
P_L=\frac{T_b}{T_c}.
\]

若任务明确适用启动间隔（initiation interval, II），则

\[
P=P_L^{0.85}\left(\frac{II_b}{II_c}\right)^{0.15};
\]

否则 \(P=P_L\)。因此 \(P>1\) 表示候选性能更好，\(P<1\) 表示候选性能退化。

### 3. 综合资源占用与资源比

资源集合为

\[
\mathcal R=\{\mathrm{LUT},\mathrm{FF},\mathrm{DSP},
\mathrm{BRAM}_{18K},\mathrm{URAM}\}.
\]

对实现 \(x\)，定义容量归一化综合资源占用：

\[
U_x=\sum_{q\in\mathcal R}\frac{R_{x,q}}{C_q}.
\]

其中 \(R_{x,q}\) 是实现使用的第 \(q\) 类资源数，\(C_q\) 是目标器件可用的该类资源数。资源比采用显式分段定义：

\[
A=
\begin{cases}
1, & U_b=U_c=0,\\[1mm]
A_{\max}, & U_b>0,\ U_c=0,\\[1mm]
\dfrac{U_b}{U_c}, & U_c>0,
\end{cases}
\qquad A_{\max}=4.
\]

因此 \(A>1\) 表示候选综合资源占用更少，\(A<1\) 表示候选占用更多。该分段式完全取代 \(10^{-12}\) 的除零技巧，零资源边界不再产生人为的巨大倍率。

### 4. 源码变化与有效性修复

\[
D=
\begin{cases}
1, & \operatorname{hash}(c)\ne\operatorname{hash}(\mathrm{starter}),\\
0, & \text{其他情况},
\end{cases}
\]

\[
F=
\begin{cases}
1, & \text{starter 无效且候选有效},\\
0, & \text{其他情况}.
\end{cases}
\]

生产评分的综合证据比为

\[
R=1.01^D\cdot2^F\cdot P^{0.55}\cdot A^{0.45}.
\]

这里不使用 \(\max(1,P)\) 或 \(\max(1,A)\)，所以性能或资源退化会降低任意候选的生产得分。

### 5. 有界质量映射、效率与最终得分

\[
Q_{\mathrm{HW}}=1-\frac{1}{(1+R)^2}.
\]

定义成本和时间利用率

\[
u_{\mathrm{cost}}=
\operatorname{clip}\!\left(\frac{C_{\mathrm{spent}}}{C_{\mathrm{limit}}},0,1\right),
\qquad
u_{\mathrm{time}}=
\operatorname{clip}\!\left(\frac{t_{\mathrm{spent}}}{t_{\mathrm{limit}}},0,1\right),
\]

并定义效率因子

\[
E=\max\left(0.80,\ 1-0.10u_{\mathrm{cost}}-0.10u_{\mathrm{time}}\right).
\]

最终得分为

\[
\boxed{
S=100\,V\,E\left(1-\frac{1}{(1+R)^2}\right)
}
\]

## 自然语言解释

这套公式按五步工作：

1. **先判断候选是否有效。** 候选若不能正确运行、不能综合、接口违规、超过器件容量，或没有完成任务要求的协同仿真，得分直接为 0。
2. **再比较性能。** 用“实际时钟周期乘以延迟周期数”近似一次执行所需时间；吞吐型任务还纳入 II。候选越快，\(P\) 越大。
3. **把不同资源换到同一尺度。** LUT、FF、DSP、BRAM 和 URAM 分别除以器件容量，再相加为综合容量压力。这样，从 LUT 转移到 BRAM 或从 BRAM 转移到 URAM时，评分依据的是两种实现占用了多少器件份额，而不是某一项是否恰好从 0 变成非零。
4. **承认修复本身的价值。** 源码确有变化时乘以 1.01；无效 starter 被修复成有效候选时再乘以 2。但这两个系数不会屏蔽硬件退化，因为生产公式仍直接使用可能小于 1 的 \(P\) 和 \(A\)。
5. **映射到百分制并扣除过程成本。** \(R=1\) 映射为 75 分硬件质量；证据越强，分数越接近但不会达到 100。最后由效率因子按 API 成本和运行时间最多扣减 20%。

## 关键参数如何理解

### 为什么不再使用 \(10^{-12}\)

旧式写法

\[
\frac{U_b+10^{-12}}{U_c+10^{-12}}
\]

中的 \(10^{-12}\) 只是防止分母为零的数值垫片，不代表任何真实硬件资源。它会在 \(U_c=0\) 时制造极大倍率。Schema 11 用上面的三分支定义直接描述零资源情况，因此不需要这个数值技巧。

### \(2^F\) 是什么意思

因为 \(F\) 只能取 0 或 1：

\[
2^F=
\begin{cases}
2, & F=1,\\
1, & F=0.
\end{cases}
\]

也就是说，只有候选把无效 starter 修复为有效实现时，综合证据比才乘以 2；其他情况不变。2 是评分策略参数，不是硬件物理常数。

### 为什么最终乘以 100

\(V\)、\(E\) 和 \(Q_{\mathrm{HW}}\) 都是 0 到 1 之间的无量纲量。乘以 100 只是把小数显示为熟悉的百分制，不改变任务排序、相对差异或任何权重。

### 为什么性能和资源权重仍是 0.55/0.45

\[
P^{0.55}A^{0.45}
\]

是加权几何平均；两个指数相加为 1。0.55 表示性能略优先，0.45 表示资源几乎同等重要。综合资源定义的改变解决了资源类型转移问题，因此当前没有证据要求同时改动这两个权重。真实任务验证若显示系统性偏差，再单独做预注册的权重灵敏度分析。

## 生产评分与 reference 验证不能混用

对于冻结的 starter/reference 数据集，为检验“官方 reference 是否至少具有某类正向证据”，可使用单向验证式：

\[
R_+=1.01^D\cdot2^F\cdot
\max(1,P)^{0.55}\cdot\max(1,A)^{0.45}.
\]

它只累计正向证据，适用于 reference 验证；生产候选评分必须使用不截断退化项的 \(R\)。两者共用相同的资源定义、有效性定义和百分制映射，但回答的问题不同：

- \(R_+\)：官方 reference 是否具备可接受的正向证据；
- \(R\)：任意候选相对有效锚点的实际综合表现如何。

## 校准点

以下数值暂不含效率扣减，即令 \(E=1\)：

| 情况 | 综合证据比 \(R\) | 硬件质量分 |
|---|---:|---:|
| 候选与锚点相当，且源码未变 | 1.00 | 75.0000 |
| 仅确认源码发生变化 | 1.01 | 75.2481 |
| 源码变化且完成有效性修复 | 2.02 | 89.0356 |
| 综合证据比为 3 | 3.00 | 93.7500 |

注意：修复候选即使具有 \(2^F\) 奖励，若性能或资源严重退化，\(P^{0.55}A^{0.45}\) 仍会把 \(R\) 拉低，因此“修复成功”不自动保证生产最终分数大于 75。

## 论文可直接复制的 LaTeX

```latex
\begin{align}
U_x &= \sum_{q\in\mathcal R}\frac{R_{x,q}}{C_q}, \\
A &=
\begin{cases}
1, & U_b=U_c=0,\\
A_{\max}, & U_b>0,\ U_c=0,\\
U_b/U_c, & U_c>0,
\end{cases} \\
R &= 1.01^D 2^F P^{0.55} A^{0.45}, \\
Q_{\mathrm{HW}} &= 1-\frac{1}{(1+R)^2}, \\
E &= \max\!\left(0.80,
1-0.10u_{\mathrm{cost}}-0.10u_{\mathrm{time}}\right), \\
S &= 100VEQ_{\mathrm{HW}}.
\end{align}
```

建议配套正文：

> We normalize each resource count by the corresponding target-device capacity and sum the resulting fractions into a common resource-pressure measure. This definition allows resource transfers across LUTs, flip-flops, DSPs, BRAMs, and URAMs without a discontinuity caused solely by a zero-valued resource category. Production scoring retains signed performance and resource ratios, while a source-change factor records non-trivial edits and a validity-rescue factor recognizes transitions from an invalid starter to a valid candidate. A hard validity gate assigns zero to invalid candidates, and a bounded efficiency-adjusted mapping converts the combined evidence ratio to a 0--100 score.

## 当前适用边界

- 综合资源占用表示目标器件容量压力，不等同于芯片物理面积、功耗或布线拥塞。
- \(1.01\)、\(2\) 和 \(A_{\max}=4\) 是可审计的评分策略参数，需要随真实任务实验一并报告。
- II 只在任务明确适用且两侧指标完整时参与性能比。
- 正式评分禁止候选自锚定；starter 与 reference 都不能提供有效锚点时，任务不可评分。
- 当前参数已由 10 个真实 API/Vitis 任务做端到端工程验证；该目的抽样实验不证明参数对全部任务全局最优。
