# Track-A v2: functional_repair

Repair the functional defect so all tests pass.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `csim_fail`.

## Kernel specification

# amd_intro__interface_memory_memory_bottleneck_original

Optimize the public HLS top function `array_mem_bottleneck` imported from `Interface/Memory/memory_bottleneck/original`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 1bb7d6ff5b88e7ff23ce8ed0b6a55c2a58a1315864ffdaf09c25f0aae69ecb54
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
