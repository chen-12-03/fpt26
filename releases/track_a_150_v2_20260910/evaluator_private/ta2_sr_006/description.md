# Track-A v2: synthesis_repair

Repair the HLS synthesis failure while preserving behavior.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `synth_fail`.

## Kernel specification

# amd_intro__interface_aggregation_disaggregation_aggregation_of_nested_structs

Optimize the public HLS top function `top` imported from `Interface/Aggregation_Disaggregation/aggregation_of_nested_structs`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 9d032dfae04268b2e009f308c03f7524ce586f2abb12187ee13aa4716c8d8040
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
