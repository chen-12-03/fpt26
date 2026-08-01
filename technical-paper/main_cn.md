# 面向预算受限的大语言模型辅助高层次综合的验证候选循环

**匿名投稿**

---

## 摘要

高层次综合（HLS）代理必须在有限的模型和工具预算内修复和优化不熟悉的内核。验证候选循环（Verified-Candidate Loop, VCL）让验证证据控制候选晋升。其质量结果（QoR）分数结合有效延迟和最坏资源增长。QoR 引导的检索增强生成（QoR-RAG）复用兼容证据，失败反思（Failure Reflection）将工具诊断转化为下一轮约束。我们在均衡的 150 任务套件上评估三个托管大语言模型端点，并用定向补跑记录替换受 API 故障影响的原始记录。DeepSeek V4 Pro 和 Qwen3.5-122B-A10B 分别完成 \DeepSeekSuccessCount{} 和 \QwenThreeFiveSuccessCount{} 个任务。Qwen3.5 在 \QwenThreeFiveScoredTaskCount{} 个有分任务上取得最高总分；DeepSeek 在 \DeepSeekScoredTaskCount{} 个有分任务上的条件均分最高。定向补跑后，Qwen3.6 达到 \QwenThreeSixSuccessCount{}/\CorpusTaskCount{}（\QwenThreeSixSuccessRate{}）的完成率，但仅 \QwenThreeSixScoredTaskCount{} 个任务具有评估器分数。评分子集不一致以及残余 provider 故障，使这些端点差异无法单独归因于模型权重。

**关键词：** 高层次综合，LLM 代理，FPGA，检索增强生成，质量结果

---

## 1. 证据必须控制 LLM 编辑

大语言模型（LLM）代理可以编辑不熟悉的高层次综合（HLS）内核，但只有工具报告能够认证正确性和硬件质量。受预算约束的代理因此需要一个候选晋升规则：任何必需验证门控失败时，该规则保留已验证的回退方案 [1]。

已有 HLS 代理自动执行代码转换、指令搜索和反馈驱动修复 [2–4]，通用工具代理也会交替执行推理和操作 [5]。VCL 在明确的模型和工具预算下，将候选晋升权交给确定性的 HLS 证据。

我们的验证候选循环（VCL）贡献了三项成果和发现：

**(1) 验证合约。** 一个故障关闭（fail-closed）的工作流在七项门控中保留已验证的回退基线：接口（Interface）、C 仿真（CSim）、HLS 综合（Synth）、频率（Frequency）、容量（Capacity）、必需的 C/RTL 协同仿真（CoSim）和指标完整性（Metric completeness）。

**(2) 硬件目标。** 有界分数 Q_HW 拒绝那些在时钟频率或最坏资源质量上的损失超过其延迟收益的加速。

**(3) 端点评估。** 第 4 节将三个托管端点的任务完成与评分覆盖分开比较。DeepSeek 的完成覆盖最高；Qwen3.5 的有分任务集合最大且总分最高；Qwen3.6 仍存在结构修复缺口。评分子集不一致以及残余 provider 故障，使这些端点差异无法单独归因于模型权重。

---

## 2. 工具证据控制代理工作流

任务接口公开可编辑内核、公开测试、目标器件和预算，同时隐藏测试和冻结参考实现。控制器在同一运行状态中记录每个候选、门控、指标、token 和信用。

VCL 按固定顺序运行七项门控：Interface、CSim、Synth、Frequency、Capacity、必需的 CoSim 和 Metric completeness。Frequency 强制至少 100 MHz，Capacity 强制满足 U55C 限制，CoSim 仅在任务要求时适用。对候选 c，以适用门控 G_i ∈ {0, 1} 定义有效性 V(c)，并将不适用的 CoSim 门控设为一：

```
V(c) = G_int · G_csim · G_syn · G_freq · G_cap · G_cosim · G_metric
```

设 b 表示已验证的回退基线。晋升规则为：

```
P(c) = V(c) ∧ [Q_HW(c) > Q_HW(b)]
```

预算准入为所有必需门控预留信用。门控失败或预算不足则保留 b。QoR-RAG 提供版本兼容的规则、成功案例和测量失败案例。失败反思将受限诊断转化为下一轮约束，无需额外 LLM 请求。重复候选和重复失败会停止重试。隐藏验收仍由评估方执行。

图 1 总结该循环。三次活动共记录 \CandidateEventCount{} 次候选接口检查、\CandidateInterfaceRejectCount{} 次接口拒绝、\CandidateSynthGateCount{} 次综合门控和 \CandidateCosimGateCount{} 次 CoSim 门控。这些计数确认合约得到执行，但不能隔离各机制的因果效果。

> **图 1：测量证据控制每一次状态转换。** 候选方案仅在所有适用门控通过且 Q_HW 改善后才替换已验证的回退方案。

---

## 3. 一个分数拒绝虚假加速

评估器选择一个有效的起始方案作为锚点 a，并在必要时回退到对代理隐藏的冻结参考实现。设 c 表示候选，L 为其周期延迟，p = max(p_target, p_estimated) 为其有效周期，II 为其启动间隔。仅当任务标记 II 为相关且两个值均为正时，分数才使用 II 分支：

```
r_L = (p_a · L_a) / (p_c · L_c)

r_P = { r_L^0.85 · (II_a / II_c)^0.15,   可靠的 II
      { r_L,                               仅延迟
```

对于锚点和候选的资源计数 A_j 和 C_j，设 R 包含查找表（LUT）、触发器（FF）、数字信号处理（DSP）块、块 RAM（BRAM）和 UltraRAM（URAM）。最坏资源增长定义面积质量：

```
R_+ = {j ∈ R : A_j > 1 ∨ C_j > 1}

Ř = { R_+,   若 R_+ ≠ ∅
    { R,     若 R_+ = ∅

r_A = [max_{j ∈ Ř} (max(C_j, 1) / max(A_j, 1))]^(-1)
```

评估器分数结合有效性、有界硬件效用和预算效率：

```
h = r_P^0.55 · r_A^0.45

Q_HW = 1 - 1 / (1 + h)²

E = max(0.80, 1 - 0.10 · u_credit - 0.10 · u_time)

S = 100 · V · Q_HW · E
```

其中两个 u 项表示消耗的信用和时间比例，截断到 [0, 1]。晋升仅在 V(c) = 1 之后比较 Q_HW，因此剩余预算永远不会将劣质设计变为回退基线。

---

## 4. 任务完成覆盖超过评分覆盖

### 实验协议

三个托管端点在同一代理版本和 \CampaignCreditLimit{} 信用限额下处理同一个均衡的 \CorpusTaskCount{} 任务套件。每个已完成输出必须按照 Track-A 合约通过 CSim、Synth、100 MHz、U55C 容量和所有适用 CoSim 门控 [8]。对于原始记录中出现失败 API 请求的任务，合并数据选择可用的定向补跑记录，并据此重新计算完成数。“有分”表示任务具有非空评估器分数；补跑并未为每个恢复完成的任务补齐分数。合并记录中三个端点分别保留 \DeepSeekApiFailures{}、\QwenThreeFiveApiFailures{} 和 \QwenThreeSixApiFailures{} 次失败请求。附录 A 给出任务来源，附录 C 给出分类结果与选中记录的核算明细。

| 端点 | 已完成 | 有分任务数 | 有分任务均分 | 总分 | API 失败请求 |
|------|-------|-----------|-------------|------|-------------|
| DeepSeek V4 Pro | 147/150 | 104 | 71.95 | 7483.07 | 1 |
| Qwen3.5-122B-A10B | 146/150 | 115 | 68.26 | 7850.21 | 0 |
| Qwen3.6-27B | 138/150 | 67 | 66.90 | 4482.31 | 4 |

### 结果

DeepSeek 的完成覆盖最广且最均衡：在 \CorpusTaskCount{} 个任务中完成 \DeepSeekSuccessCount{} 个，并在六类任务中均至少完成 24/25。Qwen3.5 只少完成一个任务，但其 \QwenThreeFiveScoredTaskCount{} 个有分任务构成最大的评分集合，并产生最高总分 \QwenThreeFiveScoreSum。DeepSeek 较高的有分任务均分 \DeepSeekScoredMean 仅适用于另一组 \DeepSeekScoredTaskCount{} 个任务，因此不能据此断言其在配对任务上的质量更高。

Qwen3.6 完成 \QwenThreeSixSuccessCount{} 个任务，其中编译修复、综合修复和 QoR 优化均达到 25/25。其剩余缺口主要集中在结构修复（18/25）和代码生成（21/25）。由于仅 \QwenThreeSixScoredTaskCount{} 个 Qwen3.6 任务具有评估器分数，其总分无法反映多数补跑后完成的任务。

评分子集不一致以及残余 provider 故障，使这些端点差异无法单独归因于模型权重。

---

## 5. 局限与后续工作

VCL 将验证证据和 Q_HW 确立为晋升权威。端点评估将任务完成覆盖与现有评分证据分开。评分子集不一致以及残余 provider 故障，使这些端点差异无法单独归因于模型权重。定向补跑降低了基础设施故障的混杂影响，但不能替代重复运行。匹配消融和更广泛的语料库仍需检验各机制的因果效果与迁移能力。

---

## 附录 A：基准来源与任务组成

接受的清单冻结了每个上游路径、提交、任务描述、公开测试、评估器专属隐藏测试、参考实现和门控配置。构建器拒绝了未通过验收检查的构建候选，保留了 \CorpusTaskCount{} 个任务，且不同类别间无内核重叠。表 A1 将六种能力分开，揭示了被聚合成功率掩盖的弱修复模式。

| 任务类型 | 初始条件 | 要求输出 | 任务数 | 需 CoSim |
|---------|---------|---------|-------|---------|
| 代码生成 | 仅有签名的存根 | 完整内核 | 25 | 否 |
| 编译修复 | 编译失败 | 可编译内核 | 25 | 否 |
| 综合修复 | 综合失败 | 可综合内核 | 25 | 否 |
| 功能修复 | CSim 失败 | 功能正确内核 | 25 | 否 |
| 结构修复 | CoSim 失败 | 可执行 RTL 结构 | 25 | 是 (25) |
| QoR 优化 | 有效基线 | 更好的有效 Q_HW | 25 | 否 |

内核来自两个公开的 AMD 仓库（均为固定提交）。入门示例贡献 \IntroExampleTaskCount{} 个任务（Apache-2.0 许可）；加速示例贡献 \AccelExampleTaskCount{} 个任务（MIT 许可）。受控故障定义了生成和修复条件，而冻结的有效起始方案或评估器专属参考实现锚定了 QoR 评估。150 个变体重用了 \UniqueSourcePathCount{} 个唯一的源文件路径。

源仓库为：
- https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- https://github.com/Xilinx/Vitis_Accel_Examples

| 仓库 | 许可证 | 上游 commit | 任务数 |
|------|--------|------------|-------|
| Xilinx/Vitis-HLS-Introductory-Examples | Apache-2.0 | `aa5c160faf5d5ebf58674df8f0591f9984ebae0f` | \IntroExampleTaskCount{} |
| Xilinx/Vitis_Accel_Examples | MIT | `81187602355a7c2b666351154c5acca2074cae64` | \AccelExampleTaskCount{} |

---

## 附录 B：Track-A 要求映射与适用范围

表 B1 区分运行时输出证据与提交包义务。“严格”指故障关闭的强制执行：适用门控的证据缺失会拒绝输出。严格执行允许不适用门控保持未执行。所有任务要求 CSim 和 Synth，而清单只对 \RequiredCosimTaskCount{} 个结构任务要求 CoSim。公开指南要求通过 CoSim，却未定义任务级豁免。本报告因此只声明结构任务的 CoSim 证据，不声明其余 125 个任务的 CoSim 覆盖；组织方确认或更广泛的运行证据仍需关闭这一提交要求。

| Track-A 要求 | 执行方式与记录证据 |
|-------------|-----------------|
| U55C；Vitis 2025.2 | 容器固定目标器件和工具版本；报告保留执行源代码版本 |
| CSim、Synth、适用 CoSim | 缺失或失败的必需门控拒绝候选方案。隐藏测试和冻结参考实现仅评估器使用 |
| 至少 100 MHz；可行的资源 | 频率和 U55C 容量门控先于晋升。报告保留延迟、II、周期、LUT、FF、DSP、BRAM 和 URAM |
| 预算与 token 核算 | 每份运行报告记录 token 和信用；结构化报告保留请求、工具和墙钟时间明细。活动限制为 \CampaignCreditLimit{} 信用 |
| 推荐的模型比较 | OpenRouter 活动覆盖 DeepSeek V4 Pro、Qwen3.5-122B-A10B 和 Qwen3.6-27B，使用同一清单和源代码版本。模拟、回放和脚本后端会触发结果生成器停止 |
| Docker 与可复现性 | 仓库提供 Docker 工作流、公开任务材料、结构化报告和结果生成脚本 |
| PDF、源码归档、视频 | 作者单独确认 IEEE 格式、两页边界、归档内容和五分钟演示作为打包义务 |

三个活动使用公开指南推荐的 checkpoint：DeepSeek V4 Pro、Qwen3.5-122B-A10B 和 Qwen3.6-27B。指南记录了其架构与量化方式；托管 provider 的实际构建仍不透明。

---

## 附录 C：详细的三端点结果

所有活动覆盖相同的 \CorpusTaskCount{} 个任务，共享一个源码哈希和信用限额。第 4 节报告任务完成、评分覆盖与条件评分。定向补跑提高了任务完成数，但没有为每个恢复完成的任务补齐评估器分数。每个任务在比较中只保留一条选定记录。

表 C1 合并分类完成率与 25 个 QoR 优化任务的均分。QoR 均分使用正文公式（6）的评估器分数。

| 端点 | 生成 | 编译 | 综合 | 功能 | 结构 | QoR 已完成 | QoR 均分 |
|------|------|------|------|------|------|------------|----------|
| *(由 \CategorySuccessRows 生成)* | | | | | | | |

表 C2 报告选中任务记录中的 Token 与信用字段。Token 数以百万计。对于定向补跑任务，补跑 Token 替换原始 Token 值，而信用仍来自原始任务记录。因此这些行既不估计原始运行与补跑的累加消耗，也不支持端点成本效率比较。

| 端点 | 选中记录 Token（百万） | 原始记录信用 |
|------|------------------|------|
| *(由 \TokenAccountingRows 生成)* | | |

分类结果揭示了不同的剩余缺口。DeepSeek 在每类中均至少完成 24 个任务；Qwen3.5 的四个未完成任务集中在代码生成和功能修复；Qwen3.6 的编译、综合和 QoR 任务全部完成，但结构修复仅为 18/25。Qwen3.6 仅有 67 个有分任务，覆盖不到整个语料库的一半，因此基于分数的比较所描述的范围明显窄于基于完成数的比较。

**必需的消融实验。** 匹配的重新运行应每个代理变体添加一行，报告活动标识符、成功率、重复失败次数、平均 Q_HW、token、调用、信用和墙钟时间。计划中的变体包括：完整代理、无 QoR-RAG、无测量失败检索、无失败反思。在有此类运行之前，我们不报告任何数值，也不声称任何因果改进。

---

## 附录 D：复现与结果刷新

接受的任务清单位于 `tasks/track_a_150/candidate_manifest.json`。三个源报告路径作为注释写在 `technical-paper/results_generated.tex` 的末尾。替换或扩展 `runs/` 下的匹配目录后，从仓库根目录执行：

```
python3 technical-paper/scripts/update_results.py
```

该脚本选择最新的匹配最终报告，并拒绝生成宏，除非模型身份、任务数量、API 客户端、执行源码哈希和信用限额一致。

生成的 TeX 文件提供任务计数、结果数值文本以及所有详细表格行。刷新活动可更新数值证据而无需手动编辑论文。评估器专属测试和参考实现保持在代理可见文件系统之外；报告写入器会脱敏凭证和敏感路径。

活动使用源码快照 \ExecutionSourceHash、温度 0、4096 token 输出限制、180 秒请求超时，以及首次请求后最多两次重试。OpenRouter 标识所请求的开放权重模型和许可证映射。不透明的提供商构建保持未冻结状态。运行目录名称保留活动时间戳。

---

*本文档为主文件 `main.tex` 及其全部引用章节的中文翻译，忠实对应原文结构。其中 `\XXX{}` 形式的占位符对应 `results_generated.tex` 中自动生成的宏值，在实际 PDF 编译时会被替换为具体数字。*
