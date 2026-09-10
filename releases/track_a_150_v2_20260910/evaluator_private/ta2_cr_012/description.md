# Track-A v2: compile_repair

Repair the C/C++ compilation failure without changing the interface.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `compile_fail`.

## Kernel specification

# amd_accel__host_xrt_host_memory_copy_kernel_xrt_src_copy_kernel

Optimize the public HLS top function `copy_kernel` imported from `host_xrt/host_memory_copy_kernel_xrt`.

Provenance:
- Source: https://github.com/Xilinx/Vitis_Accel_Examples
- Commit: 81187602355a7c2b666351154c5acca2074cae64
- License: MIT
- Source SHA-256: 107318f10b31cff58cebce460745db3b57496f0b1f2cdf40378c9c381d0e390e
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
