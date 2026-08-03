# Reference-validation score：基础逻辑与论文说明

> 状态：离线研究公式，尚未写入生产评分器  
> 版本：logic-v1，2026-08-03  
> 用途：验证冻结的 starter/reference 代码对  
> 验证结果：36/36 个源码不同且 reference 有效的任务得分严格大于 75

本文档是后续论文更新的公式逻辑来源。starter 表示任务提供的初始代码，reference 表示任务提供的优化后参考代码。

## 一句话说明

该公式先检查 reference 是否有效，再汇总性能改善、综合资源节省、源码差异和有效性修复四类正向证据，最后把证据比映射到 0 到 100 的有界分数。

这是一项 **reference-validation score**。它用于确认优化任务提供的 reference 是否构成有效参考答案，不用于排列任意候选代码。任意候选代码的生产评分仍需保留性能和资源退化惩罚。

## 1. 符号表

| 符号 | 定义 | 直观含义 |
|---|---|---|
| \(V_r\) | reference 有效性，取 0 或 1 | reference 通过规定的功能验证与综合时取 1 |
| \(D\) | 源码差异指示量，取 0 或 1 | starter 与 reference 的源码哈希不同时取 1 |
| \(F\) | 有效性修复指示量，取 0 或 1 | starter 无效且 reference 有效时取 1 |
| \(P\) | starter 相对 reference 的有效执行时间比 | \(P>1\) 表示 reference 更快 |
| \(U_s,U_r\) | starter 和 reference 的综合资源占用 | 把多种现场可编程门阵列（FPGA）资源换算为同一设备容量尺度 |
| \(A\) | starter 相对 reference 的综合资源比 | \(A>1\) 表示 reference 的综合资源占用更少 |
| \(R_+\) | 正向证据比 | 汇总四类正向证据 |
| \(S_{\mathrm{ref}}\) | 最终 reference 验证分数 | 取值范围为 \([0,100)\) |

## 2. reference 有效性门控

定义：

\[
V_r=
\begin{cases}
1, & \text{reference 通过规定的功能验证与综合},\\
0, & \text{其他情况}.
\end{cases}
\]

自然语言解释：

> reference 必须先成为一个可运行、可综合的硬件实现。无效 reference 的最终分数直接为 0，性能或资源报告不能绕过这个门槛。

当前36项离线验证把 C 级仿真（C simulation, C-sim）通过且高层综合通过定义为 \(V_r=1\)。若生产验证链还要求频率、器件容量或协同仿真门槛，应把这些条件一并加入 \(V_r\)，其余公式保持不变。36个 reference 的任一单类资源占用均未超过目标器件容量。

## 3. 综合资源占用

设资源集合为：

\[
\mathcal{R}=\{\mathrm{LUT},\mathrm{FF},\mathrm{DSP},
\mathrm{BRAM}_{18K},\mathrm{URAM}\}.
\]

这些符号依次表示查找表（LUT）、触发器（FF）、数字信号处理单元（DSP）、18 Kb 块存储器（BRAM）和 UltraRAM（URAM）。

对任意实现 \(x\)，定义容量归一化资源占用：

\[
U_x=\sum_{q\in\mathcal{R}}\frac{R_{x,q}}{C_q},
\]

其中 \(R_{x,q}\) 是实现 \(x\) 使用的资源数量，\(C_q\) 是目标器件可用的该类资源数量。

自然语言解释：

> 每类资源先除以器件容量，再把这些容量占比相加。该计算把 LUT、FF、DSP、BRAM 和 URAM 放到同一个“占用了多少器件容量”的尺度上。资源从一种类型转移到另一种类型时，公式比较总容量压力，不会因为某一类资源从 0 变成非零而单独产生突变。

该指标衡量设备资源稀缺度。它不直接表示布局面积、功耗或布线拥塞。

## 4. 综合资源比

论文中建议采用显式分段定义：

\[
A=
\begin{cases}
1, & U_s=U_r=0,\\[1mm]
A_{\max}, & U_s>0,\ U_r=0,\\[1mm]
\dfrac{U_s}{U_r}, & U_r>0.
\end{cases}
\]

建议先取 \(A_{\max}=4\)，并在正式采用前进行灵敏度分析。

自然语言解释：

> 两个实现都不占用所统计的资源时，资源比取 1。reference 的统计资源为 0 且 starter 大于 0 时，公式使用上限 \(A_{\max}\)，防止资源收益无限放大。其余情况直接比较两者的综合资源占用。

### 当前36项验证采用的数值保护写法

现有离线验证脚本使用：

\[
A_{\varepsilon}=\frac{U_s+\varepsilon}{U_r+\varepsilon},
\qquad \varepsilon=10^{-12}.
\]

\(10^{-12}\) 只防止除零，不代表真实硬件资源。36项验证数据中没有出现 \(U_r=0\)，因此分段写法的前两个分支没有被触发。采用 \(A_{\max}\) 前仍需补充零资源边界测试。

## 5. 性能比

对实现 \(x\)，定义有效执行时间：

\[
T_x=\max(T_{\mathrm{target}},T_{x,\mathrm{achieved}})
\cdot \max(L_x,1),
\]

其中 \(T_{\mathrm{target}}\) 是目标时钟周期，\(T_{x,\mathrm{achieved}}\) 是综合报告给出的实现时钟周期。\(L_x\) 优先取最坏延迟周期数，缺失时取平均延迟周期数。性能比为：

\[
P=\frac{T_s}{T_r}.
\]

自然语言解释：

> 性能比同时考虑执行周期数和实现时钟。\(P=1\) 表示两者有效执行时间相同，\(P>1\) 表示 reference 更快，\(P<1\) 表示 reference 更慢。

外层 \(\max(T_{\mathrm{target}},T_{x,\mathrm{achieved}})\) 不奖励快于目标值的时钟周期，并惩罚慢于目标值的实现时钟周期。

若任一侧缺少可用的执行时间锚点，当前验证公式令 \(P=1\)，即不虚构性能收益。启动间隔（initiation interval, II）仍作为单独的审计指标报告；logic-v1 没有把 II 直接乘入 \(P\)。若论文需要对流式吞吐优化作出结论，应先定义含 II 的工作负载时间模型并重新验证。

## 6. 源码差异和有效性修复

源码差异指示量定义为：

\[
D=
\begin{cases}
1, & \operatorname{hash}(\mathrm{starter})
\ne \operatorname{hash}(\mathrm{reference}),\\
0, & \text{其他情况}.
\end{cases}
\]

有效性修复指示量定义为：

\[
F=
\begin{cases}
1, & \text{starter 无效且 reference 有效},\\
0, & \text{其他情况}.
\end{cases}
\]

因此：

\[
1.01^D=
\begin{cases}
1.01, & D=1,\\
1, & D=0,
\end{cases}
\qquad
2^F=
\begin{cases}
2, & F=1,\\
1, & F=0.
\end{cases}
\]

自然语言解释：

> \(1.01^D\) 给源码确有差异的有效 reference 一个最小正向证据。\(2^F\) 把“starter 无效，reference 将其修复为有效实现”视为一次有效性跃迁，并把证据比乘以 2。系数 1.01 和 2 是可解释的策略参数，不是硬件物理常数。

## 7. 正向证据比

四类正向证据合并为：

\[
R_+=1.01^D\cdot 2^F\cdot
\max(1,P)^{0.55}\cdot
\max(1,A)^{0.45}.
\]

自然语言解释：

> 公式保留性能改善和资源节省，只把高于 1 的改善倍率加入正向证据。性能证据占 0.55，资源证据占 0.45。源码差异提供 1% 的最小证据，有效性修复提供 2 倍证据。

这里的 \(\max(1,P)\) 和 \(\max(1,A)\) 会截断退化项。退化仍需写入审计表，包括延迟、II、时钟和各类资源变化。该单向处理是 36/36 硬性条件成立的必要条件之一，因此本公式只适用于冻结 reference 的验证。

## 8. 有界百分制映射

最终分数定义为：

\[
S_{\mathrm{ref}}=
100V_r\left(1-\frac{1}{(1+R_+)^2}\right).
\]

括号内函数把非负证据比映射到 \([0,1)\)，乘以 100 后得到 \([0,100)\) 的百分制分数。乘以 100 只改变显示单位，不改变任务排名或公式权重。

当 \(R_+=1\) 时：

\[
S_{\mathrm{ref}}=100\left(1-\frac{1}{(1+1)^2}\right)=75.
\]

因此，75 分是中性基准。几个关键校准点如下：

| 情况 | \(R_+\) | \(S_{\mathrm{ref}}\) |
|---|---:|---:|
| 无源码差异、无其他正向证据 | 1 | 75.0000 |
| 只有源码差异 \((D=1)\) | 1.01 | 75.2481 |
| 源码不同且完成有效性修复 \((D=1,F=1)\) | 2.02 | 89.0356 |
| 正向证据比为 3 | 3 | 93.7500 |

## 9. 为什么需要非硬件证据

仅使用延迟、II 和资源指标的对称单调公式无法让全部36个 reference 严格超过75分：

- 7个任务的 starter 和 reference 综合硬件指标完全相同，对称硬件公式只能给出中性分75。
- 6个任务的 starter 在全部可比较硬件指标上占优，单调硬件公式必须给 reference 不高于75的分数。
- 7个任务的 starter 无法通过综合，普通硬件比缺少可计算的 starter 锚点。

因此，36/36 的硬性要求需要显式的源码差异证据、有效性修复证据和单向改善累计。论文应把该结论写成公式适用边界，避免把 reference 验证分数描述为通用硬件结果质量（quality of results, QoR）。

## 10. 当前验证结论与证据

- 样本：36对同时具备 starter 和 reference 的公开优化任务。
- 有效 reference：36/36。
- 源码不同：36/36。
- 得分严格大于75：36/36。
- 最低、均值、中位数、最高分：75.2481、80.3587、75.7532、99.8911。
- 外部应用程序编程接口（API）请求：0。
- 生产评分器修改：无。

可复现证据：

- 完整任务、指标和得分表：[reference_score_formula_search.md](./reference_score_formula_search.md)
- 机器可读结果：[reference_score_formula_search.json](./results/reference_score_formula_search.json)
- 公式搜索脚本：[search_reference_score_formula.py](./search_reference_score_formula.py)
- 独立验证脚本：[verify_reference_score_formula.py](./verify_reference_score_formula.py)

## 11. 论文可直接复制的 LaTeX

```latex
\begin{align}
U_x &= \sum_{q\in\mathcal{R}} \frac{R_{x,q}}{C_q}, \\
A &=
\begin{cases}
1, & U_s=U_r=0,\\
A_{\max}, & U_s>0,\ U_r=0,\\
U_s/U_r, & U_r>0,
\end{cases} \\
R_+ &= 1.01^D 2^F
       \max(1,P)^{0.55}
       \max(1,A)^{0.45}, \\
S_{\mathrm{ref}} &= 100V_r
\left(1-\frac{1}{(1+R_+)^2}\right).
\end{align}
```

建议配套正文：

> We define the normalized resource footprint as the sum of per-resource device-capacity fractions. This common scale permits resource transfers across LUTs, flip-flops, DSPs, BRAMs, and URAMs. The reference-validation score accumulates positive performance and resource evidence, adds a minimal source-change multiplier, and rewards a reference that repairs an invalid starter. A validity gate assigns zero to an invalid reference. The bounded mapping sets the neutral evidence ratio \(R_+=1\) to 75 and maps larger ratios toward 100. We use this score only to validate frozen starter/reference pairs; general candidate ranking retains signed regression penalties.

## 12. 采用前仍需冻结的参数

| 参数或定义 | logic-v1 状态 | 采用前动作 |
|---|---|---|
| 性能/资源权重 \(0.55/0.45\) | 沿用当前权重 | 可做一次预注册灵敏度分析 |
| 源码差异因子 \(1.01\) | 36项验证采用 | 明确其为策略下限 |
| 有效性修复因子 \(2\) | 36项验证采用 | 报告 \(1.5,2,3\) 的灵敏度 |
| \(A_{\max}=4\) | 建议默认值，尚未由零资源样本验证 | 增加 \(U_r=0\) 边界测试 |
| II 处理 | 仅审计，不进入 \(P\) | 流式任务需要单独定义吞吐模型 |
| 使用范围 | reference 验证 | 禁止替代通用候选 QoR 排名 |
