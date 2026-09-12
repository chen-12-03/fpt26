# Track-A v2: qor_optimization

Improve latency/throughput and area without changing functionality.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `valid_baseline`.

## Kernel specification

# amd_accel__sys_opt_multiple_process_src_krnl_vadd

Optimize the public HLS top function `krnl_vadd` imported from `sys_opt/multiple_process`.

Provenance:
- Source: https://github.com/Xilinx/Vitis_Accel_Examples
- Commit: 81187602355a7c2b666351154c5acca2074cae64
- License: MIT
- Source SHA-256: ece955bc9d3000368ff522e5ebe1c6cafc4a843bc2bfca001d4be4a8e0ffc3ab
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
