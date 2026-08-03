# Schema 11 阿里云真实 API/Vitis 验证结果

## Material Passport

- Schema：ARS Material Passport 9
- 实验 ID：`schema11_ali_qwen3coder_real10_20260803`
- 执行状态：`COMPLETED`，10/10 task 完成，0 条审计错误
- 解释状态：`ANALYZED`；真实 API 具有随机性，未把逐 token 重放标记为确定性复现
- 模型与后端：阿里云 `qwen3-coder-plus`，`OpenAICompatClient`
- 工具链：Vitis HLS 2025.2，Build 6295257
- 任务集：冻结的 `tasks/track_a_150`，6 个 repair、4 个 QoR optimize
- 原始汇总：`runs/schema11_ali_qwen3coder_real10_20260803/shard_summary.json`
- 原始汇总 SHA-256：`23f99f51b5da80e4ee4fc555cc0e5d1d7abccc4f79eb058149647bc74f493445`
- 执行源：85 files，`tree_sha256=7fd2ef0c3340d53f12f7b6ca21c71c3511287ac7fabf019fed1057449ec8f74e`，运行前后稳定
- 预注册计划：`analysis/schema11_ali_real10/experiment_plan.md`

## 结论

Schema 11 已在不少于 10 个阿里云真实任务上投入使用并通过端到端验证。

1. **修复价值不再被原评分覆盖掉。** 6 个 repair 全部成功且全部超过 75 分；其同一候选、同一综合结果下的均分由旧式反事实重算的 78.25 提升到 90.67，平均增加 12.42 分。
2. **评分仍然保留硬件层级的差异。** `synthesis_repair__02` 虽获得修复证据，但资源综合占用增加，故资源比仍为 (A=0.7347<1)；修复奖励没有把资源退化截断或伪装成改进。
3. **容量归一化资源聚合能处理资源转移。** `qor_optimization__17` 的 LUT、FF、DSP 均明显下降而 BRAM 保持不变；旧“最差单项”方法因 BRAM 不变得到 (A_{old}=1)，新公式得到 (A=1.9493)，最终分由 75.73 提升到 82.67。
4. **不是所有任务都必须超过 75。** 4 个 optimize 中 3 个没有产生硬件改进，硬件质量基准为 75，再受实测效率因子轻微扣减，最终为 74.69--74.90。这是生产评分的预期行为，不应人为抬到 75 以上。

## 本次投入使用的公式

对有效锚点 (b) 与候选 (c)：

\[
U_x=\sum_{q\in\{LUT,FF,DSP,BRAM_{18K},URAM\}}
\frac{R_{x,q}}{C_q},
\]

\[
A=
\begin{cases}
1,&U_b=U_c=0,\\
4,&U_b>0,\ U_c=0,\\
U_b/U_c,&U_c>0,
\end{cases}
\]

\[
R=1.01^D\,2^F\,P^{0.55}A^{0.45},\qquad
S=100VE\left(1-\frac{1}{(1+R)^2}\right).
\]

其中 (D=1) 表示候选源码与 starter 不同，(F=1) 表示无效 starter 被有效候选修复。生产公式保留可能小于 1 的 (P) 与 (A)，因此性能或资源退化仍会降分。正式 evaluator 禁止候选自锚定：starter 有效时锚定 starter，否则锚定有效 reference；二者均不能提供有效锚点时得 0 分。

## 真实运行汇总

| 指标 | 结果 |
|---|---:|
| 选定 / 完成任务 | 10 / 10 |
| API 请求 | 23 |
| 总 tokens | 158,073 |
| 运行耗时 | 1,180.22 s（约 19 分 40 秒） |
| 审计错误 | 0 |
| 新公式总分 / 均分 | 851.10 / 85.11 |
| 旧公式反事实总分 / 均分 | 769.65 / 76.97 |
| repair 新均分 / 旧均分 | 90.67 / 78.25 |
| optimize 新均分 / 旧均分 | 76.78 / 75.04 |
| 新公式大于 75 | 7 / 10 |
| 旧公式大于 75 | 2 / 10 |

“旧公式”不是另一轮模型运行，而是在本轮完全相同候选、综合报告和效率因子上，使用 schema 10 的最差单资源增长逻辑进行反事实重算，用于隔离评分公式本身的影响。

## 逐任务评分

| # | Task（类别） | API / tokens | 锚点 | D/F | P | A（新） | 新分 | 旧分 | 差值 |
|---:|---|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | `compile_repair__14__amd_intro__interface_aggregation_disaggregation_disaggregation_of_axis_port`（repair） | 3 / 17,042 | reference | 1/1 | 1.0000 | 1.0000 | 88.95 | 74.92 | +14.03 |
| 2 | `compile_repair__16__amd_intro__interface_memory_burst_rw`（repair） | 2 / 12,609 | reference | 1/1 | 11.7964 | 1.0000 | 98.62 | 95.71 | +2.91 |
| 3 | `functional_repair__03__amd_intro__misc_malloc_removed`（repair） | 3 / 21,397 | reference | 1/1 | 1.0000 | 1.0000 | 88.95 | 74.92 | +14.03 |
| 4 | `functional_repair__06__amd_intro__modeling_conditional_control_of_pragmas_using_template_function`（repair） | 3 / 20,399 | reference | 1/1 | 1.0000 | 1.0000 | 88.94 | 74.92 | +14.02 |
| 5 | `qor_optimization__01__amd_intro__task_level_parallelism_control_driven_channels_simple_fifos`（optimize） | 2 / 13,891 | starter | 0/0 | 1.0000 | 1.0000 | 74.90 | 74.90 | 0.00 |
| 6 | `qor_optimization__07__amd_intro__interface_memory_aliasing_axi_master_ports`（optimize） | 2 / 16,689 | starter | 0/0 | 1.0000 | 1.0000 | 74.69 | 74.69 | 0.00 |
| 7 | `qor_optimization__08__amd_intro__modeling_free_running_kernel_remerge_ii4to1`（optimize） | 2 / 12,893 | starter | 0/0 | 1.0000 | 1.0000 | 74.85 | 74.84 | +0.01¹ |
| 8 | `qor_optimization__17__amd_intro__array_array_partition_block_cyclic`（optimize） | 1 / 9,169 | starter | 1/0 | 1.0644 | 1.9493 | 82.67 | 75.73 | +6.94 |
| 9 | `synthesis_repair__01__amd_intro__interface_memory_ecc_flags`（repair） | 3 / 19,657 | reference | 1/1 | 1.0000 | 1.0000 | 88.93 | 74.91 | +14.02 |
| 10 | `synthesis_repair__02__amd_intro__interface_memory_lmem_2rw`（repair） | 2 / 14,327 | reference | 1/1 | 1.4005 | 0.7347 | 89.60 | 74.11 | +15.49 |

¹ `qor_optimization__08` 的公式在 (D=F=0,P=A=1) 时实质相同；0.01 来自用报告中的四舍五入中间量重算旧分，不代表评分逻辑变化。

## 逐任务 Vitis 关键硬件指标

资源列顺序统一为 `LUT / FF / DSP / BRAM_18K / URAM`。repair 的锚点为 evaluator-only reference，optimize 的锚点为 starter。

| # | 锚点 latency / II / clock(ns) | 候选 latency / II / clock(ns) | 锚点资源 | 候选资源 | (U_b\rightarrow U_c) |
|---:|---|---|---|---|---|
| 1 | 12 / 10 / 1.482 | 12 / 10 / 1.482 | 106 / 8 / 0 / 0 / 0 | 106 / 8 / 0 / 0 / 0 | 0.00008438 → 0.00008438 |
| 2 | 50,689 / 50,690 / 3.650 | 4,297 / 4,298 / 3.650 | 1,898 / 1,472 / 0 / 10 / 0 | 同左 | 0.00450059 → 0.00450059 |
| 3 | 70 / 71 / 2.018 | 70 / 71 / 2.018 | 349 / 130 / 0 / 0 / 0 | 同左 | 0.00031756 → 0.00031756 |
| 4 | 17 / 18 / 1.579 | 17 / 18 / 1.579 | 628 / 88 / 0 / 0 / 0 | 同左 | 0.00051546 → 0.00051546 |
| 5 | 311 / 312 / 1.843 | 311 / 312 / 1.843 | 564 / 110 / 0 / 0 / 0 | 同左 | 0.00047481 → 0.00047481 |
| 6 | 2,088 / 2,089 / 3.650 | 2,088 / 2,089 / 3.650 | 1,843 / 1,511 / 0 / 9 / 0 | 同左 | 0.00422535 → 0.00422535 |
| 7 | 136 / 137 / 2.864 | 136 / 137 / 2.864 | 707 / 141 / 0 / 0 / 0 | 同左 | 0.00059639 → 0.00059639 |
| 8 | 1,140 / 1,141 / 3.650 | 1,071 / 1,072 / 3.650 | 13,864 / 11,434 / 131 / 2 / 0 | 7,548 / 5,578 / 63 / 2 / 0 | 0.03003267 → 0.01540651 |
| 9 | 115 / 116 / 3.415 | 115 / 116 / 3.415 | 4,159 / 5,203 / 3 / 0 / 2 | 同左 | 0.00760149 → 0.00760149 |
| 10 | 14,505 / 14,506 / 3.650 | 10,357 / 10,358 / 3.650 | 2,627 / 1,728 / 0 / 7 / 0 | 3,845 / 2,802 / 0 / 8 / 0 | 0.00441392 → 0.00600812 |

## 验收判断

- **改评分规则：通过。** 权威实现为 schema 11；资源采用容量归一化综合占用，加入可审计的 (D/F)，生产评分保留有符号的性能与资源比，并禁止正式评分候选自锚定。
- **不少于 10 个阿里云真实 task：通过。** 10/10 完成；每个任务均有最终分、API 请求统计、候选运行记录以及 evaluator 的 Vitis 综合复核。
- **修复类原逻辑：通过。** starter 无效时不再让候选覆盖原锚点，而是使用 evaluator-only reference；修复本身由 (F) 记录，硬件优劣仍由 (P/A) 独立决定。

## 统计解释与 11/11 谬误检查

本实验是预先固定任务与命令后的描述性工程验证，不计算 p 值、置信区间或人群效应量，也不把 10 个目的抽样任务外推为整个任务分布。结论置信级别为 **CAUTION**：端到端证据充分，但样本量小、类别不均衡且模型输出具有随机性。

| 检查项 | 结论 |
|---|---|
| 1 Simpson's paradox | 未发现方向反转；已分别报告 repair 与 optimize，避免只看总均值。 |
| 2 Ecological fallacy | 未从类别均值推断单个任务；逐任务结果完整列出。 |
| 3 Berkson's paradox | 存在目的抽样边界，故不推断总体相关性。 |
| 4 Collider bias | 未进行回归或控制变量分析，不适用。 |
| 5 Base-rate neglect | 未报告诊断灵敏度/特异度；明确不给出全任务基率结论。 |
| 6 Regression to mean | 同一候选做新旧公式配对反事实重算，不是按极端分数选样后的重复测量。 |
| 7 Survivorship bias | 10 个预注册任务全部完成，无退出任务。 |
| 8 Look-elsewhere effect | 报告全部 10 个任务和全部方向，包括 3 个无优化结果；未择优报告。 |
| 9 Garden of forking paths | 任务、命令、停止规则及成功标准在运行前固化；旧分重算方法显式披露。 |
| 10 Correlation != causation | 新旧分差来自同一产物的确定性公式替换，可归因于计分变换；不对模型总体能力作因果宣称。 |
| 11 Reverse causality | 评分公式在候选生成前已固化，不存在由结果反向决定公式的时间顺序。 |

覆盖率：**11/11 checked**。

## 可复现性与限制

- 固定材料：任务 ID、精确命令、模型 ID、容器镜像名、Vitis 版本、执行源 SHA-256、原始汇总及逐任务 checkpoint 均已保留。
- 最终容器内评分相关回归：171 passed，0 failed；覆盖评分目录、profile、候选管线、优化评分、报告字段和 schema 11 冻结证据。
- 外部 API 输出不能保证逐 token 确定性复现，因此本实验标为 `ANALYZED`，不宣称 deterministic `VERIFIED`。
- 本次只执行一次真实 API 试验，不能估计模型随机性的方差；要比较模型优劣需另做多随机种子/多次重复实验。
- 综合资源占用衡量目标器件容量压力，不等同于物理面积、功耗、布线拥塞或时序裕量。
- 本结果支持“公式能处理这些已观察案例”，不证明参数 (1.01)、(2)、(A_{max}=4) 对所有任务均为全局最优。
