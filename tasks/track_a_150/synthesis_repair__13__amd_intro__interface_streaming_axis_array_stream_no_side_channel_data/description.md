# Track-A task: synthesis_repair

Repair the HLS synthesis failure while preserving functional behavior.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `synth_fail`
- Fault/derivation record: `synthesis_only_preprocessor_error`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Interface/Streaming/axis_array_stream_no_side_channel_data
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__interface_streaming_axis_array_stream_no_side_channel_data

Optimize the public HLS top function `example` imported from `Interface/Streaming/axis_array_stream_no_side_channel_data`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 091186ac19385a74e67c204bf6274b91a0148df78992ebe4377ae188d748c072
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
