# Track-A v2: structural_cosim_repair

Repair the C/RTL CoSim mismatch while preserving the public C model.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `cosim_fail`.

## Kernel specification

# amd_intro__interface_memory_coefficient_filter

Optimize the public HLS top function `hamming_window` imported from `Interface/Memory/coefficient_filter`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: f0a0e769875763c5e295bd263bfa68acbf64247e3e3da062dbdae3ac48acd729
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
