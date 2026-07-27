# Track-A task: functional_repair

Repair the functional defect so all public and hidden tests pass.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `csim_fail`
- Fault/derivation record: `top_early_return:return {};:variant=1`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Misc/initialization_and_reset/static_array_of_struct_with_array_RAM
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__misc_initialization_and_reset_static_array_of_struct_with_array_ram

Optimize the public HLS top function `test` imported from `Misc/initialization_and_reset/static_array_of_struct_with_array_RAM`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: c60513a81282605001b157b19d7e686bbe2b800186f90e3cd7a242501e57537b
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
