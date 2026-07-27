# Track-A task: qor_optimization

Optimize latency/throughput and area while preserving exact functionality.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `valid_unoptimized`
- Fault/derivation record: `removed_performance_pragmas:2`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Array/array_partition_block_cyclic
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__array_array_partition_block_cyclic

Optimize the public HLS top function `matmul_partition` imported from `Array/array_partition_block_cyclic`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: f19625cae10cad2ab205c09369d25464d369f7f27f6fdea459e1069b150f2582
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
