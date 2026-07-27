# Track-A task: synthesis_repair

Repair the HLS synthesis failure while preserving functional behavior.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `synth_fail`
- Fault/derivation record: `synthesis_only_preprocessor_error`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Interface/Register/using_axi_lite_with_user_defined_offset
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__interface_register_using_axi_lite_with_user_defined_offset

Optimize the public HLS top function `example` imported from `Interface/Register/using_axi_lite_with_user_defined_offset`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 8234b2c081921dd9bec2a4fb5eacbb7cfecc1eb3daa96e851c0d1e26300b86ad
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
