# Track-A v2: compile_repair

Repair the C/C++ compilation failure without changing the interface.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `compile_fail`.

## Kernel specification

# amd_intro__interface_memory_manual_burst_manual_burst_example_auto_burst_inference_failure

Optimize the public HLS top function `krnl_transfer` imported from `Interface/Memory/manual_burst/manual_burst_example/auto_burst_inference_failure`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 187d6fdfc5c01931f9e3f2d32c79fd93a8a158e669079272d2bc43ce167904c8
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
