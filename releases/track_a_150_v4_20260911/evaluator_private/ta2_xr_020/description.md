# Track-A v2: structural_cosim_repair

Repair the C/RTL CoSim mismatch while preserving the public C model.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `cosim_fail`.

## Kernel specification

# amd_intro__interface_streaming_using_array_of_streams

Optimize the public HLS top function `dut` imported from `Interface/Streaming/using_array_of_streams`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 9e61fba8da06b074c4a7bf812ad600f8ffe2cb8ebfc893059f3c4d15917ef36d
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
