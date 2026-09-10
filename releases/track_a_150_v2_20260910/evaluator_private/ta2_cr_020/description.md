# Track-A v2: compile_repair

Repair the C/C++ compilation failure without changing the interface.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `compile_fail`.

## Kernel specification

# amd_intro__modeling_pointers_native_casts

Optimize the public HLS top function `pointer_cast_native` imported from `Modeling/Pointers/native_casts`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: a76e7f59ded6032ea5f8301a5dd29ee8c35781b473a3b035f734a7da34368aaf
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
