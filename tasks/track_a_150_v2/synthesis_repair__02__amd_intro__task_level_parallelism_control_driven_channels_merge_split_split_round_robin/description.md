# Track-A v2: synthesis_repair

Repair the HLS synthesis failure while preserving behavior.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `synth_fail`.

## Kernel specification

# amd_intro__task_level_parallelism_control_driven_channels_merge_split_split_round_robin

Optimize the public HLS top function `dut` imported from `Task_level_Parallelism/Control_driven/Channels/merge_split/split_round_robin`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 991bdc4f01c0a649c8e26b0e37d0e82be4d4a1e273e74110669d8ed1d4bf645e
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
