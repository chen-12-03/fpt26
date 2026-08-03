# HLS 硬件瓶颈诊断实施与验收报告

## 结论

第一阶段采用“确定性工具证据优先、LLM 负责解释与动作规划”的路线。LLM 不负责从原始
日志中凭经验猜分类；Agent 先读取每次工具调用落盘的完整 `hls_run_tcl.log`，生成结构化
诊断，再把有界版本交给统一优化提示词。证据不足时返回 `unknown`，不使用绝对 latency、
FF/LUT 比值或 DSP 数量强推根因。

最终 official 小样本中，结构化组与关闭结构化诊断的对照组均将 latency 从 1027 cycles
降到 515 cycles，内部 Q_HW 从 0.7500 提升到 0.7666；结构化组同时记录了候选动作与
`serial_loop_latency/VITIS_LOOP_7_1` 对齐。结构化组总 token 为 6015，相对对照 5315
增加 13.17%，工具调用和 credits 均未增加。

## 真实日志审计

审计对象为当前 `runs` 下 11,622 份 `*/logs/hls_run_tcl.log`。按本阶段支持或明确保留为
unknown 的消息集合，共有 2,111 份日志包含相关信号。逐行回放 9 个已支持消息 ID，
2,720/2,720 行被对应解析器识别；重复消息在最终诊断中会去重，因此诊断记录数小于
原始行数。

| 消息证据 | 原始行数 | 当前解释 |
|---|---:|---|
| HLS 200-448 | 542 | 区分 local array port 与 external `m_axi` port，不能统一套 ARRAY_PARTITION |
| HLS 200-880 | 17 | carried dependence 造成 II 约束 |
| SCHED 204-65 | 44 | loop/function 的子循环未 unroll/flatten，pipeline 未满足 |
| HLS 214-187 | 72 | variable-trip loop 无法按请求 unroll |
| HLS 200-871/1016 | 5 | 实际 critical path 超过 effective delay budget |
| HLS 200-2199 | 11 | named common resource 上的访问冲突 |
| HLS 214-114/200-471 | 20 | 非 canonical DATAFLOW region |
| HLS 200-805 | 1,697 | 默认 stream depth 的 deadlock 风险；不等同于已发生 deadlock |
| HLS 200-2250 | 312 | rewind dependence/synchronization 证据；只有与 loop metrics 关联后才能提升为主瓶颈 |

`HLS 200-1603` 本身只说明同时存在 inferred/missed MAXI bursts，不能从摘要确定端口或
根因。第二轮实现因此没有解析摘要措辞，而是读取同次 `csynth.xml` 的 `ReportBurst` 表。
真实报告中的非 `Inferred` 记录可证实归并为五类：最大 widening 位宽约束、条件分支访问、
对齐限制、访问/端口数据宽度不匹配，以及同一 bundle 的潜在多写冲突。没有 Problem 或
Resolution 字段的失败仍保留 `unknown`。

按原 2,111 份信号日志同口径回放，非 unknown 主诊断从 1,425 份提升至 1,691 份，覆盖率
由 67.5% 提升至 80.1%；unknown 从 686 份降至 420 份。原 unknown 中保留 XML 的 266 份
全部得到证据支持的主诊断，其中 232 份以 M_AXI 明细为主因、34 份由 loop metrics 确认为
dominant serial loop。剩余 420 份缺少历史 XML，不能用其他运行的报告替代。

### 成功综合类别到方案链

第三轮按 `[HLS 200-2161] Finished Command csynth_design` 回放 5,773 份成功综合日志，
把“根因类别”和“证据状态”分开记录：

| 诊断状态 | 日志数 | 方案行为 |
|---|---:|---|
| `confirmed_bottleneck` | 1,003 | 生成单一类别、精确 target 和验证信号约束的方案契约 |
| `conditional_bottleneck` | 861 | 给出候选方案，但保留源码/CoSim 等必要前置条件 |
| `unresolved_bottleneck_cause` | 424 | 只列缺失证据，不提出优化动作 |
| `no_confirmed_bottleneck` | 1,032 | 不把成功综合强行解释为瓶颈，不提出动作 |
| `insufficient_artifacts` | 2,453 | 明确要求同次综合报告，不借用其他运行产物 |

方案链为：`diagnostic_state + primary finding` → `diagnosis_guided_optimization`
契约 → LLM 检查可编辑源码前置条件并最多选择一个 family/scheme → CSim/Synth/必要
CoSim/Q_HW 复验。HLS 200-448 继续使用更严格的专用 memory-port 契约；其余已支持
类别使用通用契约。每份契约都记录 `actionable`、候选 family、target、前置条件、禁止
动作和验证信号，并随诊断历史落盘。

日志中没有找到足以稳定证明“算子实例数不足”的 allocation/operator-instance 诊断，也
没有动态 FIFO occupancy、blocking cycle 或进程速率剖析。因此这两类暂不宣称支持。

## 结构化诊断与执行路径

每个 finding 包含：

- `cause`、`target`、`confidence` 和 `symptom`；
- 经过脱敏和长度限制的原始 evidence；
- 工具测量值，例如 II lower bound、distance、clock budget、loop latency fraction；
- `allowed_actions`、`forbidden_actions` 和 `expected_validation_signals`；
- 无法确定时所缺的 `missing_evidence`。

运行路径为：完整 HLS 日志和 SynthReport → 确定性解析/去重/置信度排序 → 有界结构化
提示 → LLM 结合可编辑源代码提出一个动作 → 动作/瓶颈对齐记录 → CSim、Synth、必要
CoSim 和 Q_HW 决定保留或回退。后续轮次重新诊断，因此技术路线可以随实测结果调整，
不是固定决策树。

实现还修正了两个容易误导 LLM 的语义：评分中的 `bottleneck_resource` 实际表示最差
资源增长项，提示中改名为 `worst_resource_growth`；`m_axi` 端口冲突不会再生成片上数组
banking contract。

## 验收结果

### 离线与历史日志

| 指标 | 门槛 | 实测 |
|---|---:|---:|
| 真实消息逐行识别 | ≥95% | 2,720/2,720，100% |
| ReportBurst 已知原因行识别 | ≥95% | 1,314/1,351，97.3%；37 行原因字段为空 |
| 信号日志非 unknown 主诊断覆盖率 | ≥80% | 1,691/2,111，80.1% |
| 结构化字段/unknown/方案契约行为 | 100% 单测通过 | 19/19 专项用例通过 |
| 成功综合状态分区 | 无遗漏、无重叠 | 5,773/5,773，100% |
| 无根因证据时生成优化方案 | 0 | 0；3,909 份非 actionable |
| 相关优化/报告/安全回归 | 全部通过 | 92 passed，1 skipped |
| Docker 全套 pytest | 不新增非 freeze 回归 | 554 passed，5 failed，3 skipped |

全套 pytest 的 5 项失败已保留、未通过改 manifest 掩盖：3 项是 execution freeze 已因
source 变化而 stale 或缺少 full199 acceptance；1 项是未修改的 scoring freeze 文件
差异；1 项是未修改的 API-exception workflow 预期差异。按照仓库现有策略，只有 fresh
full199 real-API/Vitis acceptance 后才能更新 freeze，本阶段的少量 API 验证不能替代它。

### Official-first 真实 API

任务固定为 `tasks/official/dotProduct_optimize`，模型为 `qwen3-coder-plus`，temperature=0，
每组最多 1 个优化 round；两组均为 submission-only、`--no-score`，没有读取 evaluator、
hidden 或 reference 数据。

| 运行 | 请求 | tokens（prompt/total） | tools / credits | latency | Q_HW | 动作对齐 |
|---|---:|---:|---:|---:|---:|---|
| control：结构化诊断关闭 | 1 | 5213 / 5315 | 4 / 10 | 1027→515 | 0.7500→0.7666 | 未评估 |
| treatment v1：首次实现 | 1 | 5455 / 5562 | 4 / 10 | 1027→1027 | 0.7500→0.7500 | contradicted |
| treatment v2：证据关联修正 | 1 | 5911 / 6015 | 4 / 10 | 1027→515 | 0.7500→0.7666 | aligned |

首次 treatment 不能算通过：它把 `HLS 200-2250` 的 rewind 信息直接选为主根因，且 LLM
把 UNROLL 放在循环外，Vitis 报 `HLS 207-7042` 并忽略该 pragma。读取该次完整日志后，
实现改为用 loop latency/top latency 比例关联：baseline 的 II=1 循环 latency=1025、
top latency=1027、trip count=1024，证明耗时集中在该串行循环；源代码仍需证明独立性或
归约合法性后才能尝试 partial UNROLL。复验中 pragma 被合法放在循环体内，loop/top
latency 变为 513/515，候选通过 CSim、Synth 和 Q_HW 门控。

有效 A/B（control 对 treatment v2）中，QoR、工具数和 credits 持平；prompt tokens
增加 13.39%，total tokens 增加 13.17%，低于本阶段建议的 20% 上限。样本仅有 1 个
official 优化任务，因此只能证明链路有效和未在该样本退化，不能外推为总体 QoR 提升。

运行证据：

- `runs/bottleneck_diag_ab_control_v2_20260802/dotProduct_optimize/run_report.json`
- `runs/bottleneck_diag_ab_treatment_20260802/dotProduct_optimize/run_report.json`
- `runs/bottleneck_diag_ab_treatment_v2_20260802/dotProduct_optimize/run_report.json`

## 当前支持边界

稳定支持：local/external memory port、carried dependence、shared resource conflict、
timing critical path、pipeline hierarchy、variable trip count、non-canonical DATAFLOW、
stream depth risk、rewind evidence、SynthReport 比例证明的 dominant serial loop，以及
ReportBurst 明确给出的五类 M_AXI widening/burst 失败。

暂不支持或只保留 unknown：

- 缺少对应真实日志的 operator instance/allocation limit；
- 缺少动态 profiling 的 DATAFLOW rate imbalance、FIFO occupancy 和 blocking cycle；
- 只有 `HLS 200-1603` 摘要、没有同次 ReportBurst 明细的接口效率问题；
- 只有绝对 latency 或资源比值、没有 loop/message/source 关联的推断；
- 需要改变数值结合顺序但公共 tolerance/等价性证据不足的归约重写。

## 后续可直接使用的 Goal 提示词

```text
继续完善 HLS 优化 Agent 的硬件瓶颈识别。先审计现有 runs 的真实日志、报告和候选，
只实现证据支持的分类；证据不足返回 unknown。输出根因、目标、置信度、证据、动作边界
和预期验证信号，让 LLM 结合源码规划一次修改，并允许 Agent 根据中途工具结果调整路线。
所有测试在 Docker 中运行；完成离线验证后，用少量 official-first 真实 API 对照报告
请求数、tokens、tools、QoR、失败原因和未支持类型。不得臆断或用旧结果代替本轮证据。
```

这段提示只约束证据、验证和交付，不预先规定必须采用哪一种分类器、提示结构或优化动作。
