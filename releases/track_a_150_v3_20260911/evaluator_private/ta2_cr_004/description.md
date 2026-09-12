# Track-A v2: compile_repair

Repair the C/C++ compilation failure without changing the interface.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `compile_fail`.

## Kernel specification

# amd_accel__host_xrt_p2p_simple_xrt_src_adder

Optimize the public HLS top function `adder` imported from `host_xrt/p2p_simple_xrt`.

Provenance:
- Source: https://github.com/Xilinx/Vitis_Accel_Examples
- Commit: 81187602355a7c2b666351154c5acca2074cae64
- License: MIT
- Source SHA-256: 5ac284c0991e7a05dd2da79e767082b7e88248d6d458163ac4379226c7d75942
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
