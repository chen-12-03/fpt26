# Track-A v2: qor_optimization

Improve latency/throughput and area without changing functionality.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `valid_baseline`.

## Kernel specification

# amd_intro__pipelining_loops_using_free_running_pipeline

Optimize the public HLS top function `free_pipe_mult` imported from `Pipelining/Loops/using_free_running_pipeline`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: c28b876f27208a0c70179ec4127cbdce7751a1d759859518653f70f4ab171bf3
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
