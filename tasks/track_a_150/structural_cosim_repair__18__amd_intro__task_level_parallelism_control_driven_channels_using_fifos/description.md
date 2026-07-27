# Track-A task: structural_cosim_repair

Repair the RTL/CoSim structural behavior while preserving the public C model.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `cosim_fail`
- Fault/derivation record: `synthesis_only_top_early_return:return;:variant=1`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Task_level_Parallelism/Data_driven/using_directio_hs_in_tasks
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# Track-A task: structural_cosim_repair

Repair the RTL/CoSim structural behavior while preserving the public C model.

The top-level function, file names, headers, data types, and interfaces are fixed. Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at least 100 MHz. Hidden tests and the reference implementation are evaluator-only.

- Expected initial state: `cosim_fail`
- Fault/derivation record: `synthesis_only_top_early_return:return;:variant=1`
- Upstream source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples/tree/aa5c160faf5d5ebf58674df8f0591f9984ebae0f/Task_level_Parallelism/Data_driven/using_directio_hs_in_tasks
- Upstream commit: `aa5c160faf5d5ebf58674df8f0591f9984ebae0f`
- License: `Apache-2.0`

## Kernel specification

# amd_intro__task_level_parallelism_data_driven_using_directio_hs_in_tasks

Optimize the public HLS top function `test` imported from `Task_level_Parallelism/Data_driven/using_directio_hs_in_tasks`.

Provenance:
- Source: https://github.com/Xilinx/Vitis-HLS-Introductory-Examples
- Commit: aa5c160faf5d5ebf58674df8f0591f9984ebae0f
- License: Apache-2.0
- Source SHA-256: b19a0f0075451a92836df895bb454e1245b29353764609befd73296a540bf7c0
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
