# Track-A task: synthesis_repair

Repair the HLS synthesis failure while preserving functional behavior.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `synth_fail`
- Fault/derivation record: `synthesis_only_preprocessor_error`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Interface/Memory/lmem_2rw
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__interface_memory_lmem_2rw

Optimize the public HLS top function `vadd` imported from `Interface/Memory/lmem_2rw`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 7b1195b60c6051f76b364d4c9473c4031f960d3807fc04454f0e613b2ebd660f
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
