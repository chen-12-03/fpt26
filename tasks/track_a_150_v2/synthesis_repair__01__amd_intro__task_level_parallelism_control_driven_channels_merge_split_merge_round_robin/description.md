# Track-A v2: synthesis_repair

Repair the HLS synthesis failure while preserving behavior.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `synth_fail`.

## Kernel specification

# amd_intro__task_level_parallelism_control_driven_channels_merge_split_merge_round_robin

Optimize the public HLS top function `dut` imported from `Task_level_Parallelism/Control_driven/Channels/merge_split/merge_round_robin`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: e82bc01cc6b0773ef3c1e7a472ca22a87d2b648886ed082de68c200986cf80d0
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
