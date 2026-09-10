# Track-A v2: functional_repair

Repair the functional defect so all tests pass.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `csim_fail`.

## Kernel specification

# amd_intro__pipelining_functions_function_instantiate

Optimize the public HLS top function `top` imported from `Pipelining/Functions/function_instantiate`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: e8c186d0744d0480629d4abc18f7f1ed1b168375abec0b7b4dc6e577655bb96f
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
