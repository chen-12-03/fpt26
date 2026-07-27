# Track-A task: qor_optimization

Optimize latency/throughput and area while preserving exact functionality.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `valid_unoptimized`
- Fault/derivation record: `removed_performance_pragmas:6`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Task_level_Parallelism/Control_driven/Channels/merge_split/split_load_balance
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__task_level_parallelism_control_driven_channels_merge_split_split_load_balance

Optimize the public HLS top function `dut` imported from `Task_level_Parallelism/Control_driven/Channels/merge_split/split_load_balance`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: eaae8423b8cfce6ccddd0d6abd0ffa33418d3dc432aaf314e3554a1b29153f13
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
