# Track-A v2: functional_repair

Repair the functional defect so all tests pass.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `csim_fail`.

## Kernel specification

# amd_intro__modeling_fixed_point_sqrt

Optimize the public HLS top function `fxp_sqrt_top` imported from `Modeling/fixed_point_sqrt`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: d013aec9907683e1f4e2f4d29da5fe5911ead54d44f373595bcfb3f705607bfa
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
