# Track-A v2: qor_optimization

Improve latency/throughput and area without changing functionality.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `valid_baseline`.

## Kernel specification

# amd_intro__pipelining_loops_perfect_loop

Optimize the public HLS top function `loop_perfect` imported from `Pipelining/Loops/perfect_loop`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 7eee2b554168a2e0f9b4888f1a39b3f9de5c8fd36f20bdd790d9a3e2c1c20a73
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
