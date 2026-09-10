# Track-A v2: structural_cosim_repair

Repair the C/RTL CoSim mismatch while preserving the public C model.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `cosim_fail`.

## Kernel specification

# amd_intro__task_level_parallelism_data_driven_simple_data_driven

Optimize the public HLS top function `odds_and_evens` imported from `Task_level_Parallelism/Data_driven/simple_data_driven`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: cec256fb15ea2405f548a962a34eb3448222f1263a8dabba3e09bd1c00528510
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
