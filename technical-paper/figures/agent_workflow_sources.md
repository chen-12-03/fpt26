# Agent workflow：代码依据与抽象边界

交付文件：`agent_workflow.svg`（可编辑矢量图）和 `agent_workflow.png`（论文插图）。
核对对象为当前工作区源码，不仅是 README 或旧 workflow.py 的说明。

## 模块与连线对应

下列源码路径以 `fpt26-agent-v3/` 为根；harness 路径单独注明。

| 图中模块／连线 | 代码出处 | 图中表达的准确含义 |
|---|---|---|
| Task + starter | `agent/main.py::_run_submission`；`agent/pipeline/submission.py::run_submission` | 加载公开任务，以 `task.kernel_code` 初始化 RunState 和 starter fallback。 |
| LLM Proposal / Full-source candidate | `agent/prompts.py::_SYS`；`agent/agents/repair.py::RepairAgent.run`；`agent/agents/structural.py::StructuralRepairAgent.run`；`agent/agents/optimization/controller.py::run_optimization_loop` | 模型接收上下文，返回完整源码。没有声称存在独立 Planner 或输出可观察推理链。 |
| Interface check | `agent/candidate/validator.py::validate_candidate`、`InterfaceValidator.validate` | 检查候选接口契约；优化和结构修复在完整验证费用预检查之前执行此检查。 |
| Budget admit? | `agent/candidate/validator.py::validation_cost`、`can_afford_validation`；优化控制器和结构修复的调用点 | 完整 CSim/Synth/必要 CoSim 工具费用预检查，仅明确用于优化和结构修复。普通 RepairAgent 不统一走此预检查。 |
| 工具逐次扣费 | `../fpt26-harness/llm4hls/harness.py::ToolServer.csim/synth/cosim` | 每次工具调用先执行 budget.charge；图脚注说明普通修复依赖逐次扣费。预算不是图中 LLM token 的统一预检查。 |
| CSim → Synth → Timing + capacity → CoSim* | 各 Agent 的 run 方法；`agent/runner.py::ToolServer`；`agent/candidate/validator.py::record_synth_gates/record_cosim_gate` | 执行公开候选验证；频率最低为 100 MHz，资源受器件容量限制，CoSim 按 requires_cosim 执行。 |
| repair / structural: valid → Verified Fallback | `agent/agents/repair.py` 接纳段；`agent/agents/structural.py` 接纳段；`agent/pipeline/submission.py` 必要 CoSim 与 public acceptance；`agent/candidate/validator.py::_mark_fully_verified` | 修复不要求 Q_HW 提升。普通修复若还需 CoSim，不在 RepairAgent 内直接标为 fully verified，而由后续流程完成。图合并了这些阶段。 |
| QoR Score / Complete metrics | `agent/agents/optimization/scoring.py::score_candidate`；`scoring/scoring_v3.py` 的 metric_completeness_pass、required_metrics_complete 和 grade | 指标完整性属于评分过程；缺少必需指标时评分器返回无效 scorecard，不是所有修复接纳前独立执行的第七个统一门限。 |
| Q_HW improves? | `agent/agents/optimization/controller.py` 的 `cand_card.q_hw > best_q_hw` | 优化只在严格改善时替换 best、更新 state.kernel 并标记已验证状态。图未虚构额外的 cand_card.valid 分支。 |
| interface failure (repair / opt.) → Reflection | `agent/agents/repair.py` 接口失败及 `_repair_attempt_record`；优化控制器 `_interface_gate_feedback` | 对这两类路径，接口失败形成下一轮反馈。结构修复接口失败直接 continue，不画成统一反馈保证。 |
| diagnostics / no improvement → Failure Reflection | `agent/agents/optimization/feedback.py`；优化控制器的 rejection_feedback；`agent/agents/repair.py::_repair_attempt_record`；结构修复的 cosim_log | 概括诊断和候选反馈的数据流，不是所有失败分支都调用同一个函数。某些失败直接丢弃、continue 或终止。 |
| Failure Reflection / Local processing | `agent/agents/optimization/feedback.py`；`agent/analysis/log_normalizer.py`；`agent/analysis/issue_classifier.py` | 本地日志、差异、测量指标及约束构造，不额外调用 LLM。ΔQoR 表示候选与当前最佳的比较证据，不声称有同名统一变量。 |
| candidate feedback → LLM Proposal | `agent/prompts.py::build_prompt` 的 rejection_feedback；`build_repair_prompt` 的 previous_attempt；`build_structural_repair_prompt` 的 cosim_log | 优化和修复反馈均可直接进入下一次提示词，不必只经过知识检索。 |
| query history → QoR-RAG | 优化控制器构造 `KnowledgeQuery(history=history)`；`agent/knowledge.py::_entry_score` | 历史失败和拒绝证据影响下一轮检索，不表示自动写回或训练知识库。 |
| QoR-RAG / Rules + success/failure cases | `agent/knowledge.py::retrieve_knowledge` | 最多选一条 rule、一个 verified_case、一个 failure_case；匹配不足时可少于三个。规则本身可能是 unverified_seed，所以图未将所有规则称为已验证。 |
| bounded optimization context → LLM Proposal | `agent/knowledge.py::format_for_prompt`、MAX_KNOWLEDGE_PROMPT_TOKENS；优化控制器 knowledge_hint | 检索内容有长度上限，供优化提示词使用。 |
| Retained source (optimization) → LLM Proposal | 优化控制器 `best = state.kernel`、`build_prompt(current_kernel=best)`、接纳时更新 best | 后续优化从保留版本生成候选。普通 repair 可能沿未通过的 working_code 继续修复，因此回路明确限定 optimization。 |
| insufficient budget → Finalize | 优化控制器预算不足时 break 并恢复 best；结构修复预算不足时保存 stable_code、设置 budget_exceeded 并 return；`agent/pipeline/submission.py::_finalize` | 预算拒绝不会直接输出刚生成的新候选；最终选择仍经过保留／回退逻辑。此箭头仅对应图中 † 明确预检查的路径。 |
| Verified Fallback → Finalize | `agent/candidate/validator.py::_mark_fully_verified`；`agent/pipeline/submission.py::_finalize` | 优先选 last_verified_kernel；不存在且处于失败／预算／基础设施错误状态时可选 safe_fallback_kernel。 |
| Finalize → Output | `agent/pipeline/submission.py::_finalize`；`agent/main.py::_run_submission` | 输出 final kernel、状态、run report 和 submission evidence 等。输出文件存在不等于公开验收通过。 |

## 图的范围

- 本图是**候选循环与关键数据流的架构抽象**，不是逐行控制流图。
- 首次候选生成前会执行公开 baseline 检查；为减少文字和分支，这部分未展开。
- 重复候选、动作契约、无变化候选、competition lanes、不同模式开关和异常退出未全部展开。
- Verification 框和接口检查共同表示适用的有效性检查；RepairAgent 中先通过 CSim/Synth 再由外层执行必要 CoSim 的过程已合并。
- QoR metric completeness 仅放在优化评分分支；未声称普通修复标记 verified 时检查完整 QoR 指标。
- 一个 verified fallback 只有在适用有效性门限通过后才存在。失败 fallback 通常来自 starter；全 API 失败的特殊分支还可能移除指定的故意编译失败指令。它不能被称为 verified。
- 图没有承诺任何基础设施异常或任意预算耗尽都一定走完 Finalize；异常的实际处理以代码为准。
- 停止可能来自尝试／轮数上限、无变化、重复、停滞、证据支持的收敛、提前成功或预算；图仅展开预算停止和通用 stop。
- 图描述 submission 的公开验证与可见 QoR；hidden tests、正式 evaluator 评分不在本图范围。

## 验证

- SVG 已按 XML 解析，保留可编辑文字、路径、模块 id 和源码 metadata。
- 使用浏览器渲染 PNG 检查文字和连接线。
- 本次仅修改图、依据文档及对应论文段落／图引用，未执行模型或 Vitis，也未改变 agent 业务代码。
- 已同步摘要、引言、VCL 正文与图注中的门限适用范围，并引用新图。论文经两轮 pdflatex 编译，保持 2 页；无 Overfull 或未定义引用警告。
