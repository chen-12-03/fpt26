# Track-A task: code_generation

Implement the complete HLS kernel from the specification.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `compile_fail`
- Fault/derivation record: `signature_only_generation_stub`
- Upstream source: https://github.com/Xilinx/Vitis_Accel_Examples/tree/81187602355a7c2b666351154c5acca2074cae64/sys_opt/multiple_process
- Upstream commit: `81187602355a7c2b666351154c5acca2074cae64`
- License: `MIT`

## Kernel specification

# amd_accel__sys_opt_multiple_process_src_krnl_vadd

Optimize the public HLS top function `krnl_vadd` imported from `sys_opt/multiple_process`.

Provenance:
- Source: https://github.com/Xilinx/Vitis_Accel_Examples
- Commit: 81187602355a7c2b666351154c5acca2074cae64
- License: MIT
- Source SHA-256: ece955bc9d3000368ff522e5ebe1c6cafc4a843bc2bfca001d4be4a8e0ffc3ab
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
