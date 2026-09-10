# Track-A v2: functional_repair

Repair the functional defect so all tests pass.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `csim_fail`.

## Kernel specification

# amd_intro__interface_streaming_axis_array_stream_no_side_channel_data

Optimize the public HLS top function `example` imported from `Interface/Streaming/axis_array_stream_no_side_channel_data`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 091186ac19385a74e67c204bf6274b91a0148df78992ebe4377ae188d748c072
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
