# Track-A task: functional_repair

Repair the functional defect so all public and hidden tests pass.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `csim_fail`
- Fault/derivation record: `top_early_return:return {};:variant=0`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Misc/malloc_removed
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__misc_malloc_removed

Optimize the public HLS top function `malloc_removed` imported from `Misc/malloc_removed`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: b167ea888ba8787338cc8897ed8411cd15fab38c9ee40d0644fcb0d826366689
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
