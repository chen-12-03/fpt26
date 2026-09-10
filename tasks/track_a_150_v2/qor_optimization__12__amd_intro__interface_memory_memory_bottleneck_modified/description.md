# Track-A v2: qor_optimization

Improve latency/throughput and area without changing functionality.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `valid_baseline`.

## Kernel specification

# amd_intro__interface_memory_memory_bottleneck_modified

Optimize the public HLS top function `mem_bottleneck_resolved` imported from `Interface/Memory/memory_bottleneck/modified`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 2e46d6c98d7f7628904eb47400957bb31aa3948648d87be479c1cd64511236c6
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
