# Track-A v2: compile_repair

Repair the C/C++ compilation failure without changing the interface.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `compile_fail`.

## Kernel specification

# amd_intro__array_array_partition_complete

Optimize the public HLS top function `matmul_partition` imported from `Array/array_partition_complete`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: c2e9f3015bae81d56d00342d8ee8d442d09f5720da89e269f5b35b57ccca9af4
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
