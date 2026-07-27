# Track-A task: synthesis_repair

Repair the HLS synthesis failure while preserving functional behavior.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `synth_fail`
- Fault/derivation record: `synthesis_only_preprocessor_error`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Interface/Memory/memory_bottleneck/original
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__interface_memory_memory_bottleneck_original

Optimize the public HLS top function `array_mem_bottleneck` imported from `Interface/Memory/memory_bottleneck/original`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 1bb7d6ff5b88e7ff23ce8ed0b6a55c2a58a1315864ffdaf09c25f0aae69ecb54
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
