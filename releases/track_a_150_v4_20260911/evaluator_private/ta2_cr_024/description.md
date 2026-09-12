# Track-A v2: compile_repair

Repair the C/C++ compilation failure without changing the interface.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `compile_fail`.

## Kernel specification

# amd_intro__interface_aggregation_disaggregation_auto_disaggregation_of_struct

Optimize the public HLS top function `dut` imported from `Interface/Aggregation_Disaggregation/auto_disaggregation_of_struct`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 72f7971f1290ad7c9ba4557b722f45fa63f9db7f9bc010a8cd2b02ea5ea7fa03
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
