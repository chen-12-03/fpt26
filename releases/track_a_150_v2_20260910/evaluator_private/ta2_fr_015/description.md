# Track-A v2: functional_repair

Repair the functional defect so all tests pass.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `csim_fail`.

## Kernel specification

# amd_intro__modeling_pointers_basic_pointers

Optimize the public HLS top function `pointer_basic` imported from `Modeling/Pointers/basic_pointers`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 0310dc25343d5b79919b3c54eae65c8c8accceb0d829ff7c044165825ea0a3ac
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
