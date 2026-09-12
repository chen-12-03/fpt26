# Track-A v2: synthesis_repair

Repair the HLS synthesis failure while preserving behavior.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `synth_fail`.

## Kernel specification

# amd_accel__host_xrt_p2p_fpga2fpga_xrt_src_increment

Optimize the public HLS top function `increment` imported from `host_xrt/p2p_fpga2fpga_xrt`.

Provenance:
- Source: https://github.com/Xilinx/Vitis_Accel_Examples
- Commit: 81187602355a7c2b666351154c5acca2074cae64
- License: MIT
- Source SHA-256: 723b1a82c729b71d059479ab61f190a500bca5860fb7ef98e22c1e0c1c213c3e
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
