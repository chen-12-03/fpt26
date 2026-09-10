# Track-A v2: compile_repair

Repair the C/C++ compilation failure without changing the interface.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `compile_fail`.

## Kernel specification

# amd_intro__interface_streaming_using_axi_stream_with_struct

Optimize the public HLS top function `example` imported from `Interface/Streaming/using_axi_stream_with_struct`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: f2b442e14c6057e755a67c49e517def756521492373f4cc9fa482e94ca079b92
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
