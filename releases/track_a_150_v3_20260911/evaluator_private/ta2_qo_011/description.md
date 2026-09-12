# Track-A v2: qor_optimization

Improve latency/throughput and area without changing functionality.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `valid_baseline`.

## Kernel specification

# amd_intro__pipelining_loops_imperfect_loop

Optimize the public HLS top function `loop_imperfect` imported from `Pipelining/Loops/imperfect_loop`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: a4fd5d35dc7bae2ff2f1a4c40bec4132bc42d7d1146b99124dbb16cfd94e311a
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
