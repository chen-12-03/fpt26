# Track-A 150 v2: third-party source notice

This corpus contains source and test material derived from the projects below.
Task-level `task.toml` files in the evaluator corpus pin the acquisition path,
revision, source digest, normalization, and license-evidence URL.  The public
agent bundle carries this notice but omits exact source paths and revisions to
prevent answer lookup during evaluation.

| Source suite | Tasks | Declared license | Upstream project |
|---|---:|---|---|
| AMD Vitis HLS Introductory Examples | 70 | Apache-2.0 | https://github.com/Xilinx/Vitis-HLS-Introductory-Examples |
| AMD Vitis Accel Examples | 9 | MIT | https://github.com/Xilinx/Vitis_Accel_Examples |
| AMD Vitis HLS Performance Pragma | 1 | Apache-2.0 | https://github.com/Xilinx/Vitis-HLS-Performance-Pragma |
| C2HLSC | 10 | GPL-3.0-only | https://github.com/Lucaz97/c2hlsc |
| CHStone SoftFloat-derived kernels | 10 | LicenseRef-CHStone-SoftFloat-2b | https://github.com/ferrandi/CHStone |
| GNNBuilder | 3 | AGPL-3.0-only | https://github.com/sharc-lab/gnn-builder |
| MachSuite | 17 | BSD-3-Clause (16), ISC (AES, 1) | https://github.com/breagen/MachSuite |
| PolyBench/C | 26 | LicenseRef-PolyBenchC-OSU | https://github.com/ferrandi/PolyBenchC |
| pp4fpga examples | 2 | CC-BY-4.0 | https://github.com/KastnerRG/pp4fpgas |
| Rosetta | 2 | BSD-3-Clause | https://github.com/cornell-zhang/rosetta |

The 70 tasks acquired through HLS-Eval are byte-checked (after recorded newline
normalization) against HLS-Eval revision
`e628c0ad9b58d3890fbc350e9b37470cc92bf183`; license attribution is to each
original upstream suite, not to HLS-Eval itself.

The CHStone entries selected here originate from SoftFloat Release 2b and must
retain its copyright and permission notice.  PolyBench/C uses the license text
shipped in its pinned upstream repository rather than a guessed SPDX license.
See the evaluator-side provenance manifest for the exact evidence links.

This inventory is an engineering provenance record, not legal advice.  A
redistribution release must include the corresponding complete upstream
license texts and notices and must be reviewed for license compatibility.
