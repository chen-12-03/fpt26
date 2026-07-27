# Track-A task: qor_optimization

Optimize latency/throughput and area while preserving exact functionality.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `valid_unoptimized`
- Fault/derivation record: `removed_performance_pragmas:3`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Interface/Streaming/axi_stream_to_master
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__interface_streaming_axi_stream_to_master

Optimize the public HLS top function `example` imported from `Interface/Streaming/axi_stream_to_master`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 6234d6cfef915265768266b16e638b1b54e868eef11e887894b28707f9c13678
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
