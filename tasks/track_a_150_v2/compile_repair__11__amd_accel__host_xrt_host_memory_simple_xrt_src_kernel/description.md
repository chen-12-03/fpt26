# Track-A v2: compile_repair

Repair the C/C++ compilation failure without changing the interface.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `compile_fail`.

## Kernel specification

# amd_accel__host_xrt_host_memory_simple_xrt_src_kernel

Optimize the public HLS top function `krnl_vadd` imported from `host_xrt/host_memory_simple_xrt`.

Provenance:
- Source: https://github.com/Xilinx/Vitis_Accel_Examples
- Commit: 81187602355a7c2b666351154c5acca2074cae64
- License: MIT
- Source SHA-256: d29a3c64e0ce96c34211863aaba60979180c6cc3199fa9f183adbb57740d07bb
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
