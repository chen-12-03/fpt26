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
- A fresh evaluator checks evaluator-side hidden correctness for all 432
  public-completed final kernels using hidden C simulation, candidate
  synthesis, and required hidden co-simulation.
- Reference-anchored QoR scores use frozen evaluator references. The 25
  optimization tasks have complete reference coverage for all endpoints.

## Headline results

| Endpoint | Public-gate completion | Tokens (M) | Credits | Starter-anchored QoR proxy | Proxy >76 |
|---|---:|---:|---:|---:|---:|
| DeepSeek V4 Pro | 144/150 (96.0%) | 5.87 | 2,617 | 85.5 | 22/25 (88%) |
| Qwen3.5-122B-A10B | 140/150 (93.3%) | 1.68 | 2,375 | 76.3 | 7/25 (28%) |
| Qwen3.6-27B | 148/150 (98.7%) | 1.92 | 2,515 | 79.7 | 15/25 (60%) |

Qwen3.6-27B has the highest public-gate completion rate. DeepSeek V4 Pro has
the highest starter-anchored QoR proxy and uses about 3.1 times as many tokens
as Qwen3.6-27B.
Qwen3.5-122B-A10B uses the fewest tokens.

## Independent evaluator results

| Endpoint | Evaluator-side hidden correctness | Reference-scoreable / 150 | Reference-anchored QoR-25 mean |
|---|---:|---:|---:|
| DeepSeek V4 Pro | 144/144 (100.0%) | 112/150 | 83.11 |
| Qwen3.5-122B-A10B | 140/140 (100.0%) | 109/150 | 70.77 |
| Qwen3.6-27B | 148/148 (100.0%) | 115/150 | 75.33 |

All 432 final kernels that passed the public gate also pass evaluator-side
hidden correctness. The evaluator uses hidden grading for all 432 reports,
and all 450 final-kernel hashes match their submission evidence.

Full-corpus reference means remain unavailable. Some frozen starter/reference
syntheses report data-dependent or missing latency and interval metrics, so
missing scores remain unavailable. On the 106 tasks with valid reference
scores for all endpoints, the comparable means are 84.03 for DeepSeek, 80.48
for Qwen3.5, and 82.20 for Qwen3.6. One Qwen3.5 task passes evaluator-side
hidden correctness but ends with `required_metric_missing` because neither
anchor supplies the required fixed metric.

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
| Starter-anchored QoR proxy | 85.5 | 76.3 | 79.7 |

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
- Versioned evaluator summary: [`technical-paper/evidence/track_a_150_reevaluation_summary.md`](../technical-paper/evidence/track_a_150_reevaluation_summary.md)
- Versioned machine-readable evaluator data: [`technical-paper/evidence/track_a_150_reevaluation_summary.json`](../technical-paper/evidence/track_a_150_reevaluation_summary.json)
- Raw evaluator run tree: [`runs/150_ultimate_evaluator_20260905_v1/`](../runs/150_ultimate_evaluator_20260905_v1/)
- Frozen task manifest: [`tasks/track_a_150/candidate_manifest.json`](../tasks/track_a_150/candidate_manifest.json)
- Generated paper values: [`technical-paper/results_generated.tex`](../technical-paper/results_generated.tex)
- Generated evaluator values: [`technical-paper/evaluator_results_generated.tex`](../technical-paper/evaluator_results_generated.tex)
- Track-A compliance evidence: [`docs/p0-compliance-report.md`](p0-compliance-report.md)

The current paper values are audited directly from the selected
`run_report.json` files. `technical-paper/scripts/update_results.py` targets
future evaluator-generated `final_report.json` inputs and does not regenerate
this submission-side proxy table. Run
`python3 technical-paper/scripts/update_evaluator_results.py` to regenerate the
independent evaluator macros from the machine-readable summary.

All reported campaigns use source snapshot
`0a06af39777b6ae7f3962afa2910232eaf782e91727e0f184ec168f1`, temperature 0,
a 4,096-token output limit, a 180-second request timeout, and at most two
retries.
