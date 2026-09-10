# Track-A v2: structural_cosim_repair

Repair the C/RTL CoSim mismatch while preserving the public C model.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `cosim_fail`.

## Kernel specification

# amd_intro__modeling_using_float_and_double

Optimize the public HLS top function `double_mul_pow2` imported from `Modeling/using_float_and_double`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: f58027813c47cd91b386e82aa3c3f6506a9000c7cda38326661fc7a1cf45da49
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
