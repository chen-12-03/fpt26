# Track-A task: compile_repair

Repair the C/C++ compilation failure without changing the interface.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `compile_fail`
- Fault/derivation record: `preprocessor_compile_error`
- Upstream source: https://github.com/Xilinx/Vitis_Accel_Examples/tree/81187602355a7c2b666351154c5acca2074cae64/host_xrt/copy_buffer_xrt
- Upstream commit: `81187602355a7c2b666351154c5acca2074cae64`
- License: `MIT`

## Kernel specification

# amd_accel__host_xrt_copy_buffer_xrt_src_vector_addition

Optimize the public HLS top function `vector_add` imported from `host_xrt/copy_buffer_xrt`.

Provenance:
- Source: https://github.com/Xilinx/Vitis_Accel_Examples
- Commit: 81187602355a7c2b666351154c5acca2074cae64
- License: MIT
- Source SHA-256: d8e6dea60c790bba5d50aba3a686afd22f6dda120394d6f9890309df71e67042
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
