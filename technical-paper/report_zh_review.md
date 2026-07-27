# 面向预算受限大语言模型辅助高层次综合的验证候选循环

> 本文件逐节对应当前 `main.tex`、`sections/*.tex` 与 `appendix.tex`，用于
> 中文审核，不作为最终提交文件。公式、图表位置和结论占位与英文稿保持一致；
> 最终实验数据尚未填入。

## 摘要

高层次综合（HLS）Agent 必须在有限的大语言模型（LLM）和工具预算内修复并
优化陌生 Kernel。本文提出验证候选循环（Verified-Candidate Loop，VCL）：
只有有序验证链及其结果有权决定候选提升。Agent 使用同时考虑有效延迟和最差
资源增长的结果质量（QoR）分数对门控有效的候选进行排序。QoR 引导的检索增强
生成（QoR-RAG）检索兼容规则、成功案例和实测失败案例；失败反思（Failure
Reflection）则把关键诊断信息和源代码变化转换为下一轮约束，且不增加 LLM
请求。Agent 记录每一道门控、工具调用和 Token 消耗，以支持可复现评测。

**关键词：** 高层次综合，LLM Agent，FPGA，检索增强生成，结果质量

## 一、证据必须控制 LLM 修改

HLS 工程师需要理解陌生的 C/C++ Kernel，修复功能与流式执行故障，并在有限
评测预算下优化硬件。Vitis HLS 只能通过仿真和综合报告揭示正确性与性能 [1]。
LLM 可以提出源代码修改，但其文本推理无法证明接口正确、寄存器传输级（RTL）
执行正确或硬件取舍合理。

已有 LLM 辅助 HLS 系统能够自动完成代码变换与设计空间探索 [2, 3]，通用
工具型 Agent 则交替执行模型推理和工具动作 [4]。计量式 HLS 循环还需要明确
的候选提升规则。未经完整检查的修改可能通过编译，却在隐藏测试中失败、在
RTL 中死锁、无法达到 100 MHz，或以不成比例的资源增长换取速度。局部验证
还可能耗尽后续恢复所需的 Credit。

我们把这种证据控制的提升机制称为 VCL。本文围绕三项主张展开：

1. **有效性保持：** 验证链阻止未通过任一当前可用必要门控的候选替换已验证
   回退方案；
2. **QoR 对齐：** 有界硬件质量分数 \(Q_{\mathrm{HW}}\) 拒绝因时钟恶化或
   最差资源增长而得不偿失的表面加速；
3. **证据复用：** QoR-RAG 与失败反思让后续迭代聚焦于兼容动作和既有失败。

第五节将每项主张映射到独立实验；最终版本再填入实测结果。

## 二、VCL 保留已验证回退方案

VCL 将候选生成、验证和提升分开。任务预检记录可编辑 Kernel、公开测试、
完全一致的顶层函数签名、目标器件及预算。LLM 每轮提出一个完整源代码候选。
验证链首先执行接口门控，检查必要头文件、函数签名、平衡的源代码结构及禁止
依赖。

其余门控依次运行 C 仿真（CSim）、HLS 综合（Synth）、100 MHz 频率检查、
U55C 容量检查和必要的 C/RTL 协同仿真（CoSim）。指标完整性门控要求综合
报告包含延迟、时钟及五类资源计数。令适用门控 \(G_i\in\{0,1\}\)，不适用
的协同仿真门控取 1，则候选有效性为

\[
V(c)=G_{\mathrm{int}}G_{\mathrm{csim}}G_{\mathrm{syn}}
G_{\mathrm{freq}}G_{\mathrm{cap}}G_{\mathrm{cosim}}G_{\mathrm{metric}}.
\]

令 \(b\) 表示已验证回退方案，提升规则为

\[
P(c)=V(c)\land[Q_{\mathrm{HW}}(c)>Q_{\mathrm{HW}}(b)].
\]

功能或综合失败进入常规修复路径。协同仿真失败进入结构修复路径，其提示词
针对生产者交错写入、有界 Stream 深度及生产者与消费者速率平衡。在运行候选
工具前，预算准入要求剩余 Credit 足以完成 CSim、Synth 和必要 CoSim。任何
门控失败或预算拒绝都会保留 \(b\)，即最后一个通过全部当前可用必要门控的
Kernel。隐藏测试验收仍由外部评测器完成。

**[TODO-FIGURE：插入图设计说明中规定的 VCL 架构图。]**

**图注：** VCL 将候选提升权交给验证链和硬件质量规则。失败候选或预算无法
支撑完整验证的候选不能替换已验证回退方案。

## 三、QoR 拒绝表面加速

评测器侧的 Anchor 选择优先使用有效 Starter；若 Starter 无效，则使用冻结的
评测器侧 Reference。Agent 不会获得 Reference 源代码或测量值。令 \(L\)、
\(p\) 和 \(II\) 分别表示周期延迟、有效时钟周期和启动间隔，下标 \(a\) 与
\(c\) 分别表示 Anchor 和候选方案。有效时钟周期定义为

\[
p_x=\max(p_{\mathrm{target}},p_{\mathrm{estimated},x}).
\]

仅当任务声明 \(II\) 相关且 Anchor 与候选均报告正 \(II\) 时，性能比采用
加权 \(II\) 分支：

\[
r_L=\frac{p_aL_a}{p_cL_c},\qquad
r_P=
\begin{cases}
r_L^{0.85}(II_a/II_c)^{0.15}, & \text{具有可靠 }II,\\
r_L, & \text{仅使用延迟}.
\end{cases}
\]

令 \(A_j\) 与 \(C_j\) 分别表示 Anchor 和候选的资源计数，并定义

\[
\mathcal{R}=\{\mathrm{LUT},\mathrm{FF},\mathrm{DSP},
\mathrm{BRAM}_{18\mathrm{K}},\mathrm{URAM}\},
\]

\[
\mathcal{R}_{+}=\{j\in\mathcal{R}:A_j>1\lor C_j>1\},\qquad
\widehat{\mathcal{R}}=
\begin{cases}
\mathcal{R}_{+}, & \mathcal{R}_{+}\ne\varnothing,\\
\mathcal{R}, & \mathcal{R}_{+}=\varnothing.
\end{cases}
\]

面积比惩罚活动资源中增长比例最大的类别：

\[
r_A=\left[\max_{j\in\widehat{\mathcal{R}}}
\frac{\max(C_j,1)}{\max(A_j,1)}\right]^{-1}.
\]

加权硬件比、有界效用和官方总分定义为

\[
h=r_P^{0.55}r_A^{0.45},\qquad
Q_{\mathrm{HW}}=1-\frac{1}{(1+h)^2},
\]

\[
E=\max(0.80,1-0.10u_{\mathrm{credit}}-0.10u_{\mathrm{time}}),\qquad
S=100VQ_{\mathrm{HW}}E.
\]

\(u_{\mathrm{credit}}\) 与 \(u_{\mathrm{time}}\) 是截断到 \([0,1]\) 的已消耗
预算比例，\(E\) 是官方分数 \(S\) 中的有界预算项。候选提升在 \(V(c)=1\)
后只比较 \(Q_{\mathrm{HW}}\)，不比较 \(E\)。因此，当时钟恶化或最大资源增长
抵消周期收益时，系统会拒绝该候选。

## 四、证据复用聚焦每轮迭代

### A. QoR-RAG 检索兼容动作

QoR-RAG 按顺序使用源代码元数据、基线 QoR、综合诊断、资源余量、拒绝历史和
任务描述构建查询，并分别以 \(3,2,4,2,3,1\) 加权 Token 重合。关键词指示器
把查询映射到归约、存储端口、Dataflow、Stream 及因子分解类别。每次查询最多
返回一条整理后的规则、一个已验证成功案例和一个实测失败案例。实测案例必须
匹配目标器件与 Vitis 版本；工作负载门控使用任务描述和 AES、GEMM、Stencil、
Dot Product 等类别标签检查结构兼容性。来源检查拒绝路径中包含 Hidden、
Reference 或 Evaluator 组件的数据。检索上下文上限为 1,800 Token。

### B. 失败反思把错误转化为约束

失败反思提取下一轮真正需要的证据。它移除 ANSI 控制文本，对路径和密钥做
脱敏，删除重复行，并选取包含编译、结果不匹配、时序、Stream、死锁或超时
信号的有限诊断行。最终记录包括失败类别、候选 Diff、涉及的 Pragma、循环、
数组及下一轮约束。规范化签名用于统计重复失败模式。下一轮提示词和 QoR-RAG
查询共同使用该记录，因此失败反思不需要额外的 LLM 请求。

候选指纹会移除注释、规范化空白，并消除单语句 `for` 循环的可选花括号。
控制器在运行工具前用该指纹拒绝未变化或重复的候选，并在预算耗尽、候选重复
或搜索停滞时停止。

## 五、评测把每项主张映射到证据

### A. VCL 保持必要有效性

该实验审计每一个已提出候选、对应门控向量、相应提升决策及最终已验证回退
方案；若评测器返回隐藏测试结果，则单独报告外部隐藏验收。

**结论句占位：** 填入 VCL 阻止门控无效候选提升的实测比例。

### B. \(Q_{\mathrm{HW}}\) 选择硬件收益

该实验比较冻结 Anchor、已接受候选和被拒绝候选，并报告延迟、\(II\)、时钟、
五类资源及 \(Q_{\mathrm{HW}}\)。

**结论句占位：** 填入一个 \(Q_{\mathrm{HW}}\) 接受或拒绝名义周期收益的实测
案例。

### C. 证据复用减少重复失败

该实验比较完整 Agent 与移除 QoR-RAG、移除实测失败案例、移除失败反思的
变体，并报告成功率、重复失败数、LLM Token、工具调用、Credit 和耗时。

**结论句占位：** 填入重复失败和预算消耗的实测变化。

所有实验使用 Docker、Vitis 2025.2 和 Alveo U55C 目标平台。

**[TODO-TABLE：插入单栏结果表，包含验证、QoR 决策和证据复用消融三组行。]**

**表注：** 各组结果在相同任务和预算下分别对应一项论文主张。

## 六、证据控制候选提升

VCL 将 LLM 候选生成与验证链及 \(Q_{\mathrm{HW}}\) 提升规则绑定。QoR-RAG
提供兼容证据，失败反思则在不增加 LLM 请求的情况下生成下一轮约束。最终
评测将量化这些机制对有效性、硬件质量和预算消耗的影响。

---

# 附录

## 附录 A：实现契约

提交流水线在统一运行状态中保存候选方案、门控结果、最佳综合证据、已验证
回退方案、计量信息和终止状态。所有修复与优化路径都使用同一验证链和提升
规则。输出程序写出最近一个通过全部当前可用必要门控的 Kernel；失败和中断
路径返回已验证回退方案。

## 附录 B：实验配置

**[TODO-TABLE：插入最终容器、源码版本、开源模型、推理设置、任务预算和
Benchmark 配置。]**

**表注：** 最终实验集合的复现配置。

## 附录 C：逐任务证据

**[TODO-TABLE：插入逐任务门控、延迟、\(II\)、时钟、资源、
\(Q_{\mathrm{HW}}\)、状态和证据标识。]**

**表注：** 逐任务正确性和硬件证据。

## 附录 D：Token 与工具计量

**[TODO-TABLE：插入逐阶段 Prompt/Completion Token、LLM 请求、工具调用、
Credit 和耗时。]**

**表注：** 分阶段模型和工具计量。

## 附录 E：复现步骤

评测人员构建随附 Docker 镜像，通过环境变量配置开源模型端点，并挂载任务
和输出目录。命令行入口在指定输出根目录中写出最终 Kernel、结构化运行报告
和提交证据。Vitis 子进程环境不包含凭据，报告写入器会对敏感文本脱敏。

## 参考文献对应关系

[1] AMD, *Vitis High-Level Synthesis User Guide*, UG1399, Version 2025.2.

[2] C. Xiong, C. Liu, H. Li, and X. Li, “HLSPilot: LLM-based High-Level
Synthesis,” 2024.

[3] H. Xu, H. Hu, and S. Huang, “Optimizing High-Level Synthesis Designs
with Retrieval-Augmented Large Language Models,” ICCAD 2024.

[4] S. Yao et al., “ReAct: Synergizing Reasoning and Acting in Language
Models,” ICLR 2023.
