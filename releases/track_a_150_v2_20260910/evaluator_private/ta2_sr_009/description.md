# Track-A v2: synthesis_repair

Repair the HLS synthesis failure while preserving behavior.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `synth_fail`.

## Kernel specification

# amd_intro__task_level_parallelism_control_driven_channels_using_fifos

Optimize the public HLS top function `diamond` imported from `Task_level_Parallelism/Control_driven/Channels/using_fifos`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 60f64654b7f6ed0d836adabf54a6cae879a395584338a6e6eaccf0239ac7568f
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
