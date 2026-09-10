# Track-A v2: qor_optimization

Improve latency/throughput and area without changing functionality.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `valid_baseline`.

## Kernel specification

# amd_intro__interface_memory_ecc_flags

Optimize the public HLS top function `ecc_flags` imported from `Interface/Memory/ecc_flags`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 49a952e51cae09305b520f2fcb46c70faf96ef7e251d2094acb2d12c1d45ed1a
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
