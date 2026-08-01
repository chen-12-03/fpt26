# Verified-Candidate Loop：Visio 完整绘图指南

> 用途：仅对照本文件，即可在 Microsoft Visio 中重建论文的完整工作流程图。
>
> 图名建议：**Evidence-Governed Verified-Candidate Loop**
>
> 论文中的核心术语：**Verified-Candidate Loop (VCL)**

## 1. 这张图必须表达的结论

这张图只服务于一个中心结论：

**LLM 负责提出候选代码，工具测量得到的证据负责所有候选状态转移。**

读者看完图后，应能回答以下问题：

1. 输入任务如何进入共享的运行状态。
2. 系统何时选择 Repair、Structural 或 Optimization。
3. LLM 生成的完整源码如何经过候选准入与验证链。
4. 正确性恢复与 QoR 优化为什么使用两条不同的晋升路径。
5. 系统如何始终保留一个可回退的已验证候选。
6. 失败信息如何影响同一次运行中的下一轮生成。
7. 已验证的公开运行证据如何进入以后运行的 QoR-RAG。
8. 独立评测器为什么位于信任边界之外。

本图不要复刻 ChatHLS 的“生成、调试、数据集构建”三阶段布局。本图的组织中心是：

**共享 Run State + 统一 Validation Chain + 双路径 Promotion + 两种反馈时间尺度 + 独立评测信任边界。**

## 2. 已锁定的语义

### 2.1 双路径晋升

候选通过完整验证后，根据当前角色进入两条不同路径。

- **Validity Restoration**：Repair 或 Structural 候选通过所有适用的必需验证后，建立或恢复 Verified Fallback。此路径解决“先得到一个正确且可综合的候选”。
- **QoR Improvement**：Optimization 候选通过所有适用的必需验证后，再进入 **Q_HW Promotion Gate**。只有候选的实测硬件 QoR 优于当前 Verified Fallback，系统才更新回退候选。

图中不要让 Repair 或 Structural 候选看起来也必须先提升 QoR 才能恢复有效状态。

### 2.2 两种反馈时间尺度

- **Within-run fast loop**：本次运行中的准入拒绝、验证失败和 QoR 拒绝进入 Failure Reflection，再影响下一轮角色选择、提示约束和 QoR-RAG 查询。
- **Across-run slow loop**：完成公开验证的运行报告经过证据筛选后进入 Public Evidence Store，供以后运行中的 QoR-RAG 检索。

### 2.3 评测信任边界

Independent Evaluator 使用独立的隐藏或评测侧证据计算最终结果。隐藏参考源码、隐藏测量和最终评分不得回流到 QoR-RAG。

在图中必须满足以下约束：

- Final Artifacts 可以指向 Independent Evaluator。
- Independent Evaluator 不得指向 Public Evidence Store、QoR-RAG、Run State 或 LLM Candidate Proposer。
- Public Evidence Loop 只接收公开提交侧的、已经完成所需验证的运行报告。

## 3. 统一术语及图中文字

论文和图中优先使用下表的英文名称，不要在不同位置替换成近义词。

| 中文含义 | 图中固定英文标签 | 说明 |
|---|---|---|
| 已验证候选循环 | Verified-Candidate Loop (VCL) | 整张图的系统名 |
| 任务契约与初始代码 | Task Contract + Starter | 输入任务、接口、预算与 starter |
| 运行状态 | Run State | 所有角色共享的候选、证据、预算和历史 |
| 状态感知角色路由 | State-Aware Role Router | 选择 Repair、Structural 或 Optimization |
| 角色条件化提案 | Role-Conditioned Proposal | 三类上下文汇合到 LLM 候选生成 |
| 候选准入 | Candidate Admission | 工具调用前的确定性检查与预算检查 |
| 验证链 | Validation Chain | 统一的工具支持验证顺序 |
| 晋升控制器 | Promotion Controller | 区分有效性恢复与 QoR 改进 |
| 已验证回退 | Verified Fallback | 最近一个通过全部适用必需门的候选 |
| 失败反思 | Failure Reflection | 从失败证据生成下一轮约束 |
| QoR 检索增强生成 | QoR-RAG | 只支持 Optimization Context |
| 公开证据循环 | Public Evidence Loop | 跨运行的公开证据沉淀与复用 |
| 最终产物 | Final Artifacts | 最终 kernel、运行报告和提交证据 |
| 独立评测器 | Independent Evaluator | 图右侧信任边界外的最终评测 |

## 4. Visio 页面设置

### 4.1 画布

- 页面方向：横向。
- 目标宽度：IEEE 双栏通栏，约 **7.16 in / 18.2 cm**。
- 建议绘图页尺寸：**18.2 cm × 8.8 至 9.4 cm**。
- 背景：纯白 `#FFFFFF`。
- 页边安全区：四周至少 0.25 cm。
- 导出格式：优先 PDF 或 SVG；需要位图时至少 600 dpi。
- 不使用渐变、阴影、三维效果、剪贴画或装饰性图标。

### 4.2 字体

- 字体：Arial、Helvetica 或 Times New Roman。
- 分组标题：9 pt，加粗。
- 主节点：8.5 至 9 pt。
- 子节点与箭头标签：8 pt，不能更小。
- `Q_HW` 中的 `HW` 建议设置为下标；若操作不便，可直接写 `Q_HW`。

### 4.3 图形语言

| 元素 | Visio 形状 | 含义 |
|---|---|---|
| 处理节点 | 圆角矩形 | 路由、提案、验证、反思等处理 |
| 数据或状态存储 | 圆柱体 | Run State、Verified Fallback、Public Evidence Store |
| 决策 | 菱形 | 角色选择、验证通过、晋升判断 |
| 输入或输出 | 平行四边形或带折角文档 | Task Contract、Final Artifacts |
| 外部系统 | 灰色矩形，外加虚线边界 | Independent Evaluator |
| 逻辑分组 | 无填充或极浅色圆角虚线框 | Proposal、Validation、Promotion 等 |

不要依赖颜色单独表达语义。颜色、形状、线型和文字应共同区分类别。

## 5. 颜色与线型

### 5.1 色彩映射

使用 Paul Tol bright 调色板。

| 语义 | 颜色 | 十六进制 |
|---|---|---|
| 验证与工具证据 | 蓝色 | `#4477AA` |
| LLM 提案与 QoR-RAG | 青色 | `#66CCEE` |
| 晋升、回退与成功输出 | 绿色 | `#228833` |
| 预算、控制与 Failure Reflection | 黄色 | `#CCBB44` |
| 失败、拒绝与错误反馈 | 红色 | `#EE6677` |
| 上下文、公共存储与外部评测 | 灰色 | `#BBBBBB` |

建议采用浅色填充加深色边框，确保黑白打印时仍能区分。

### 5.2 连线规范

| 连线类型 | 样式 | 建议颜色与宽度 |
|---|---|---|
| 主流程 | 实线、实心箭头 | 黑色，0.75 pt |
| Verified Fallback 更新 | 实线、实心箭头 | 绿色，1.0 pt |
| 本次运行反馈 | 虚线、实心箭头 | 红色，0.75 pt |
| 跨运行证据复用 | 虚线、实心箭头 | 蓝色，0.75 pt |
| 条件或控制 | 点线、实心箭头 | 深灰色，0.5 pt |
| 信任边界 | 虚线框 | 灰色，0.75 pt |
| 普通节点边框 | 实线 | 0.5 pt |
| 核心贡献边框 | 实线 | 1.0 pt |

Visio 中优先使用直角动态连接线。主流程尽量水平，反馈线尽量从节点底部出发并从下方返回，避免穿过主节点。

## 6. 总体布局

### 6.1 四条水平带

将画布从上到下划分为四条带：

1. **标题与图例带，0% 至 8% 高度**  
   左侧放图名，右侧放三种箭头图例。

2. **主流程带，8% 至 53% 高度**  
   从左到右放 Task Contract、Run State、Role Router、Proposal、Admission、Validation、Promotion、Verified Fallback 和 Final Artifacts。

3. **本次运行反馈带，53% 至 74% 高度**  
   放 Failure Reflection 和 QoR-RAG，并绘制红色虚线回路。

4. **跨运行证据与评测带，74% 至 100% 高度**  
   放 Public Evidence Loop。Independent Evaluator 放在最右侧，并用独立信任边界包围。

### 6.2 横向空间分配

以下百分比以画布可用宽度为基准，可在 Visio 的“大小和位置”窗口中近似执行。

| 区域 | 左边界 | 右边界 | 用途 |
|---|---:|---:|---|
| 输入与状态 | 1% | 18% | N1、N2 |
| 角色与提案 | 18% | 45% | N3、N4 |
| 准入与验证 | 45% | 68% | N5、N6 |
| 晋升与回退 | 68% | 87% | N7、N8 |
| 输出与评测 | 87% | 99% | N12、N13 |

如果文字过密，优先加高画布或加宽分组，不要把字号降到 8 pt 以下。

## 7. 一级节点清单

先放置以下一级节点。建议在 Visio 形状的“数据”字段中同时保存节点 ID，便于后续核对。

| ID | 标签 | 形状 | 颜色 | 位置 | 节点内短说明 |
|---|---|---|---|---|---|
| N1 | Task Contract + Starter | 文档或平行四边形 | 灰 | 主流程最左 | interface, budget, starter |
| N2 | Run State | 圆柱体 | 灰 | N1 右侧 | current kernel, evidence, budget, history |
| N3 | State-Aware Role Router | 菱形 | 黄 | N2 右侧 | Repair / Structural / Optimization |
| N4 | Role-Conditioned Proposal | 大型圆角分组框 | 青 | N3 右侧 | 三类上下文和 LLM Candidate Proposer |
| N5 | Candidate Admission | 大型圆角分组框 | 黄 | N4 右侧 | extraction, guards, budget admission |
| N6 | Validation Chain | 大型圆角分组框 | 蓝 | N5 右侧 | Interface 到 Metric Completeness |
| N7 | Promotion Controller | 大型圆角分组框 | 绿 | N6 右侧 | Validity Restoration + QoR Improvement |
| N8 | Verified Fallback | 圆柱体，粗边框 | 绿 | N7 右侧 | latest fully verified candidate |
| N9 | Failure Reflection | 圆角矩形 | 黄 | N5 至 N7 下方 | diagnostics, diff, next constraint |
| N10 | QoR-RAG | 圆角矩形或小型分组框 | 青 | N4 下方 | retrieve public measured evidence |
| N11 | Public Evidence Loop | 大型横向分组框 | 灰/蓝边 | 图底部 | report, curation, evidence store |
| N12 | Final Artifacts | 文档或平行四边形 | 绿 | N8 右侧 | kernel + run report + evidence |
| N13 | Independent Evaluator | 灰色矩形 | 灰 | 最右下或最右侧 | hidden/reference checks + Final QoR Score |

## 8. N4：Role-Conditioned Proposal 内部结构

N4 是一个青色虚线圆角分组框。内部放三行上下文，三行汇合到同一个 LLM Candidate Proposer。

### 8.1 Repair Context

从左到右放置：

`CSim/Synth Failure`
→ `Log Normalization`
→ `Issue Classification`
→ `Previous-Attempt Feedback`
→ `Repair Prompt`

此行标签：**Repair Context**。

### 8.2 Structural Context

从左到右放置：

`Required CoSim Failure`
→ `CoSim Diagnostics`
→ `Stream/Dataflow Constraint`
→ `Structural Repair Prompt`

此行标签：**Structural Context**。

### 8.3 Optimization Context

将以下信息放入一个两列的小型上下文框，不必为每项画独立大框：

- Current-Best Report
- Source Metadata
- Synthesis Diagnostics
- Baseline QoR Context
- Resource Headroom
- QoR-RAG
- Measured Rejection History

这些输入汇合到 `Optimization Prompt`。

### 8.4 公共生成尾部

三个 Prompt 通过三条实线汇合到：

`LLM Candidate Proposer`
→ `Full-Source Candidate`

必须写 **Full-Source Candidate**，用于强调系统输出完整源码候选，不是仅输出一条 pragma 或零散补丁。

QoR-RAG 只连接 `Optimization Context`，不要连接 Repair Context 或 Structural Context。

## 9. N5：Candidate Admission 内部结构

N5 内部从左到右放置三个小节点：

1. **Code Extraction**
2. **Deterministic Guards**
3. **Budget Admission**

在 Deterministic Guards 下方用两行小字列出：

`interface / no-op / duplicate`

`action / report-evidence`

连接关系：

`Full-Source Candidate`
→ `Code Extraction`
→ `Deterministic Guards`
→ `Budget Admission`
→ `Validation Chain`

失败出口：

- Code Extraction 失败 → Failure Reflection。
- Deterministic Guards 拒绝 → Failure Reflection。
- Budget Admission 拒绝 → 直接保留 Verified Fallback，并进入 Final Artifacts。

预算拒绝表示“剩余预算不足以完成一次完整候选验证”。该分支不要进入部分验证，以免消耗预算后留下不完整证据。

## 10. N6：Validation Chain 内部结构

N6 使用蓝色实线边框。内部按从左到右的顺序放置七个小节点：

`Interface`
→ `CSim`
→ `Synth`
→ `Frequency`
→ `Capacity`
→ `Required CoSim`
→ `Metric Completeness`

### 10.1 条件 CoSim

在 `Required CoSim` 上方添加小标签：

`conditional on task manifest`

若任务不要求 CoSim，流程跳过该工具，但仍到达 Metric Completeness。使用灰色点线旁路：

`Capacity`
→ `Metric Completeness`

并在线上标：

`CoSim not required`

### 10.2 验证输出

从 `Synth` 和 `Required CoSim` 各引一条短蓝色线，汇合到验证链底部的小标签：

**Candidate QoR Evidence**

完整验证结果从 N6 右侧输出到 N7，箭头标签：

`validated evidence`

每个验证门的失败出口用一条共用红色虚线连接 N9 Failure Reflection，箭头标签：

`gate failure`

如果逐个绘制七条反馈线造成拥挤，可在 N6 底部放一条红色汇流线，再用一条红色虚线连到 N9。

## 11. N7：Promotion Controller 内部结构

N7 是本图最需要视觉强调的部分，使用 1.0 pt 绿色外边框。内部画一个小型角色判断菱形：

**Candidate Role?**

它分成上下两条并行路径。

### 11.1 上方：Validity Restoration

路径：

`Repair / Structural`
→ `Complete Validation Pass`
→ `Establish Verified Fallback`

终点连接 N8，使用粗绿色箭头。

边标签可写：

`restore validity`

这条路径不放 Q_HW 判断。

### 11.2 下方：QoR Improvement

路径：

`Optimization`
→ `Complete Validation Pass`
→ 菱形 `Q_HW Promotion Gate`

Q_HW Promotion Gate 有两个出口：

- `improve` → N8，标签 `update fallback`，使用粗绿色箭头。
- `reject` → N9，标签 `Measured QoR Rejection`，使用红色虚线。

图中只表达“与当前 Verified Fallback 的实测 QoR 比较”。不要写评分公式，也不要展开性能、时钟和资源的具体权重。

## 12. N8：Verified Fallback 与正向状态循环

N8 使用绿色圆柱体和粗边框。内部文字：

**Verified Fallback**

`latest fully verified candidate`

N8 有四类输出：

1. 向右到 N12：`stop / convergence / retry limit`。
2. 向左上或上方返回 N2：`update current best`。
3. 向 N10：`Baseline QoR Context + source structure`。
4. 接收 N7 两条成功路径的绿色粗箭头。

N8 返回 N2 的连线称为 **positive state loop**。建议从 N8 顶部出发，沿主流程上方回到 N2 顶部，使用绿色或深灰色点线，避免与下方失败反馈混在一起。

## 13. N9：Failure Reflection

N9 放在 N5、N6 和 N7 下方。框内建议使用四个短项：

- key diagnostic lines
- candidate diff
- implicated source elements
- next constraint

N9 的输入：

- N5 → N9：`admission rejection`
- N6 → N9：`gate failure`
- N7 → N9：`Measured QoR Rejection`

N9 的输出：

- N9 → N3：`failure-stage role selection`
- N9 → N4：`next constraint`
- N9 → N10：`rejection / failure history`

这些线均使用红色虚线。将返回 N3 和 N4 的线沿主流程下方布置。

## 14. N10：QoR-RAG

N10 使用青色边框，放在 N4 下方、N9 左侧。内部可画三个小步骤：

`Build Structured Query`
→ `Retrieve Public Evidence`
→ `Bounded Prompt Context`

输入：

- N8 → N10：`Baseline QoR Context`
- N8 → N10：`source structure`
- N9 → N10：`Measured Rejection History`
- N11 → N10：`verified public cases`

输出：

- N10 → N4 的 Optimization Context：`retrieved evidence`

在 N10 旁加一条小注释：

`advisory evidence; validation and promotion still decide`

该注释表达 QoR-RAG 只影响候选提案，不具有晋升权。

## 15. N11：Public Evidence Loop

N11 放在图底部，用蓝色虚线边框包围三个节点：

`Fully Verified Public Run Report`
→ `Evidence Curation`
→ 圆柱体 `Public Evidence Store`

连接：

- N12 → `Fully Verified Public Run Report`，箭头标签 `public submission run report`。
- `Public Evidence Store` → N10，箭头标签 `future-run retrieval`。

使用蓝色虚线表示跨运行慢循环。

Evidence Curation 框内可用小字标出：

- version compatibility
- required gates complete
- verified success / measured failure
- provenance filter

不要从 Independent Evaluator 连接到 N11。隐藏评测信息不能成为公开检索证据。

## 16. N12 与 N13：输出和独立评测

### 16.1 Final Artifacts

N12 内部写：

- final kernel
- run report
- submission evidence

N8 在停止、收敛、重试上限或预算安全停止时都指向 N12。最终输出必须来自 Verified Fallback，不从最新但尚未验证的候选直接输出。

### 16.2 Independent Evaluator

在 N13 外画一个灰色虚线圆角框，标题：

**Evaluator Trust Boundary**

边界内放：

`Independent Evaluator`

小字：

`hidden/reference checks`

`Final QoR Score`

唯一进入该边界的业务箭头：

N12 → N13，标签：

`final kernel + submission evidence`

可选地在边界底部加入禁止回流的小注释：

`no evaluator evidence enters QoR-RAG`

不要画任何从 N13 返回左侧系统的箭头。

## 17. 全部一级连线表

以下表格是绘图后的逐条核对清单。

| 编号 | 起点 | 终点 | 标签 | 线型 |
|---|---|---|---|---|
| E01 | N1 Task Contract + Starter | N2 Run State | initialize | 黑色实线 |
| E02 | N2 Run State | N6 Validation Chain | bootstrap validation | 黑色实线 |
| E03 | N2 Run State | N3 Role Router | choose next action | 黑色实线 |
| E04 | N3 Role Router | N4 Role-Conditioned Proposal | selected role | 黑色实线 |
| E05 | N4 Proposal | N5 Candidate Admission | proposed candidate | 黑色实线 |
| E06 | N5 Candidate Admission | N6 Validation Chain | admitted candidate | 黑色实线 |
| E07 | N6 Validation Chain | N7 Promotion Controller | validated evidence | 黑色实线 |
| E08 | N7 Validity Restoration | N8 Verified Fallback | establish fallback | 绿色粗实线 |
| E09 | N7 QoR Improvement, improve | N8 Verified Fallback | update fallback | 绿色粗实线 |
| E10 | N8 Verified Fallback | N12 Final Artifacts | stop / convergence | 黑色实线 |
| E11 | N12 Final Artifacts | N13 Independent Evaluator | final kernel + evidence | 黑色实线 |
| E12 | N8 Verified Fallback | N2 Run State | update current best | 绿色或灰色点线 |
| E13 | N5 admission reject | N9 Failure Reflection | admission rejection | 红色虚线 |
| E14 | N6 gate failure | N9 Failure Reflection | gate failure | 红色虚线 |
| E15 | N7 QoR reject | N9 Failure Reflection | Measured QoR Rejection | 红色虚线 |
| E16 | N9 Failure Reflection | N3 Role Router | failure-stage role selection | 红色虚线 |
| E17 | N9 Failure Reflection | N4 Proposal | next constraint | 红色虚线 |
| E18 | N9 Failure Reflection | N10 QoR-RAG | rejection / failure history | 红色虚线 |
| E19 | N8 Verified Fallback | N10 QoR-RAG | Baseline QoR Context | 蓝色或灰色点线 |
| E20 | N10 QoR-RAG | N4 Optimization Context | retrieved evidence | 蓝色虚线 |
| E21 | N5 budget denied | N8 Verified Fallback | retain fallback | 灰色点线 |
| E22 | N12 Final Artifacts | N11 Public Run Report | public run report | 蓝色虚线 |
| E23 | N11 Public Evidence Store | N10 QoR-RAG | future-run retrieval | 蓝色虚线 |

必须缺省的连线：

- N13 → N11：禁止。
- N13 → N10：禁止。
- N13 → N2、N3 或 N4：禁止。
- N10 → Repair Context：禁止。
- N10 → Structural Context：禁止。
- 未验证候选 → N12：禁止。

## 18. QoR 在图中的五个出现位置

QoR 只在以下五处出现。这样既体现评分机制，又保持图的可读性。

| 序号 | 图中文字 | 放置位置 | 表达的作用 |
|---|---|---|---|
| Q1 | Baseline QoR Context | N8 → N10 或 Optimization Context 输入处 | 当前 Verified Fallback 的基线 |
| Q2 | Candidate QoR Evidence | N6 中 Synth/CoSim 输出下方 | 工具测得的候选硬件证据 |
| Q3 | Q_HW Promotion Gate | N7 的 QoR Improvement 路径 | 决定优化候选是否更新 fallback |
| Q4 | Measured QoR Rejection | N7 reject → N9 | 将未提升的实测结果送入反馈 |
| Q5 | Final QoR Score | N13 Independent Evaluator 内 | 外部最终评分 |

不要在流程图中放：

- Q_HW 的数学公式。
- 最终 evaluator score 的数学公式。
- 性能、资源和时钟的具体权重。
- 隐藏参考测量。

公式和权重由论文正文解释，相关文件路径见第 23 节。

## 19. 推荐的紧凑标签

如果通栏图空间不足，节点标题必须保留，说明文字可以按下表缩短。

| 完整标签 | 紧凑标签 |
|---|---|
| State-Aware Role Router | Role Router |
| Role-Conditioned Proposal | Role Proposal |
| LLM Candidate Proposer | LLM Proposer |
| Deterministic Guards | Guards |
| Metric Completeness | Metrics Complete |
| Validity Restoration | Restore Validity |
| QoR Improvement | Improve QoR |
| Establish Verified Fallback | Establish Fallback |
| Measured QoR Rejection | Measured Rejection |
| Public Evidence Store | Public Evidence |
| Independent Evaluator | Evaluator |

下列词不要缩写或替换：

- Verified-Candidate Loop
- Validation Chain
- Verified Fallback
- Failure Reflection
- QoR-RAG
- Q_HW Promotion Gate

## 20. Visio 实际绘制顺序

按以下顺序绘制，可以减少返工和交叉线。

1. 设置横向画布、白色背景、字体和网格。
2. 先画四条不可见的水平参考带。
3. 放置 N1、N2、N3、N4、N5、N6、N7、N8、N12，完成主流程对齐。
4. 在 N4 中搭建三类上下文和公共 LLM 生成尾部。
5. 在 N5 中放 Code Extraction、Guards 和 Budget Admission。
6. 在 N6 中放七级 Validation Chain，并增加条件 CoSim 旁路。
7. 在 N7 中放 Candidate Role 判断和双路径晋升。
8. 放置 N9 Failure Reflection 和 N10 QoR-RAG。
9. 放置底部 N11 Public Evidence Loop。
10. 在右侧放 N13 和 Evaluator Trust Boundary。
11. 先连接黑色主流程。
12. 再连接绿色 fallback 更新和 positive state loop。
13. 再连接红色 within-run feedback。
14. 最后连接蓝色 across-run evidence reuse。
15. 添加 QoR 的五个固定标签。
16. 添加箭头图例、信任边界说明和条件 CoSim 标签。
17. 使用“对齐”和“分布”统一节点间距。
18. 在 50% 缩放下检查文字；在灰度打印预览中检查线型。
19. 导出 PDF/SVG，嵌入论文后再次检查实际印刷尺寸。

## 21. 图中图例

右上角放一个小图例，只保留三项：

- 黑色实线：`candidate / evidence flow`
- 红色虚线：`within-run feedback`
- 蓝色虚线：`across-run evidence reuse`

绿色粗线的含义可直接通过箭头标签 `establish/update fallback` 表达，不必占用第四个图例项。

## 22. 推荐图注

### 英文图注

**Measured evidence governs candidate promotion. Full validation establishes a Verified Fallback for repair and structural candidates, while the Q_HW Promotion Gate selects subsequent optimization updates. Failure Reflection guides within-run retries, and verified public reports support cross-run QoR-RAG retrieval.**

### 中文释义

实测证据控制候选晋升。完整验证为修复类和结构类候选建立 Verified Fallback，Q_HW Promotion Gate 决定后续优化候选是否更新回退版本。Failure Reflection 指导本次运行内的重试，已验证的公开报告支持跨运行的 QoR-RAG 检索。

## 23. 源码与论文文件索引

### 23.1 路径基准

仓库根目录：

`/home/chen1/projects/fpt26_new`

下表默认使用相对于仓库根目录的路径。用户需要进一步确认图中文字或实现细节时，可直接打开对应文件。

### 23.2 总流程、运行状态和入口

| 文件 | 用于确认的内容 |
|---|---|
| `fpt26-agent-v3/agent/main.py` | 命令入口、submission/evaluator 入口、报告与证据输出 |
| `fpt26-agent-v3/agent/pipeline/submission.py` | 当前生产 submission 流程、bootstrap 验证、repair/structural/optimization 调用、finalize fallback |
| `fpt26-agent-v3/agent/workflow.py` | 向后兼容 façade；不是当前生产流程的主要来源 |
| `fpt26-agent-v3/agent/agents/base.py` | `RunState`、预算、结果、`last_verified_kernel`、`safe_fallback_kernel` |
| `fpt26-agent-v3/agent/models.py` | 运行证据、工具结果、计分卡和数据模型 |

### 23.3 三类角色与提示上下文

| 文件 | 用于确认的内容 |
|---|---|
| `fpt26-agent-v3/agent/agents/repair.py` | CSim/Synth 修复循环和通过验证后的有效候选 |
| `fpt26-agent-v3/agent/agents/structural.py` | CoSim、stream/dataflow 结构修复和完整验证 |
| `fpt26-agent-v3/agent/agents/optimize.py` | Optimization Agent 外层接口 |
| `fpt26-agent-v3/agent/agents/optimization/controller.py` | 主优化循环、QoR-RAG、候选守卫、工具验证、Q_HW 接受/拒绝、停止条件 |
| `fpt26-agent-v3/agent/agents/optimization/strategies.py` | 优化策略与动作约束 |
| `fpt26-agent-v3/agent/agents/optimization/diagnostics.py` | 优化诊断和上下文构建 |
| `fpt26-agent-v3/agent/agents/optimization/feedback.py` | 优化拒绝反馈与下一轮约束 |
| `fpt26-agent-v3/agent/prompts.py` | Repair、Structural、Optimization 提示文本 |

### 23.4 Failure Reflection 和候选准入

| 文件 | 用于确认的内容 |
|---|---|
| `fpt26-agent-v3/agent/analysis/log_normalizer.py` | 工具日志规范化 |
| `fpt26-agent-v3/agent/analysis/issue_classifier.py` | 失败阶段与问题分类 |
| `fpt26-agent-v3/agent/analysis/source_metadata.py` | 源码结构元数据 |
| `fpt26-agent-v3/agent/analysis/action_contract.py` | 优化动作契约和守卫 |
| `fpt26-agent-v3/agent/candidate/validator.py` | 接口检查、预算完整验证估算、Synth/CoSim 门和 fully verified 状态 |
| `fpt26-agent-v3/agent/candidate/selector.py` | 已验证候选和 anchor 的选择规则 |

### 23.5 Validation Chain、工具与预算

| 文件 | 用于确认的内容 |
|---|---|
| `fpt26-agent-v3/agent/validation.py` | frequency、capacity 和资源预算检查 |
| `fpt26-agent-v3/agent/runner.py` | 工具服务器与工具执行 |
| `fpt26-agent-v3/agent/integrations/harness.py` | 工具兼容和预算管理 |
| `fpt26-agent-v3/agent/candidate/validator.py` | 统一候选验证计划与验证证据 |
| `fpt26-agent-v3/scoring/scoring_v3.py` | 权威硬件评分与容量检查实现；公式不要复制到流程图 |
| `fpt26-agent-v3/scoring/profiles.py` | 评分配置与权重 |

### 23.6 Q_HW Promotion Gate

| 文件 | 用于确认的内容 |
|---|---|
| `fpt26-agent-v3/agent/agents/optimization/scoring.py` | 优化侧可见候选 QoR 计分工具 |
| `fpt26-agent-v3/agent/agents/optimization/controller.py` | 当前 best 与 candidate 的 Q_HW 比较、接受、拒绝和 measured rejection history |
| `fpt26-agent-v3/scoring/scoring_v3.py` | 生产评分内核 |
| `technical-paper/sections/qor.tex` | 论文正文中的 QoR 定义与解释 |

### 23.7 QoR-RAG 与跨运行证据

| 文件 | 用于确认的内容 |
|---|---|
| `fpt26-agent-v3/agent/knowledge.py` | 知识条目、检索、查询、提示格式、来源过滤和验证要求 |
| `fpt26-agent-v3/agent/qor_rag_curate.py` | 公开 submission run report 到 verified success/failure cases 的筛选 |
| `fpt26-agent-v3/agent/knowledge_assets/hls_generator_seeds.json` | 未验证的通用规则种子 |
| `fpt26-agent-v3/agent/knowledge_assets/verified_cases.json` | 已验证公开案例存储 |
| `technical-paper/sections/evidence_reuse.tex` | Failure Reflection 与 QoR-RAG 的论文叙述 |

### 23.8 Final Artifacts、报告和独立评测

| 文件 | 用于确认的内容 |
|---|---|
| `fpt26-agent-v3/agent/reporting/builder.py` | 运行报告构建 |
| `fpt26-agent-v3/agent/reporting/writer.py` | 报告写出 |
| `fpt26-agent-v3/agent/reporting/schema.py` | 报告字段结构 |
| `fpt26-agent-v3/agent/reporting/console.py` | 控制台报告 |
| `fpt26-agent-v3/agent/pipeline/evaluator.py` | evaluator 编排、提交证据核验和评测侧边界 |
| `fpt26-agent-v3/scoring/evaluator.py` | 独立验证与最终评测执行 |
| `fpt26-agent-v3/scoring/scoring_v3.py` | 最终评分内核 |

### 23.9 论文上下文与现有图示文件

| 文件 | 用于确认的内容 |
|---|---|
| `technical-paper/project_context.md` | 论文中心主张、固定术语、贡献与图的定位 |
| `technical-paper/sections/vcl.tex` | 当前论文正文中的紧凑 VCL 图与说明 |
| `technical-paper/figures/figure_spec_vcl.md` | 早期紧凑图规范；双路径语义以本文件为准 |
| `technical-paper/main_cn.md` | 中文论文主叙事 |
| `technical-paper/report_zh_review.md` | 中文审阅和背景说明 |
| `docs/2507.00642v4.pdf` | ChatHLS 参考论文；仅用于观察绘图风格和信息密度 |

### 23.10 相关测试

测试文件不是图中文字的来源，但可用于确认实现关系。

| 文件 | 覆盖内容 |
|---|---|
| `fpt26-agent-v3/tests/test_candidate_noop_guard.py` | no-op 候选守卫 |
| `fpt26-agent-v3/tests/test_candidate_pipeline.py` | 候选验证流水线 |
| `fpt26-agent-v3/tests/test_p0_candidate_validation.py` | P0 候选验证 |
| `fpt26-agent-v3/tests/test_p0_workflow.py` | P0 工作流 |
| `fpt26-agent-v3/tests/test_diverse_optimization.py` | 优化候选多样性与反馈 |
| `fpt26-agent-v3/tests/test_qor_rag.py` | QoR-RAG 检索和证据规则 |
| `fpt26-agent-v3/tests/test_qor_rag_small_ab_plan.py` | QoR-RAG 小规模消融计划 |
| `fpt26-agent-v3/tests/test_repair_csim_reuse.py` | Repair 对 CSim 证据的复用 |
| `fpt26-agent-v3/tests/test_structural_cosim_synth_evidence.py` | Structural 的 Synth/CoSim 证据 |
| `fpt26-agent-v3/tests/test_workflow_capacity_gate.py` | Capacity gate |
| `fpt26-agent-v3/tests/test_workflow_cosim_latency.py` | CoSim latency |
| `fpt26-agent-v3/tests/test_workflow_synth_reuse.py` | Synth 证据复用 |
| `fpt26-agent-v3/tests/test_report_loop_metrics.py` | 循环指标报告 |
| `fpt26-agent-v3/tests/test_reporting_attempt_counts.py` | 尝试次数报告 |
| `fpt26-agent-v3/tests/test_reporting_state_consistency.py` | 报告与 Run State 一致性 |
| `fpt26-agent-v3/tests/test_run_report_execution_trace.py` | run report 执行轨迹 |

## 24. 图面删减优先级

如果 18.2 cm 宽度下仍显拥挤，按以下顺序删减：

1. 删除节点内的解释性小字，保留节点标题。
2. 将 Failure Reflection 的四项缩成 `diagnostics + diff + next constraint`。
3. 将 Optimization Context 的七项排成两行逗号列表。
4. 将 Validation Chain 的七个小框改成一个横向分段条。
5. 将 Public Evidence Loop 的 curation 条件移到图注。
6. 将三类 Proposal Context 的中间步骤合并为每类两个框。

不得删减：

- 双路径 Promotion。
- Verified Fallback。
- Validation Chain 的门顺序。
- Failure Reflection 的回路。
- QoR-RAG 只进入 Optimization Context 的关系。
- Public Evidence Loop。
- Independent Evaluator 的信任边界。
- QoR 的 Q1 至 Q5 五个使用点。

## 25. 最终验收清单

### 25.1 语义

- [ ] LLM 只生成候选，不直接控制晋升。
- [ ] Repair/Structural 通过完整验证后可建立 Verified Fallback。
- [ ] Optimization 通过完整验证后仍需经过 Q_HW Promotion Gate。
- [ ] 任一适用必需验证失败都不能更新 Verified Fallback。
- [ ] 预算不足时保留 Verified Fallback。
- [ ] 最终输出来自 Verified Fallback。
- [ ] QoR-RAG 只进入 Optimization Context。
- [ ] Failure Reflection 同时影响角色选择、下一提示约束和检索查询。
- [ ] 公开运行证据形成跨运行慢循环。
- [ ] Independent Evaluator 没有任何返回系统的箭头。

### 25.2 QoR

- [ ] 图中存在 Baseline QoR Context。
- [ ] 图中存在 Candidate QoR Evidence。
- [ ] 图中存在 Q_HW Promotion Gate。
- [ ] 图中存在 Measured QoR Rejection。
- [ ] Evaluator 内存在 Final QoR Score。
- [ ] 图中没有评分公式、权重和隐藏参考数据。

### 25.3 视觉

- [ ] 主流程从左向右可一次读完。
- [ ] 红色反馈线从图下方返回，不穿过主节点。
- [ ] 蓝色跨运行反馈与红色本次运行反馈有明显线型区别。
- [ ] 信任边界清楚包围 Independent Evaluator。
- [ ] 所有文字在最终论文尺寸下至少 8 pt。
- [ ] 图在灰度模式下仍可理解。
- [ ] 背景纯白，无阴影、渐变、三维和装饰性图标。
- [ ] PDF/SVG 导出后线条没有断裂，箭头标签没有被遮挡。

### 25.4 最后一眼测试

隐藏正文，只看图和图注，确认读者仍能复述：

> Task Contract 初始化 Run State；状态选择角色；LLM 产生完整源码候选；准入后进入统一验证链；Repair/Structural 恢复有效回退，Optimization 还需通过 Q_HW 晋升；失败在本次运行内反馈，公开验证证据跨运行复用；独立评测器只接收最终产物且不回流证据。

如果这段关系无法从图中读出，应先调整布局和箭头，再考虑增加文字。
