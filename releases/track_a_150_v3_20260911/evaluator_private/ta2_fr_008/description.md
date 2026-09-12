# Track-A v2: functional_repair

Repair the functional defect so all tests pass.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `csim_fail`.

## Kernel specification

# amd_intro__modeling_pointers_stream_better

Optimize the public HLS top function `pointer_stream_better` imported from `Modeling/Pointers/stream_better`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 237912d6a011bb35bffbce6ee91ba84b0de4fb3fb70b7fd327daac2307174036
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
