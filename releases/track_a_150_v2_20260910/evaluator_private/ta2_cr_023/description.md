# Track-A v2: compile_repair

Repair the C/C++ compilation failure without changing the interface.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `compile_fail`.

## Kernel specification

# amd_intro__interface_streaming_axi_stream_to_master

Optimize the public HLS top function `example` imported from `Interface/Streaming/axi_stream_to_master`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 6234d6cfef915265768266b16e638b1b54e868eef11e887894b28707f9c13678
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
