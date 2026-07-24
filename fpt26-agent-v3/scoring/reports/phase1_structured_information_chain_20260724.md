# 第一阶段：结构化信息链增强实施与验收报告

日期：2026-07-24  
当前最终执行源 SHA256：`8b702dce371c6508b4a34792c874129ede403722f8176d4bc44e8c6c7f33dcc7`

## 结论

功能实现、单元测试、比赛语义审计、12 任务真实 paired run、97 题
fresh split-role run 和 official 三题独立审计均已完成并通过。paired
run 通过有效性、required CoSim、audit、credits、tokens 和 Q_HW 门槛；
最终 v4 全量证据为 97/97、audit error 0、API usage 完整、
`workflow_integrity_ok=true`。`execution-freeze.json` 已用 v4
acceptance 哈希重签，完整回归为 408 passed、3 skipped、0 failed。

## 实现

### 1. Repair 信息链

- `IssueClassifier` 的 stage、category、confidence、summary、
  normalized key lines、source location 和 recommended action 进入最终 prompt。
- 第二次及以后尝试携带上次 candidate diff 与验证结果。
- 日志、diff 和字段均有确定上限；UTF-8 异常安全降级。
- 宿主机绝对路径只保留文件名/行号，敏感值继续经过既有 redaction。
- RepairAgent 没有新增 LLM 调用。

旧结构仅传入类似：

```json
{"tool_results":{"csim":"FAIL: mismatch"}}
```

新结构增加：

```json
{
  "repair_evidence": {
    "failure_stage": "csim",
    "category": "functional_mismatch",
    "confidence": "high",
    "error_summary": "top.cpp:42: mismatch",
    "key_lines": ["ERROR: ..."],
    "suspected_source_location": "top.cpp:42",
    "recommended_action": "inspect_branch_formula",
    "previous_attempt": {
      "candidate_diff": "...",
      "result": {"stage": "csim", "phase": "runtime_fail"}
    }
  }
}
```

### 2. Optimization Synth 失败反馈

- 新增可安全序列化的 `OptimizationFailure`。
- 保存 stage、category、summary、诊断行、candidate fingerprint、diff 摘要、
  implicated pragma/loop/array、下一步约束和 repetition count。
- 相同 fingerprint 或归一化失败模式合并计数，历史最多保留 3 条。
- 下一轮通过 `previous_candidate_feedback` 看见最近失败；无独立修复调用。
- diff 上限 1600 字符，summary 360 字符，诊断行最多 6 条且每条 180 字符。
- 保留既有 duplicate/no-op 防护，并补足两个确定性 no-op：
  单语句 `for` 的可选花括号，以及仅对顶层函数添加 `INLINE/INLINE OFF`。
  两者在工具调用前收敛，不修改 Q_HW 接受公式。

### 3. 循环和数组元数据

- 新增 `agent/analysis/source_metadata.py`，不依赖编译器、网络或综合工具。
- 循环：name/label、nesting depth、静态 trip count 或边界、PIPELINE II、
  UNROLL factor，以及可保守匹配的 report loop name。
- 数组：name、element type、rank/extents、PARTITION、RESHAPE 和简单访问模式。
- 不确定值统一为 `unknown`；解析失败返回空元数据。
- 无损结构可稳定 JSON 序列化；模型可见投影硬限制为 700 字符，并以
  loop/array round-robin 保证两类证据都不会被长列表单方面挤出。

## 修改文件

阶段实现：

- `agent/agents/repair.py`
- `agent/prompts.py`
- `agent/analysis/log_normalizer.py`
- `agent/analysis/source_metadata.py`
- `agent/agents/optimization/controller.py`
- `agent/agents/optimization/feedback.py`
- `agent/agents/optimization/strategies.py`
- `agent/agents/optimize.py`

阶段测试：

- `tests/test_structured_information_chain.py`
- `tests/test_source_metadata.py`
- `tests/test_candidate_noop_guard.py`

真实验收过程中发现并最小修复的既有基础问题：

- `agent/integrations/llm/protocol.py`、`agent/reporting/metrics.py`：
  让 runner 读取底层真实 API client 和完整 token usage；不改变调用。
- `scoring/run_p0_real_api_shard.py`、`scoring/reconcile_p0_evaluators.py`：
  evaluator 显式携带 mandatory submission evidence。
- `agent/integrations/task_repository.py`：
  公共任务加载后执行仓库已有的 testbench data-file 归一化，修复
  MachSuite 输入文件存在但未挂载的伪 CSim 失败。
- 对应测试：
  `tests/test_llm_token_usage.py`、`tests/test_p0_batch_runner.py`、
  `tests/test_task_data_files.py`。

## 自动化测试

定向测试：

```text
35 passed
```

完整 Docker/Vitis 命令：

```bash
python3 -m pytest -q tests scoring -rs \
  --basetemp=/workspace/.pytest-tmpfs/run
```

最终结果：

```text
408 passed, 3 skipped, 0 failed
```

reference-classification 的 727 文件冻结记录已通过逐字恢复误删的
`c2hlsc__add_round_key/description.md` 重新成立；没有改写权重搜索前的
冻结分类。execution freeze 已用最终执行源、97 题 acceptance 和
official acceptance 的哈希重签；frozen execution files 与 65 个
agent Python 源文件的树哈希均通过回归。

## 比赛语义审计

以下语义未改变：

- interface → CSim → Synth → required CoSim 顺序；
- 100 MHz 和设备资源容量约束；
- candidate 只有在既有门禁通过且实测 `candidate_q_hw > best_q_hw`
  时才接受；
- 失败候选回滚与最终 fully-verified candidate；
- credit 定义和 ToolServer 计费；
- required CoSim 条件；
- submission 不读取 hidden/reference，evaluator 继续隔离；
- Competition/DiverseOptimizationStage 未启用。

## 真实 paired run

baseline 是在 `/tmp` 中从当前仓库生成、仅回退本阶段功能文件的临时树；
runner 计量和公共 data-file 修复在两侧保持一致。baseline 和 current
各自批次内执行源稳定：

- baseline：`28a00ce25cc7e9f33dc50593aa739ea80424ffff897e4a3698568a80f5e4a6cb`
- current：`01a68fbec796226fda2d0108cec8651c18d7b0aef9f24cdca5d191c6f2d1401d`

12 项覆盖 official、C2HLSC、CHStone、GNNBuilder、MachSuite、PolyBench
和 Rosetta。选样依据的历史归档包含超过 10 次 Repair/Synth 失败事件。

最终产物：

- baseline official：
  `runs/phase1_contemporaneous_baseline_official_20260724_v1`
- baseline generated：
  `runs/phase1_contemporaneous_baseline_generated_20260724_v1`
- current official：
  `runs/phase1_structured_final_official_20260724_v6`
- current generated：
  `runs/phase1_structured_final_generated_20260724_v6`

| 指标 | Baseline | Current | 变化 | 门槛 |
|---|---:|---:|---:|---|
| 有效任务 | 12/12 | 12/12 | 持平 | 不下降，PASS |
| required CoSim | 12/12 | 12/12 | 持平 | 100%，PASS |
| audit/infrastructure errors | 0 | 0 | 持平 | 0，PASS |
| credits 总计 | 202 | 196 | -2.97% | 平均增幅 ≤5%，PASS |
| tokens/task 中位数 | 8029.0 | 7947.5 | -1.02% | 增幅 ≤10%，PASS |
| 配对 token 变化中位数 | — | — | +6.67% | ≤10%，PASS |
| tokens 总计 | 109462 | 106439 | -2.76% | 记录项 |
| Q_HW 几何均值 | 0.751043 | 0.756193 | +0.69% | 不显著下降，PASS |
| submission 失败事件 | 6 | 5 | -16.67% | 记录项 |
| Synth 失败事件 | 2 | 2 | 持平 | 记录项 |

效果指标满足“有效率不下降且 Q_HW 几何平均正向提升”。Q_HW 有 1 个正向
配对、0 个负向配对，其余持平；双侧 exact sign test `p=1.0`，没有显著
下降。

## 验收矩阵

- A 功能验收：PASS。
- B 回归验收：PASS；408 项通过、3 项按既有环境条件跳过、0 项失败。
- C 比赛语义验收：PASS。
- D 成本验收：PASS。
- E 真实验证：PASS；paired 12 项和 full 97 项均完成独立审计。

## 未解决风险

- 静态元数据提取器是保守 recognizer，不是完整 C++ parser；宏生成循环、
  复杂模板和非标准 pragma 会返回 `unknown`。
- 真实 LLM 输出存在随机性；paired run 通过执行源、同日 API、同任务与
  同工具配置减少偏差；97 项全量重跑用于补充覆盖，但不能消除模型随机性。
- 当前 auditor 只允许替换旧 `infrastructure_error`，而 runner 会对
  `outcome=completed` 但 API usage 不完整的记录生成 retry ID。本次使用
  带原摘要哈希和移除清单的确定性 supersession evidence view 解决该
  证据合并差异；原始 shard/retry 摘要保持不变。

## Freeze 闭环补充证据

97 题 v3（补 official launcher 前的执行源
`2966cc45131dd7bb993d770bbb5b7e50da9654837290be40f38b7747a235b85a`）
完成并通过独立审计：

- 97/97 recorded，77 completed、20 failed；
- audit error 0，`workflow_integrity_ok=true`；
- submission public-only 97/97；
- required CoSim 1/1；
- API request/response 159/159，failed request 0；
- total tokens 769032，credits 1062；
- official 3 题独立证据视图 `acceptance_ok=true`。

证据文件：

- `runs/phase1_full97_20260724_v3_acceptance.json`
- `runs/phase1_official_from_full97_20260724_v3_acceptance.json`

随后修复 `run-p0-official-fresh.sh`，保证 evaluator 始终携带
`submission_evidence.json`；shell syntax 和相关回归测试共 45 项通过。
该 launcher 属于 execution snapshot，所以按 policy 启动最终 v4 重跑。

v4 在账户欠费窗口的 partial 聚合审计：

- 文件：`runs/phase1_full97_20260724_v4_partial_audit.json`
- execution SHA：
  `8b702dce371c6508b4a34792c874129ede403722f8176d4bc44e8c6c7f33dcc7`
- recorded 73/97，missing 24；
- 66/73 任务具备完整 API usage；
- 欠费窗口内 21 个 failed requests，分布在 7 个待 fresh retry 任务：
  `polybench__3mm`、`polybench__cholesky`、`polybench__fdtd_2d`、
  `polybench__gemver`、`polybench__symm`、`polybench__trisolv`、
  `rosetta__optical_flow__outer_product`。

账户恢复后，在相同执行源 SHA 下完成三个原 shard 的 `--resume`，
覆盖达到 33/33、32/32、32/32。interim audit 只列出上述 7 个
欠费任务。首轮 fresh retry 完成 7/7，其中 `cholesky` 有一次瞬时
失败请求；第二轮由审计文件精确选择并重跑该单项，结果为 API 2/2、
failed request 0、audit error 0。

旧欠费记录的 `outcome` 是 `completed`，但含
`real_api_usage_incomplete`；当前 auditor 的重复替换条件只接受旧
`outcome=infrastructure_error`。因此最终审计使用确定性派生视图：

- 三个主 shard 视图按 interim audit 移除 7 条旧记录；
- retry1 视图按 retry1 audit 移除旧 `cholesky` 记录；
- retry1 的其余 6 条和 retry2 的 1 条完整记录填回；
- 每个视图都保存原 `shard_summary.json` SHA、驱动 audit SHA 和
  `removed_task_ids`；原始证据没有修改。

最终 v4 97 题 acceptance：

- 文件：`runs/phase1_full97_20260724_v4_acceptance.json`
- SHA256：
  `293eefa6d0f849ce5f5f73ade8219bf768ce7a31ef85df9ee772d8e1592aca3f`
- 97/97 recorded，78 completed、19 failed；
- audit error 0，`retry_task_ids=[]`，
  `workflow_integrity_ok=true`；
- submission public-only 97/97，forbidden access 0；
- required CoSim 1/1；
- real API usage proven 97/97，request/response 158/158，
  failed request 0；
- total tokens 762140，credits 1051；
- execution source stable：
  `8b702dce371c6508b4a34792c874129ede403722f8176d4bc44e8c6c7f33dcc7`。

official 三题独立证据视图：

- 文件：`runs/phase1_official_from_full97_20260724_v4_acceptance.json`
- SHA256：
  `ec8c0137e980f6ba93dd337e11c98de5f78d06b11d286d3ec5f4564c6a933730`
- 3/3，`acceptance_ok=true`，errors 0；
- execution source 首尾快照一致；
- API requests 7，tokens 27583，credits 100；
- 最低观测频率 315.457 MHz。

`execution-freeze.json` 已记录上述两个 acceptance 哈希、最终执行源
SHA、镜像 `fpt26-agent-v3:phase1-20260724` 和 Vitis HLS
2025.2 build 6295257。重签后完整 Docker/Vitis 回归：

```text
408 passed, 3 skipped, 0 failed
```
