# Track-A task: code_generation

Implement the complete HLS kernel from the specification.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `compile_fail`
- Fault/derivation record: `signature_only_generation_stub`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/DSP/fir/decimator
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__dsp_fir_decimator

Optimize the public HLS top function `fir_top` imported from `DSP/fir/decimator`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: f6991ce6dbea75fa94e24e56e910da569702f2f55c247875cbf43e53b06ff471
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
