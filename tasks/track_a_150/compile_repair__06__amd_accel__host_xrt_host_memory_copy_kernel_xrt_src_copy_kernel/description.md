# Track-A task: compile_repair

Repair the C/C++ compilation failure without changing the interface.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `compile_fail`
- Fault/derivation record: `preprocessor_compile_error`
- Upstream source: https://github.com/Xilinx/Vitis_Accel_Examples/tree/81187602355a7c2b666351154c5acca2074cae64/host_xrt/host_memory_copy_kernel_xrt
- Upstream commit: `81187602355a7c2b666351154c5acca2074cae64`
- License: `MIT`

## Kernel specification

# amd_accel__host_xrt_host_memory_copy_kernel_xrt_src_copy_kernel

Optimize the public HLS top function `copy_kernel` imported from `host_xrt/host_memory_copy_kernel_xrt`.

Provenance:
- Source: https://github.com/Xilinx/Vitis_Accel_Examples
- Commit: 81187602355a7c2b666351154c5acca2074cae64
- License: MIT
- Source SHA-256: 107318f10b31cff58cebce460745db3b57496f0b1f2cdf40378c9c381d0e390e
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
