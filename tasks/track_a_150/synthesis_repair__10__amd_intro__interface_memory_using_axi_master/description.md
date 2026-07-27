# Track-A task: synthesis_repair

Repair the HLS synthesis failure while preserving functional behavior.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `synth_fail`
- Fault/derivation record: `synthesis_only_preprocessor_error`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Interface/Memory/using_axi_master
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__interface_memory_using_axi_master

Optimize the public HLS top function `example` imported from `Interface/Memory/using_axi_master`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 2a37a6dadfa6f40091e478815eb8d1be495dfe7881d7c7dd435f7ac2c59afda0
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
