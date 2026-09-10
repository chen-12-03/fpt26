# Track-A v2: structural_cosim_repair

Repair the C/RTL CoSim mismatch while preserving the public C model.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `cosim_fail`.

## Kernel specification

# amd_intro__interface_memory_burst_rw

Optimize the public HLS top function `vadd` imported from `Interface/Memory/burst_rw`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: e9899cc632d48391a7d727eeba258717448d64faae13231ac63de35b272db6e5
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
