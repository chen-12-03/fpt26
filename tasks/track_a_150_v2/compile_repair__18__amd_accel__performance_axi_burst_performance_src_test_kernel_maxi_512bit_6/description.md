# Track-A v2: compile_repair

Repair the C/C++ compilation failure without changing the interface.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `compile_fail`.

## Kernel specification

# amd_accel__performance_axi_burst_performance_src_test_kernel_maxi_512bit_6

Optimize the public HLS top function `test_kernel_maxi_512bit_6` imported from `performance/axi_burst_performance`.

Provenance:
- Source: https://github.com/Xilinx/Vitis_Accel_Examples
- Commit: 81187602355a7c2b666351154c5acca2074cae64
- License: MIT
- Source SHA-256: 3bd743811ef5537dde8d87c88b19b7461e0aecb5948f457f2bebfddc9d42633b
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
