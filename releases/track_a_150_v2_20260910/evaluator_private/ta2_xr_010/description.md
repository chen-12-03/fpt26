# Track-A v2: structural_cosim_repair

Repair the C/RTL CoSim mismatch while preserving the public C model.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `cosim_fail`.

## Kernel specification

# amd_intro__modeling_cpp_templates_for_multiple_instances

Optimize the public HLS top function `cpp_template` imported from `Modeling/cpp_templates_for_multiple_instances`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 947b5e33330806a14e6f2e60584c510c3de35bca3869ed3822ff7ed908dece80
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
