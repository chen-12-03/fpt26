# Track-A v2: structural_cosim_repair

Repair the C/RTL CoSim mismatch while preserving the public C model.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `cosim_fail`.

## Kernel specification

# amd_intro__interface_aggregation_disaggregation_aggregation_of_m_axi_ports

Optimize the public HLS top function `dut` imported from `Interface/Aggregation_Disaggregation/aggregation_of_m_axi_ports`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: 04e86539ec8a631d92f80a2995fb3016ab71dacd505398d49b269288aacf09a7
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
