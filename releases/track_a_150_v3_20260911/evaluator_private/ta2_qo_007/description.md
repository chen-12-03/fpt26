# Track-A v2: qor_optimization

Improve latency/throughput and area without changing functionality.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `valid_baseline`.

## Kernel specification

# amd_accel__sys_opt_kernel_swap_src_krnl_vmul

Optimize the public HLS top function `krnl_vmul` imported from `sys_opt/kernel_swap`.

Provenance:
- Source: https://github.com/Xilinx/Vitis_Accel_Examples
- Commit: 81187602355a7c2b666351154c5acca2074cae64
- License: MIT
- Source SHA-256: 6f8c9a5c7062ce5a6029952f732a034d4244a1d96f023a6f65faba429f998baf
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
