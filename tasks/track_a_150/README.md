# Track-A 150-task corpus

This directory contains a six-way, 150-task Track-A benchmark:

- `code_generation`: 25
- `compile_repair`: 25
- `synthesis_repair`: 25
- `functional_repair`: 25
- `structural_cosim_repair`: 25
- `qor_optimization`: 25

Every package contains `task.toml`, `description.md`, a public baseline kernel,
fixed headers (when required), a public testbench, evaluator-only `hidden/`,
evaluator-only `reference/`, and fixed-commit provenance.

All source kernels come from the AMD/Xilinx
`Vitis-HLS-Introductory-Examples` (Apache-2.0) or
`Vitis_Accel_Examples` (MIT) repositories. A kernel family is assigned to
exactly one category; controlled fault variants may repeat only inside that
category.

`candidate_manifest.json` describes the constructed corpus. A task is not part
of the frozen accepted set until its U55C/Vitis 2025.2 evidence checkpoint
passes every applicable gate and it appears in the separately generated
`accepted_manifest.json`.

The submission role must receive only public files. `hidden/` and `reference/`
are loaded only by the evaluator role.
