# Schema 11 阿里云真实 API/Vitis 验证计划

## Material Passport

- Schema：ARS Material Passport 9
- 实验 ID：`schema11_ali_qwen3coder_real10_20260803`
- 类型：真实 API + Vitis HLS 2025.2 端到端评估
- 模型：阿里云 `qwen3-coder-plus`
- 状态：已按下列精确命令完成；10/10 task 成功，结果见 `analysis/schema11_ali_real10/results.md`
- 外部写入：仅调用用户指定的阿里云兼容 API；本地结果写入声明的运行目录
- 主要输出：`runs/schema11_ali_qwen3coder_real10_20260803/shard_summary.json`

## 研究问题

1. Schema 11 是否能在真实 repair 任务中显式反映“无效 starter 被修复为有效候选”的价值？
2. 容量归一化综合资源公式投入生产后，真实 optimize 任务的评分与旧最差资源公式相比如何变化？
3. 正式评分取消候选自锚定后，repair 与 optimize 是否仍能得到可审计的有效锚点和最终分数？

## 抽样任务

全部任务均来自冻结的 `tasks/track_a_150`，均含公开 starter、隐藏测试和 evaluator-only reference；starter 与 reference 源码逐文件比较均不相同。

| # | 类别 | Task ID | 覆盖点 |
|---:|---|---|---|
| 1 | compile repair | `compile_repair__14__amd_intro__interface_aggregation_disaggregation_disaggregation_of_axis_port` | 接口/编译修复 |
| 2 | compile repair | `compile_repair__16__amd_intro__interface_memory_burst_rw` | 内存接口编译修复 |
| 3 | functional repair | `functional_repair__03__amd_intro__misc_malloc_removed` | C-sim 功能修复 |
| 4 | functional repair | `functional_repair__06__amd_intro__modeling_conditional_control_of_pragmas_using_template_function` | 模板代码功能修复 |
| 5 | synthesis repair | `synthesis_repair__01__amd_intro__interface_memory_ecc_flags` | 综合期修复 |
| 6 | synthesis repair | `synthesis_repair__02__amd_intro__interface_memory_lmem_2rw` | 双端口存储综合修复 |
| 7 | QoR optimize | `qor_optimization__01__amd_intro__task_level_parallelism_control_driven_channels_simple_fifos` | DATAFLOW/FIFO |
| 8 | QoR optimize | `qor_optimization__07__amd_intro__interface_memory_aliasing_axi_master_ports` | AXI master 接口 |
| 9 | QoR optimize | `qor_optimization__08__amd_intro__modeling_free_running_kernel_remerge_ii4to1` | II/自由运行内核 |
| 10 | QoR optimize | `qor_optimization__17__amd_intro__array_array_partition_block_cyclic` | 数组分区与资源折中 |

该选择包含 6 个 repair 和 4 个 optimize；四个 optimize 分属冻结语料中四个不同的 `kernel_family_id`，避免重复替换任务造成伪多样性。

## 精确执行命令

工作目录：`/home/chen1/projects/fpt26_new`

```bash
docker run --rm \
  -v /home/chen1/projects/fpt26_new:/workspace \
  -v /tools/Xilinx:/tools/Xilinx:ro \
  --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace/fpt26-agent-v3:/workspace/fpt26-harness \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -w /workspace \
  fpt26-agent-v3:latest \
  bash -lc 'source /tools/Xilinx/Vitis/2025.2/settings64.sh &&
    python3 -m scoring.run_p0_real_api_shard
      --task-root tasks/track_a_150
      --output-root runs/schema11_ali_qwen3coder_real10_20260803
      --shard-index 0
      --shard-count 1
      --task-timeout-s 7200
      --backend custom
      --model qwen3-coder-plus
      --task-id compile_repair__14__amd_intro__interface_aggregation_disaggregation_disaggregation_of_axis_port
      --task-id compile_repair__16__amd_intro__interface_memory_burst_rw
      --task-id functional_repair__03__amd_intro__misc_malloc_removed
      --task-id functional_repair__06__amd_intro__modeling_conditional_control_of_pragmas_using_template_function
      --task-id synthesis_repair__01__amd_intro__interface_memory_ecc_flags
      --task-id synthesis_repair__02__amd_intro__interface_memory_lmem_2rw
      --task-id qor_optimization__01__amd_intro__task_level_parallelism_control_driven_channels_simple_fifos
      --task-id qor_optimization__07__amd_intro__interface_memory_aliasing_axi_master_ports
      --task-id qor_optimization__08__amd_intro__modeling_free_running_kernel_remerge_ii4to1
      --task-id qor_optimization__17__amd_intro__array_array_partition_block_cyclic'
```

## 监控与停止规则

- 每个任务由 runner 设置 7200 秒硬超时；硬超时是唯一自动终止条件。
- 每 30--60 秒检查进程存活、`shard_summary.json` 的记录数以及当前任务日志是否增长。
- 非零退出、API 异常、连续日志停滞和异常内存增长只报告，不自动重试或修改命令。
- 运行期间不修改 `agent/**/*.py`、评分器或 runner，确保 `execution_source.tree_sha256` 从头到尾一致。

## 成功标准

1. `selected_task_count=10` 且 `completed_record_count=10`。
2. 每个任务都有 submission 运行情况；完成的 submission 都由独立 evaluator 复核。
3. 每个可评分任务都有 Schema 11/显式 profile 包装后的最终分数与完整中间量。
4. 报告 repair 的 `D/F`、锚点来源和新旧评分差；报告 optimize 的性能比、综合资源比和新旧评分差。
5. `execution_source.stable=true`，模型和 API 合规检查无错误。

真实 API 本身具有随机性，因此不宣称逐 token 可复现；固定任务、代码哈希、模型 ID、Vitis 版本、命令、报告和评分计算均保留以供审计。

## 运行前预检记录

- Vitis 入口：`/tools/Xilinx/2025.2/Vitis/bin/vitis-run`
- Vitis 版本：2025.2，Build 6295257
- 目标器件：`xcu55c-fsvh2892-2L-e`
- 10/10 public task 均可由隔离加载器读取。
- 10/10 task 均存在 evaluator-only reference 和 hidden testbench。
- 10/10 starter 与 reference 源码均不同。
- 输出根目录在预检时不存在，满足 fresh-run 要求。
- 当前相关回归：175 passed，0 failed。
- 待运行执行源快照：85 files，`tree_sha256=7fd2ef0c3340d53f12f7b6ca21c71c3511287ac7fabf019fed1057449ec8f74e`。

## 运行完成记录

- `selected_task_count=10`，`completed_record_count=10`，`audit_error_record_count=0`。
- 共 23 次真实 API 请求、158,073 tokens；总耗时 1,180.22 秒。
- 运行期间执行源保持稳定，结束哈希与预检哈希一致。
- 完整逐任务评分、硬件指标、新旧公式对照和 11 项统计谬误检查见 `analysis/schema11_ali_real10/results.md`。
