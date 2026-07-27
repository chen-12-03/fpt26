# Track-A task: qor_optimization

Optimize latency/throughput and area while preserving exact functionality.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `valid_unoptimized`
- Fault/derivation record: `removed_performance_pragmas:3`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Task_level_Parallelism/Data_driven/using_maxi_in_tasks
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__task_level_parallelism_data_driven_using_maxi_in_tasks

Optimize the public HLS top function `stable_pointer` imported from `Task_level_Parallelism/Data_driven/using_maxi_in_tasks`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 2a35a246d14c48e1e5f460dac902b2882e79206df23dd7b9552120c08839f445
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
