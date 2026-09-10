# Track-A v2: synthesis_repair

Repair the HLS synthesis failure while preserving behavior.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `synth_fail`.

## Kernel specification

# amd_intro__dsp_fir_decimator

Optimize the public HLS top function `fir_top` imported from `DSP/fir/decimator`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: f6991ce6dbea75fa94e24e56e910da569702f2f55c247875cbf43e53b06ff471
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
