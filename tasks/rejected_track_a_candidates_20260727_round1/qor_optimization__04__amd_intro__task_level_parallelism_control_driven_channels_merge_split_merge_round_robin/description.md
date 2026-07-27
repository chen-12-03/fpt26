# Track-A task: qor_optimization

Optimize latency/throughput and area while preserving exact functionality.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `valid_unoptimized`
- Fault/derivation record: `removed_performance_pragmas:6`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Task_level_Parallelism/Control_driven/Channels/merge_split/merge_round_robin
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__task_level_parallelism_control_driven_channels_merge_split_merge_round_robin

Optimize the public HLS top function `dut` imported from `Task_level_Parallelism/Control_driven/Channels/merge_split/merge_round_robin`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: e82bc01cc6b0773ef3c1e7a472ca22a87d2b648886ed082de68c200986cf80d0
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
