# Third-party notices

The root `LICENSE` covers original repository code only. The frozen Track-A
corpus under `releases/track_a_150_v4_20260911/` contains material from the
projects below. Each corpus file remains under its upstream license. The
repository does not relicense the corpus as MIT.

| Source suite | Tasks | License | Bundled text |
|---|---:|---|---|
| AMD Vitis HLS Introductory Examples | 70 | Apache-2.0 | `LICENSES/Apache-2.0.txt` |
| AMD Vitis Accel Examples | 9 | MIT | `LICENSES/MIT.txt` |
| AMD Vitis HLS Performance Pragma | 1 | Apache-2.0 | `LICENSES/Apache-2.0.txt` |
| C2HLSC | 10 | GPL-3.0-only | `LICENSES/GPL-3.0-only.txt` |
| CHStone SoftFloat-derived kernels | 10 | LicenseRef-CHStone-SoftFloat-2b | `LICENSES/LicenseRef-CHStone-SoftFloat-2b.txt` |
| GNNBuilder | 3 | AGPL-3.0-only | `LICENSES/AGPL-3.0-only.txt` |
| MachSuite | 17 | BSD-3-Clause (16), ISC (AES, 1) | `LICENSES/BSD-3-Clause.txt`, `LICENSES/ISC.txt` |
| PolyBench/C | 26 | LicenseRef-PolyBenchC-OSU | `LICENSES/LicenseRef-PolyBenchC-OSU.txt` |
| pp4fpga examples | 2 | CC-BY-4.0 | `LICENSES/CC-BY-4.0.txt` |
| Rosetta | 2 | BSD-3-Clause | `LICENSES/BSD-3-Clause.txt` |

The evaluator mapping records each task's source path, pinned revision,
digest, and license identifier:

`releases/track_a_150_v4_20260911/evaluator_private/EVALUATOR_MAPPING.json`

The 70 tasks acquired through HLS-Eval are checked against HLS-Eval revision
`e628c0ad9b58d3890fbc350e9b37470cc92bf183`. Attribution follows the original
upstream suite rather than HLS-Eval.

The CHStone entries retain SoftFloat Release 2b notices. The PolyBench/C
entries retain the Ohio State University Software Distribution License. Source
files may contain additional copyright notices that remain in force.

This inventory records provenance and license identifiers. It is not legal
advice.
