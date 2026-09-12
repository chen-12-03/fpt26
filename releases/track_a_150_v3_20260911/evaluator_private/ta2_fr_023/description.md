# Track-A v2: functional_repair

Repair the functional defect so all tests pass.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `csim_fail`.

## Kernel specification

# amd_intro__modeling_using_array_stencil_2d

Optimize the public HLS top function `Filter2DKernel` imported from `Modeling/using_array_stencil_2d`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 2d4f2c0964bd3ab1ba6b433c0435cc9f197e6ae33529d0ddcab493f1132e8308
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
