# Track-A task: compile_repair

Repair the C/C++ compilation failure without changing the interface.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `compile_fail`
- Fault/derivation record: `preprocessor_compile_error`
- Upstream source: https://github.com/Xilinx/Vitis_Accel_Examples/tree/81187602355a7c2b666351154c5acca2074cae64/host_xrt/p2p_fpga2fpga_xrt
- Upstream commit: `81187602355a7c2b666351154c5acca2074cae64`
- License: `MIT`

## Kernel specification

# amd_accel__host_xrt_p2p_fpga2fpga_xrt_src_increment

Optimize the public HLS top function `increment` imported from `host_xrt/p2p_fpga2fpga_xrt`.

Provenance:
- Source: https://github.com/Xilinx/Vitis_Accel_Examples
- Commit: 81187602355a7c2b666351154c5acca2074cae64
- License: MIT
- Source SHA-256: 723b1a82c729b71d059479ab61f190a500bca5860fb7ef98e22c1e0c1c213c3e
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
