# Track-A v2: structural_cosim_repair

Repair the C/RTL CoSim mismatch while preserving the public C model.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `cosim_fail`.

## Kernel specification

# amd_intro__task_level_parallelism_data_driven_using_directio_none_in_tasks

Optimize the public HLS top function `adder_top` imported from `Task_level_Parallelism/Data_driven/using_directio_none_in_tasks`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 133fa49b571d511854aa7a2b6cbfbf09aff806072f11bfcd23007e5a62ae6e60
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
