# Track-A task: compile_repair

Repair the C/C++ compilation failure without changing the interface.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `compile_fail`
- Fault/derivation record: `preprocessor_compile_error`
- Upstream source: https://github.com/Xilinx/Vitis_Accel_Examples/tree/81187602355a7c2b666351154c5acca2074cae64/hello_world
- Upstream commit: `81187602355a7c2b666351154c5acca2074cae64`
- License: `MIT`

## Kernel specification

# amd_accel__hello_world_src_vadd

Optimize the public HLS top function `vadd` imported from `hello_world`.

Provenance:
- Source: https://github.com/Xilinx/Vitis_Accel_Examples
- Commit: 81187602355a7c2b666351154c5acca2074cae64
- License: MIT
- Source SHA-256: d077acdbf8eb3a93f928fa00ab71ba9d17a28b3a532c3ed271b42474f5fadc25
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
