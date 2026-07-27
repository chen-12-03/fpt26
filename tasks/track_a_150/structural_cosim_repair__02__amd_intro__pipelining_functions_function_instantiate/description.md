# Track-A task: structural_cosim_repair

Repair the RTL/CoSim structural behavior while preserving the public C model.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `cosim_fail`
- Fault/derivation record: `synthesis_only_top_early_return:return {};:variant=0`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Modeling/using_float_and_double
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# Track-A task: structural_cosim_repair

Repair the RTL/CoSim structural behavior while preserving the public C model.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `cosim_fail`
- Fault/derivation record: `synthesis_only_top_early_return:return {};:variant=0`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Modeling/using_float_and_double
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__modeling_using_float_and_double

Optimize the public HLS top function `double_mul_pow2` imported from `Modeling/using_float_and_double`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: f58027813c47cd91b386e82aa3c3f6506a9000c7cda38326661fc7a1cf45da49
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
