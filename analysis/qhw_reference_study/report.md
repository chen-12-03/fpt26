# qhw 评分可信度：公开 starter/reference Vitis 实证

## 结论

在本次可评分的 24 个独立公开示例上，当前 `performance=0.55 / area=0.45` **能够反映综合后、硬件层级的 QoR 优劣，暂不建议改权重**。

明确 Pareto 有方向的 9 项中，当前权重判断正确 9/9：4 个 reference 全维不劣且至少一维更优的任务均高于 starter 中性分 75；5 个 starter 反向支配 reference 的任务均低于 75。

唯一允许的替代试算为 `0.60 / 0.40`。它的明确 Pareto 方向正确率仍是 9/9，没有增加；均分从 69.74 升至 70.54，中位数仍为 75。

因此 `0.60 / 0.40` 只是更偏向性能的政策选择，不是本数据支持的更准确校准。它会减轻面积爆炸惩罚，例如 `pipelining_loops_using_free_running_pipeline` 在最坏资源增长 9× 时由 56.96 升至 61.12。

## 数据与可复现口径

- 上游：[`Xilinx/Vitis-HLS-Introductory-Examples`](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples)，固定 commit `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`，Apache-2.0。仓库通过普通 `git clone` 下拉，没有使用 GitHub API。
- 来源核验：对本地 task 声明的 source file set 重新计算 SHA-256，与刚下拉 commit 的内容逐项一致；完整结果见 [upstream_audit.json](results/upstream_audit.json)。
- pair 构造：reference 是公开上游代码；starter 仅删除会影响调度、并行或存储映射的 HLS pragma，保留接口 pragma 与只影响报告的 `LOOP_TRIPCOUNT`。每个 task 的被删指令、源码哈希和实际两版源码都在证据中。
- 工具：Vitis HLS 2025.2 build 6295257；目标 `xcu55c-fsvh2892-2L-e`；约束 5 ns。starter/reference 各跑一次 C-sim 与 C synthesis。
- 样本：共采集 36 个不同 source path/source hash；29 个四阶段全通过；其中 24 个双方 latency 有限，作为正式评分样本。其余 12 个不被静默删除，见文末筛除表。
- API：所有 evidence 均为 `api.request_count=0`；容器没有挂载 API env file，也没有模型 backend。
- 分数：使用生产实现 `scoring/scoring_v3.py` 的 `P^0.55 × A^0.45` 和 `1-1/(1+r)^2`，以 starter 为 anchor；为隔离硬件质量，报告 `efficiency=1` 的标准化分数。当前 task 没有冻结 workload case，故 II 完整报告但没有再次并入分数。
- 替代试算：严格只有一次，固定为 `P^0.60 × A^0.40`；生产评分文件未修改。

## 24 个正式任务的来源与 pair 证明

`S`/`R` 链接是实际送入 Vitis 的 starter/reference 源码；哈希列给出完整 source-set SHA-256。

| # | Task | GitHub 固定来源 | 上游 source SHA-256 | 删除 pragma | 实际 pair | 证据 |
|---:|---|---|---|---:|---|---|
| T01 | `array_array_partition_block_cyclic` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Array/array_partition_block_cyclic) | `f19625cae10cad2ab205c09369d25464d369f7f27f6fdea459e1069b150f2582` | 2 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__array_array_partition_block_cyclic/starter_synth/matmul_partition.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__array_array_partition_block_cyclic/reference_synth/matmul_partition.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__array_array_partition_block_cyclic/evidence.json) |
| T02 | `dsp_fir_decimator` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/DSP/fir/decimator) | `f6991ce6dbea75fa94e24e56e910da569702f2f55c247875cbf43e53b06ff471` | 1 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__dsp_fir_decimator/starter_synth/fir_top.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__dsp_fir_decimator/reference_synth/fir_top.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__dsp_fir_decimator/evidence.json) |
| T03 | `interface_aggregation_disaggregation_aggregation_of_nested_structs` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Interface/Aggregation_Disaggregation/aggregation_of_nested_structs) | `9d032dfae04268b2e009f308c03f7524ce586f2abb12187ee13aa4716c8d8040` | 1 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_aggregation_disaggregation_aggregation_of_nested_structs/starter_synth/top.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_aggregation_disaggregation_aggregation_of_nested_structs/reference_synth/top.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_aggregation_disaggregation_aggregation_of_nested_structs/evidence.json) |
| T04 | `interface_aggregation_disaggregation_struct_ii_issue` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Interface/Aggregation_Disaggregation/struct_ii_issue) | `b5e21cbf29d08583ac540baf411ad643b0bf0a17a70dd2ee736017b4acfe496f` | 1 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_aggregation_disaggregation_struct_ii_issue/starter_synth/dut.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_aggregation_disaggregation_struct_ii_issue/reference_synth/dut.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_aggregation_disaggregation_struct_ii_issue/evidence.json) |
| T05 | `interface_memory_aliasing_axi_master_ports` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Interface/Memory/aliasing_axi_master_ports) | `6f0c679782ea48c0fc4154658fcb65c69f0d6c910ea40710d986f01c52789f0f` | 5 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_aliasing_axi_master_ports/starter_synth/dut.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_aliasing_axi_master_ports/reference_synth/dut.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_aliasing_axi_master_ports/evidence.json) |
| T06 | `interface_memory_burst_rw` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Interface/Memory/burst_rw) | `e9899cc632d48391a7d727eeba258717448d64faae13231ac63de35b272db6e5` | 1 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_burst_rw/starter_synth/vadd.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_burst_rw/reference_synth/vadd.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_burst_rw/evidence.json) |
| T07 | `interface_memory_coefficient_filter` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Interface/Memory/coefficient_filter) | `f0a0e769875763c5e295bd263bfa68acbf64247e3e3da062dbdae3ac48acd729` | 1 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_coefficient_filter/starter_synth/hamming_window.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_coefficient_filter/reference_synth/hamming_window.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_coefficient_filter/evidence.json) |
| T08 | `interface_memory_ecc_flags` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Interface/Memory/ecc_flags) | `49a952e51cae09305b520f2fcb46c70faf96ef7e251d2094acb2d12c1d45ed1a` | 2 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_ecc_flags/starter_synth/ecc_flags.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_ecc_flags/reference_synth/ecc_flags.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_ecc_flags/evidence.json) |
| T09 | `interface_memory_lmem_2rw` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Interface/Memory/lmem_2rw) | `7b1195b60c6051f76b364d4c9473c4031f960d3807fc04454f0e613b2ebd660f` | 2 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_lmem_2rw/starter_synth/vadd.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_lmem_2rw/reference_synth/vadd.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_lmem_2rw/evidence.json) |
| T10 | `interface_memory_max_widen_port_width` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Interface/Memory/max_widen_port_width) | `4a37920fbdecb6eecf68ab84885a2860c59b7bd8894ae5e3a20929269f9db3f9` | 1 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_max_widen_port_width/starter_synth/example.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_max_widen_port_width/reference_synth/example.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_max_widen_port_width/evidence.json) |
| T11 | `interface_memory_ram_uram` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Interface/Memory/ram_uram) | `66759d7aaec48048fa6b5bc854559797f2691ac21079b172741dd976499b4ea7` | 3 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_ram_uram/starter_synth/resource_uram.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_ram_uram/reference_synth/resource_uram.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__interface_memory_ram_uram/evidence.json) |
| T12 | `misc_initialization_and_reset_static_array_of_struct_with_array_ram` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Misc/initialization_and_reset/static_array_of_struct_with_array_RAM) | `c60513a81282605001b157b19d7e686bbe2b800186f90e3cd7a242501e57537b` | 1 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__misc_initialization_and_reset_static_array_of_struct_with_array_ram/starter_synth/test.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__misc_initialization_and_reset_static_array_of_struct_with_array_ram/reference_synth/test.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__misc_initialization_and_reset_static_array_of_struct_with_array_ram/evidence.json) |
| T13 | `misc_initialization_and_reset_static_array_ram` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Misc/initialization_and_reset/static_array_RAM) | `644bfff735c23426464abf9e1192d71648bb5d7ce33a0363ffbd85ba6cff629c` | 3 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__misc_initialization_and_reset_static_array_ram/starter_synth/test.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__misc_initialization_and_reset_static_array_ram/reference_synth/test.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__misc_initialization_and_reset_static_array_ram/evidence.json) |
| T14 | `misc_initialization_and_reset_static_array_rom` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Misc/initialization_and_reset/static_array_ROM) | `a68d2e6470ea629ef81f10c21b04860e8e92273a06647a558859e409219f0457` | 2 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__misc_initialization_and_reset_static_array_rom/starter_synth/test.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__misc_initialization_and_reset_static_array_rom/reference_synth/test.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__misc_initialization_and_reset_static_array_rom/evidence.json) |
| T15 | `misc_rtl_as_blackbox` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Misc/rtl_as_blackbox) | `bdab9a1827a6571a2d964a352be92f38c26f4c218ec1de03e9f6083d4be18510` | 1 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__misc_rtl_as_blackbox/starter_synth/example.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__misc_rtl_as_blackbox/reference_synth/example.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__misc_rtl_as_blackbox/evidence.json) |
| T16 | `modeling_conditional_control_of_pragmas_using_template_function` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Modeling/conditional_control_of_pragmas/using_template_function) | `2e80f77215d1470db09195c26d3f85c6af8f5721099770e915098b2653d90ccc` | 1 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__modeling_conditional_control_of_pragmas_using_template_function/starter_synth/top.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__modeling_conditional_control_of_pragmas_using_template_function/reference_synth/top.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__modeling_conditional_control_of_pragmas_using_template_function/evidence.json) |
| T17 | `modeling_free_running_kernel_remerge_ii4to1` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Modeling/free_running_kernel_remerge_ii4to1) | `7cf9e5a5f1bec736451a93b0553f74c8e3dc25cba54299b7c19fb27b27b7a66c` | 5 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__modeling_free_running_kernel_remerge_ii4to1/starter_synth/example.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__modeling_free_running_kernel_remerge_ii4to1/reference_synth/example.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__modeling_free_running_kernel_remerge_ii4to1/evidence.json) |
| T18 | `modeling_using_array_stencil_2d` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Modeling/using_array_stencil_2d) | `2d4f2c0964bd3ab1ba6b433c0435cc9f197e6ae33529d0ddcab493f1132e8308` | 2 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__modeling_using_array_stencil_2d/starter_synth/Filter2DKernel.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__modeling_using_array_stencil_2d/reference_synth/Filter2DKernel.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__modeling_using_array_stencil_2d/evidence.json) |
| T19 | `pipelining_functions_function_instantiate` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Pipelining/Functions/function_instantiate) | `e8c186d0744d0480629d4abc18f7f1ed1b168375abec0b7b4dc6e577655bb96f` | 2 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__pipelining_functions_function_instantiate/starter_synth/top.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__pipelining_functions_function_instantiate/reference_synth/top.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__pipelining_functions_function_instantiate/evidence.json) |
| T20 | `pipelining_loops_using_free_running_pipeline` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Pipelining/Loops/using_free_running_pipeline) | `c28b876f27208a0c70179ec4127cbdce7751a1d759859518653f70f4ab171bf3` | 5 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__pipelining_loops_using_free_running_pipeline/starter_synth/free_pipe_mult.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__pipelining_loops_using_free_running_pipeline/reference_synth/free_pipe_mult.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__pipelining_loops_using_free_running_pipeline/evidence.json) |
| T21 | `task_level_parallelism_control_driven_channels_simple_fifos` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Task_level_Parallelism/Control_driven/Channels/simple_fifos) | `f5eace3178ddf804cbf16ddf294f502d414176e5079554d1b0062cb49c99732d` | 9 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__task_level_parallelism_control_driven_channels_simple_fifos/starter_synth/diamond.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__task_level_parallelism_control_driven_channels_simple_fifos/reference_synth/diamond.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__task_level_parallelism_control_driven_channels_simple_fifos/evidence.json) |
| T22 | `task_level_parallelism_control_driven_channels_using_fifos` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Task_level_Parallelism/Control_driven/Channels/using_fifos) | `60f64654b7f6ed0d836adabf54a6cae879a395584338a6e6eaccf0239ac7568f` | 7 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__task_level_parallelism_control_driven_channels_using_fifos/starter_synth/diamond.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__task_level_parallelism_control_driven_channels_using_fifos/reference_synth/diamond.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__task_level_parallelism_control_driven_channels_using_fifos/evidence.json) |
| T23 | `task_level_parallelism_data_driven_using_directio_none_in_tasks` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Task_level_Parallelism/Data_driven/using_directio_none_in_tasks) | `133fa49b571d511854aa7a2b6cbfbf09aff806072f11bfcd23007e5a62ae6e60` | 1 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__task_level_parallelism_data_driven_using_directio_none_in_tasks/starter_synth/adder_top.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__task_level_parallelism_data_driven_using_directio_none_in_tasks/reference_synth/adder_top.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__task_level_parallelism_data_driven_using_directio_none_in_tasks/evidence.json) |
| T24 | `task_level_parallelism_data_driven_using_maxi_in_tasks` | [link](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Task_level_Parallelism/Data_driven/using_maxi_in_tasks) | `2a35a246d14c48e1e5f460dac902b2882e79206df23dd7b9552120c08839f445` | 5 | [S](../../runs/qhw_reference_study_20260801/raw/amd_intro__task_level_parallelism_data_driven_using_maxi_in_tasks/starter_synth/stable_pointer.cpp) / [R](../../runs/qhw_reference_study_20260801/raw/amd_intro__task_level_parallelism_data_driven_using_maxi_in_tasks/reference_synth/stable_pointer.cpp) | [JSON](../../runs/qhw_reference_study_20260801/raw/amd_intro__task_level_parallelism_data_driven_using_maxi_in_tasks/evidence.json) |

## 全部正式任务的综合指标与分数

`L/II/clk` 为 worst latency cycles / top interval / estimated clock ns；资源均为 starter→reference。`P` 已纳入 5 ns target 与 estimated clock；`A=1/max(resource growth)`。

| # | S L/II/clk | R L/II/clk | LUT | FF | DSP | BRAM | URAM | P | A | 0.55/0.45 | 0.60/0.40 | Pareto |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| T01 | 1140/1141/3.650 | 1071/1072/3.650 | 13864→7548 | 11434→5578 | 131→63 | 2→2 | 0→0 | 1.064 | 1.000 | 75.85 | 75.93 | `reference_dominates` |
| T02 | 21/22/2.000 | 20/21/2.000 | 511→482 | 334→325 | 11→11 | 0→0 | 0→0 | 1.050 | 1.000 | 75.67 | 75.73 | `reference_dominates` |
| T03 | 10/8/1.346 | 17/16/1.346 | 149→150 | 10→10 | 0→0 | 0→0 | 0→0 | 0.588 | 0.993 | 67.15 | 66.41 | `starter_dominates` |
| T04 | 526/527/3.650 | 526/200/3.650 | 8837→7784 | 5228→5098 | 0→0 | 8→30 | 0→0 | 1.000 | 0.267 | 58.47 | 60.41 | `tradeoff` |
| T05 | 2088/2089/3.650 | 1060/1045/3.650 | 1843→2087 | 1511→1511 | 0→0 | 9→9 | 0→0 | 1.970 | 0.883 | 82.24 | 83.05 | `tradeoff` |
| T06 | 50689/50690/3.650 | 50689/50690/3.650 | 1898→1898 | 1472→1472 | 0→0 | 10→10 | 0→0 | 1.000 | 1.000 | 75.00 | 75.00 | `identical_metrics` |
| T07 | 258/256/3.117 | 258/256/3.117 | 75→75 | 20→20 | 1→1 | 1→1 | 0→0 | 1.000 | 1.000 | 75.00 | 75.00 | `identical_metrics` |
| T08 | 113/114/3.170 | 115/116/3.415 | 3994→4159 | 5108→5203 | 3→3 | 0→0 | 0→2 | 0.983 | 0.500 | 66.39 | 67.34 | `starter_dominates` |
| T09 | 16553/16554/3.650 | 14505/14506/3.650 | 2466→2627 | 1706→1728 | 0→0 | 7→7 | 0→0 | 1.141 | 0.939 | 76.09 | 76.33 | `tradeoff` |
| T10 | 81/64/3.650 | 81/64/3.650 | 1188→1188 | 1080→1080 | 0→0 | 1→1 | 0→0 | 1.000 | 1.000 | 75.00 | 75.00 | `identical_metrics` |
| T11 | 1/2/2.983 | 1/2/2.440 | 45→282 | 146→150 | 0→0 | 57→0 | 0→8 | 1.000 | 0.125 | 48.41 | 51.46 | `tradeoff` |
| T12 | 1/2/2.310 | 1/2/3.272 | 377→236 | 113→17 | 0→0 | 0→3 | 0→0 | 1.000 | 0.333 | 61.42 | 63.02 | `tradeoff` |
| T13 | 1/2/2.940 | 12/13/3.434 | 214→319 | 62→85 | 0→0 | 0→1 | 0→1 | 0.083 | 0.671 | 32.04 | 29.61 | `starter_dominates` |
| T14 | 1/2/1.359 | 1/2/1.879 | 36→31 | 10→6 | 0→0 | 0→1 | 0→0 | 1.000 | 1.161 | 76.65 | 76.47 | `tradeoff` |
| T15 | 0/1/2.320 | 0/1/2.247 | 123→121 | 0→0 | 0→0 | 0→0 | 0→0 | 1.000 | 1.017 | 75.18 | 75.16 | `reference_dominates` |
| T16 | 34/35/1.579 | 17/18/1.579 | 259→628 | 56→88 | 0→0 | 0→0 | 0→0 | 2.000 | 0.412 | 74.56 | 76.52 | `tradeoff` |
| T17 | 136/137/2.864 | 78/75/2.864 | 707→654 | 141→170 | 0→0 | 0→0 | 0→0 | 1.744 | 0.829 | 80.21 | 81.02 | `tradeoff` |
| T18 | 20523490/20523491/3.650 | 44991/44992/3.650 | 8464→14070 | 3788→11532 | 4→131 | 15→15 | 0→0 | 456.169 | 0.031 | 97.98 | 99.14 | `tradeoff` |
| T19 | 0/1/0.705 | 0/1/0.705 | 30→30 | 0→0 | 0→0 | 0→0 | 0→0 | 1.000 | 1.000 | 75.00 | 75.00 | `identical_metrics` |
| T20 | 77/78/6.179 | 51/8/3.610 | 2631→8054 | 1223→6797 | 3→27 | 0→0 | 0→0 | 1.866 | 0.111 | 56.96 | 61.12 | `tradeoff` |
| T21 | 311/312/1.843 | 308/100/1.843 | 564→489 | 110→106 | 0→0 | 0→0 | 0→0 | 1.010 | 1.038 | 75.55 | 75.51 | `reference_dominates` |
| T22 | 198/199/3.650 | 57/44/3.650 | 9240→9752 | 11830→12431 | 0→0 | 8→8 | 0→0 | 3.474 | 0.947 | 88.40 | 89.36 | `tradeoff` |
| T23 | 0/1/1.760 | 1/1/1.760 | 148→166 | 2→37 | 0→0 | 0→0 | 0→0 | 1.000 | 0.054 | 37.90 | 41.84 | `starter_dominates` |
| T24 | 9/8/3.650 | 9/8/3.650 | 1416→1492 | 904→958 | 0→0 | 0→2 | 0→0 | 1.000 | 0.500 | 66.67 | 67.64 | `starter_dominates` |

机器可读全字段（含 best/avg/worst latency、全部资源、两组分数）见 [task_metrics.csv](results/task_metrics.csv) 与 [analysis.json](results/analysis.json)。

## 评分行为判断

1. **能识别真实全维优化。** `array_partition_block_cyclic`、`dsp_fir_decimator`、`misc_rtl_as_blackbox`、`simple_fifos` 四项 reference 被 starter Pareto 支配关系反转后，当前分数都从中性 75 向上移动。
2. **不会因源码含“优化 pragma”就盲目加分。** 例如 `static_array_ram` latency 1→12，当前仅 32.04；`directio_none_in_tasks` 新增大量 FF/LUT，当前 37.90。评分依据综合结果而非代码表面。
3. **能表达性能/面积交换。** `array_stencil_2d` 的有效性能比 456×、最坏资源约 32×，仍得 97.98；`using_free_running_pipeline` 仅 1.87× 性能、最坏资源 9×，得 56.96。二者方向符合当前性能稍优先、面积仍受约束的设计。
4. **主要不足不在 0.55/0.45。** 当前 `A` 使用最坏资源增长和统一 1-unit floor。`ram_uram` 把 57 BRAM 映射为 8 URAM，虽可能是器件资源重映射，却因 URAM 0→8 被当作 8× 瓶颈，得 48.41。仅调性能/面积指数无法辨别资源替换是否更适合目标器件。
5. **II 语义仍需任务化。** 表中 top interval 有明显改善，但当前评分在没有冻结 workload case 时不使用 II；这避免重复计分，却不能完整评价持续流吞吐。

## 唯一替代系数试算与建议

本次只计算了 `0.60/0.40` 一组替代值。高于 75 的 task 从 10 增至 11；唯一跨过 75 的是 `modeling_conditional_control_of_pragmas_using_template_function`。明确 Pareto 方向正确数不变。

建议：**生产系数保持 0.55/0.45**。若竞赛政策明确要把“latency/throughput 优先于可部署面积”提升一个档位，0.60/0.40 是本次唯一有实测表格支持的备选；但它不是更准确，只是更偏性能，并会弱化 8–9× 资源增长的惩罚。

若后续要实质提升可信度，优先级应是：先把 area 从“最坏原始计数增长”升级为容量归一化、能识别 BRAM↔URAM/DSP 替换的资源代价，再为流式 task 冻结 workload 以启用 II；不应先继续调两个指数。

## 未进入 24 项评分集的 12 个候选

这些 task 同样保留来源、两版源码与工具产物，但不能合法使用 starter anchor 计算当前 qhw。

| Task | 原因 | starter C-sim | reference C-sim | starter synth | reference synth | 可用指标摘要 |
|---|---|---:|---:|---:|---:|---|
| `array_array_partition_complete` | `latency_undef` | True | True | True | True | L undef→undef; II undef→undef; LUT 7639→7639 |
| `interface_memory_manual_burst_manual_burst_example_auto_burst_inference_failure` | `latency_undef` | True | True | True | True | L undef→undef; II undef→undef; LUT 1753→1753 |
| `interface_memory_manual_burst_manual_burst_example_manual_burst_inference_success` | `latency_undef` | True | True | True | True | L undef→undef; II undef→undef; LUT 2615→2615 |
| `interface_streaming_axi_stream_to_master` | `latency_undef` | True | True | True | True | L undef→undef; II undef→undef; LUT 2056→2221 |
| `task_level_parallelism_control_driven_channels_merge_split_merge_load_balance` | `one_or_more_tool_stages_failed` | True | True | False | True | L undef→65; II undef→64; LUT undef→422 |
| `task_level_parallelism_control_driven_channels_merge_split_merge_round_robin` | `one_or_more_tool_stages_failed` | True | True | False | True | L undef→65; II undef→64; LUT undef→422 |
| `task_level_parallelism_control_driven_channels_merge_split_split_load_balance` | `one_or_more_tool_stages_failed` | True | True | False | True | L undef→17; II undef→16; LUT undef→350 |
| `task_level_parallelism_control_driven_channels_merge_split_split_round_robin` | `one_or_more_tool_stages_failed` | True | True | False | True | L undef→17; II undef→16; LUT undef→350 |
| `task_level_parallelism_control_driven_channels_using_stream_of_blocks` | `one_or_more_tool_stages_failed` | True | True | False | True | L undef→258; II undef→100; LUT undef→1791 |
| `task_level_parallelism_control_driven_patterns_using_stream_as_sync` | `latency_undef` | True | True | True | True | L undef→undef; II undef→undef; LUT 1961→1955 |
| `task_level_parallelism_data_driven_mixed_control_and_data_driven` | `one_or_more_tool_stages_failed` | True | True | False | True | L undef→undef; II undef→undef; LUT undef→402 |
| `task_level_parallelism_data_driven_unique_task_regions` | `one_or_more_tool_stages_failed` | True | True | False | True | L undef→undef; II undef→undef; LUT undef→1722 |

## 局限

- 24 项有不同 source path/source hash，但都来自同一个 AMD/Xilinx 示例仓库，不能代表所有 HLS corpus。
- starter 是可审计的 pragma ablation，不是上游作者单独发布并命名的 baseline；因此结论针对“代码级 pragma 优化能否在 qhw 中反映”，不等同于专家手工架构重写的全部情形。
- 本报告使用 C-synthesis estimate；没有 place-and-route、功耗或板级吞吐。
- 7 个 starter 无法综合、5 个双方 latency 为 `undef`，说明 benchmark 构造必须先做有效性门，不能只看是否存在两份源码。
