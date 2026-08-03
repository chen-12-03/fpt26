# 优化任务质量真实 API/Vitis 小门禁计划

## Material Passport

- Schema：ARS Material Passport 9
- 实验 ID：`optimize_quality_v2_gate_20260803`
- Origin Skill：academic-research-suite / experiment-agent
- Origin Mode：plan
- Origin Date：2026-08-03
- Verification Status：UNVERIFIED
- 类型：阿里云真实 API + Vitis HLS 2025.2 端到端门禁
- 模型：`qwen3-coder-plus`
- 外部写入：仅调用用户授权的阿里云兼容 API；结果仅写入下列本地运行目录

## 研究问题与预注册判据

研究问题：基于源码结构证据的复合优化策略，在不读取 reference、不按 task ID 分支的条件下，是否能明显提高优化候选的实测覆盖率和最终得分？

第一阶段只运行 1 个官方优化任务和冻结 Track-A 优化语料中 4 个不同 `kernel_family_id` 的任务。门禁通过条件为：

1. 5/5 task 形成可审计的 submission/evaluator 记录，且执行源哈希全程稳定；
2. 至少 4/5 task 测量了非 baseline 候选；
3. 至少 3/5 task 的最终真实 evaluator 分数大于 76；
4. 不出现 reference 泄漏、具体 task ID 答案分支或评分公式修改。

若小门禁未通过，不直接消耗完整 25-task API 配额；先依据通用失败类型改进。若通过，再预注册并请求确认完整 25-task 验收命令。小门禁本身不用于宣称最终“>70%”目标已经完成。

## 抽样任务

| 语料 | Task ID | 选择理由 |
|---|---|---|
| official | `dotProduct_optimize` | 官方单循环归约；验证源码常量约束的归约并行化 |
| Track-A | `qor_optimization__01__amd_intro__task_level_parallelism_control_driven_channels_simple_fifos` | 冻结优化语料，独立 kernel family |
| Track-A | `qor_optimization__07__amd_intro__interface_memory_aliasing_axi_master_ports` | 冻结优化语料，独立 kernel family |
| Track-A | `qor_optimization__08__amd_intro__modeling_free_running_kernel_remerge_ii4to1` | 冻结优化语料，独立 kernel family |
| Track-A | `qor_optimization__17__amd_intro__array_array_partition_block_cyclic` | 冻结优化语料，独立 kernel family |

任务选择在运行前固定。优化器只接收 public starter、任务说明、public testbench 和自身 Vitis 测量结果；evaluator-only reference/hidden 数据不进入 submission 进程。

## 精确命令 1：官方门禁

工作目录：`/home/chen1/projects/fpt26_new`

```bash
docker run --rm \
  -v /home/chen1/projects/fpt26_new:/workspace \
  -v /tools/Xilinx:/tools/Xilinx:ro \
  --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness:/workspace \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e FPT26_QOR_RAG_GENERALIZED=1 \
  -e FPT26_QOR_RAG_EARLY_STOP=0 \
  -w /workspace/fpt26-agent-v3 \
  fpt26-agent-v3:latest \
  bash -lc 'source /tools/Xilinx/Vitis/2025.2/settings64.sh && python3 -m scoring.run_p0_real_api_shard --task-root /workspace/tasks --output-root /workspace/runs/optimize_quality_v2_official_gate_20260803 --shard-index 0 --shard-count 1 --task-timeout-s 7200 --backend custom --model qwen3-coder-plus --competition --task-id dotProduct_optimize'
```

## 精确命令 2：四个不同 kernel family 的 Track-A 门禁

工作目录：`/home/chen1/projects/fpt26_new`

```bash
docker run --rm \
  -v /home/chen1/projects/fpt26_new:/workspace \
  -v /tools/Xilinx:/tools/Xilinx:ro \
  --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness:/workspace \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e FPT26_QOR_RAG_GENERALIZED=1 \
  -e FPT26_QOR_RAG_EARLY_STOP=0 \
  -w /workspace/fpt26-agent-v3 \
  fpt26-agent-v3:latest \
  bash -lc 'source /tools/Xilinx/Vitis/2025.2/settings64.sh && python3 -m scoring.run_p0_real_api_shard --task-root /workspace/tasks/track_a_150 --output-root /workspace/runs/optimize_quality_v2_track_gate_20260803 --shard-index 0 --shard-count 1 --task-timeout-s 7200 --backend custom --model qwen3-coder-plus --competition --task-id qor_optimization__01__amd_intro__task_level_parallelism_control_driven_channels_simple_fifos --task-id qor_optimization__07__amd_intro__interface_memory_aliasing_axi_master_ports --task-id qor_optimization__08__amd_intro__modeling_free_running_kernel_remerge_ii4to1 --task-id qor_optimization__17__amd_intro__array_array_partition_block_cyclic'
```

## 监控与停止规则

- 每个 task 的 runner 硬超时为 7200 秒；只有硬超时可以自动终止。
- 每 30--60 秒检查进程、日志增长、`shard_summary.json` 记录数和内存异常。
- 非零退出、API 错误、日志停滞或异常内存增长只报告，不自动重试或改变命令。
- 运行期间不修改 agent、runner 或评分文件；执行源哈希必须保持稳定。
- 真实 API 响应具有随机性，因此报告为 `ANALYZED`，不宣称逐 token 可复现。

## 已完成的离线门禁

- 相关扩大回归：282 passed，0 failed。
- 静态硬编码审计：`high_risk_task_answer_hardcoding_found=false`，`generalized_runtime_ready=true`。
- 冻结 25-task 语料的源码结构检查：21/25 检出互联多阶段并行机会；其余归约/矩阵类任务由源码可见的有限因子和访存证据约束。
- 尚未为本计划调用任何真实 API。
