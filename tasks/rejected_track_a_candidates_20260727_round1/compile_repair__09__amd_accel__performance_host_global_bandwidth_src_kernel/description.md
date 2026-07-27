# Track-A task: compile_repair

Repair the C/C++ compilation failure without changing the interface.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `compile_fail`
- Fault/derivation record: `preprocessor_compile_error`
- Upstream source: https://github.com/Xilinx/Vitis_Accel_Examples/tree/81187602355a7c2b666351154c5acca2074cae64/performance/host_global_bandwidth
- Upstream commit: `81187602355a7c2b666351154c5acca2074cae64`
- License: `MIT`

## Kernel specification

# amd_accel__performance_host_global_bandwidth_src_kernel

Optimize the public HLS top function `bandwidth` imported from `performance/host_global_bandwidth`.

Provenance:
- Source: https://github.com/Xilinx/Vitis_Accel_Examples
- Commit: 81187602355a7c2b666351154c5acca2074cae64
- License: MIT
- Source SHA-256: bf8ef2bf2f9a5ad1c24425649b433334a0cacd69d8571c0ecccee3526001d276
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
