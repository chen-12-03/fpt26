# Track-A v2: qor_optimization

Improve latency/throughput and area without changing functionality.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `valid_baseline`.

## Kernel specification

# amd_intro__task_level_parallelism_control_driven_channels_simple_fifos

Optimize the public HLS top function `diamond` imported from `Task_level_Parallelism/Control_driven/Channels/simple_fifos`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: f5eace3178ddf804cbf16ddf294f502d414176e5079554d1b0062cb49c99732d
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
