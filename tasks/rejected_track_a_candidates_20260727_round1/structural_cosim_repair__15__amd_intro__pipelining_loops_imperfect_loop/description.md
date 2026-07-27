# Track-A task: structural_cosim_repair

Repair the RTL/CoSim structural behavior while preserving the public C model.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `cosim_fail`
- Fault/derivation record: `synthesis_only_top_early_return:return;:variant=0`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Pipelining/Loops/imperfect_loop
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__pipelining_loops_imperfect_loop

Optimize the public HLS top function `loop_imperfect` imported from `Pipelining/Loops/imperfect_loop`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: a4fd5d35dc7bae2ff2f1a4c40bec4132bc42d7d1146b99124dbb16cfd94e311a
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
