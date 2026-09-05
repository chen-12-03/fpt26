# Paper Experiment Results

This page preserves the detailed experiment material omitted from the
two-page FPT'26 Track-A short paper. The paper reports the headline findings;
this page provides the benchmark composition, per-category outcomes, cost
accounting, and reproduction pointers in one place.

## Evaluation protocol

- 150 tasks across six balanced HLS capabilities, with 25 tasks per category.
- All tasks require C simulation and synthesis; the 25 structural-repair tasks
  additionally require C/RTL co-simulation.
- Target: AMD Alveo U55C with Vitis 2025.2 and a minimum 100 MHz clock.
- Three hosted endpoints were evaluated under one task manifest and agent
  revision: DeepSeek V4 Pro, Qwen3.5-122B-A10B, and Qwen3.6-27B.
- We report public-gate completion and a starter-anchored QoR proxy from
  submission-side synthesis.
- The proxy uses `100 * Q_HW * E` on the 25 optimization tasks. It excludes
  evaluator-side hidden validation and reference fallback.

## Headline results

| Endpoint | Completed | Tokens (M) | Credits | QoR proxy | Proxy >76 |
|---|---:|---:|---:|---:|---:|
| DeepSeek V4 Pro | 144/150 (96.0%) | 5.87 | 2,617 | 85.5 | 22/25 (88%) |
| Qwen3.5-122B-A10B | 140/150 (93.3%) | 1.68 | 2,375 | 76.3 | 7/25 (28%) |
| Qwen3.6-27B | 148/150 (98.7%) | 1.92 | 2,515 | 79.7 | 15/25 (60%) |

Qwen3.6-27B has the highest completion rate. DeepSeek V4 Pro has the highest
optimization proxy and uses about 3.1 times as many tokens as Qwen3.6-27B.
Qwen3.5-122B-A10B uses the fewest tokens.

## Completion by category

Each category contains 25 tasks.

| Category | DeepSeek V4 Pro | Qwen3.5-122B-A10B | Qwen3.6-27B |
|---|---:|---:|---:|
| Code generation | 22/25 (88%) | 22/25 (88%) | 24/25 (96%) |
| Compile repair | 25/25 (100%) | 25/25 (100%) | 25/25 (100%) |
| Synthesis repair | 25/25 (100%) | 24/25 (96%) | 25/25 (100%) |
| Functional repair | 24/25 (96%) | 24/25 (96%) | 24/25 (96%) |
| Structural repair | 23/25 (92%) | 20/25 (80%) | 25/25 (100%) |
| QoR optimization | 25/25 (100%) | 25/25 (100%) | 25/25 (100%) |
| Optimization QoR proxy | 85.5 | 76.3 | 79.7 |

## Token and credit accounting

| Endpoint | Tokens (M) | Credits |
|---|---:|---:|
| DeepSeek V4 Pro | 5.87 | 2,617 |
| Qwen3.5-122B-A10B | 1.68 | 2,375 |
| Qwen3.6-27B | 1.92 | 2,515 |

## Benchmark composition

| Task type | Tasks | CoSim required |
|---|---:|---:|
| Code generation | 25 | 0 |
| Compile repair | 25 | 0 |
| Synthesis repair | 25 | 0 |
| Functional repair | 25 | 0 |
| Structural repair | 25 | 25 |
| QoR optimization | 25 | 0 |

The suite contains 109 tasks derived from
[Vitis-HLS-Introductory-Examples](https://github.com/Xilinx/Vitis-HLS-Introductory-Examples)
at commit `aa5c160f` and 41 tasks derived from
[Vitis_Accel_Examples](https://github.com/Xilinx/Vitis_Accel_Examples) at
commit `81187602`. The 150 variants reuse 65 unique source paths.

## Evidence and reproduction

- Legacy cross-model summary: [`runs/150_ultimate/CROSS_MODEL_REPORT.md`](../runs/150_ultimate/CROSS_MODEL_REPORT.md). Its DeepSeek QoR lookup used the wrong directory name and is superseded by the audited values above.
- Raw campaign evidence: [`runs/150_ultimate/`](../runs/150_ultimate/)
- Frozen task manifest: [`tasks/track_a_150/candidate_manifest.json`](../tasks/track_a_150/candidate_manifest.json)
- Generated paper values: [`technical-paper/results_generated.tex`](../technical-paper/results_generated.tex)
- Track-A compliance evidence: [`docs/p0-compliance-report.md`](p0-compliance-report.md)

The current paper values are audited directly from the selected
`run_report.json` files. `technical-paper/scripts/update_results.py` targets
future evaluator-generated `final_report.json` inputs and does not regenerate
this submission-side proxy table.

All reported campaigns use source snapshot
`0a06af39777b6ae7f3962afa2910232eaf782e91727e0f184ec168f1`, temperature 0,
a 4,096-token output limit, a 180-second request timeout, and at most two
retries.
