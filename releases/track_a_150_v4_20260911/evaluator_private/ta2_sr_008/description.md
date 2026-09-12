# Track-A v2: synthesis_repair

Repair the HLS synthesis failure while preserving behavior.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `synth_fail`.

## Kernel specification

# amd_accel__host_xrt_data_transfer_xrt_src_dummy_kernel

Optimize the public HLS top function `dummy_kernel` imported from `host_xrt/data_transfer_xrt`.

Provenance:
- Source: https://github.com/Xilinx/Vitis_Accel_Examples
- Commit: 81187602355a7c2b666351154c5acca2074cae64
- License: MIT
- Source SHA-256: 688a3aad842644fb37797fb6c5ded16df82034f0f6fac1d06a2c753e693f9324
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
