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
- Scores use `S = 100 * V(c) * Q_HW * E`; optimization-only means are reported
  separately from the headline estimated means.

## Headline results

| Endpoint | Completed | Tokens (M) | Credits | Estimated mean | >76 rate |
|---|---:|---:|---:|---:|---:|
| DeepSeek V4 Pro | 144/150 (96.0%) | 5.87 | 2,617 | 70.6 | 3/144 (2%) |
| Qwen3.5-122B-A10B | 140/150 (93.3%) | 1.68 | 2,375 | 74.0 | 7/140 (5%) |
| Qwen3.6-27B | 148/150 (98.7%) | 1.92 | 2,515 | 74.6 | 15/148 (10%) |

Qwen3.6-27B has the highest completion rate and the best optimization-only
mean. Qwen3.5-122B-A10B uses the fewest tokens. DeepSeek V4 Pro uses about
3.1 times as many tokens as Qwen3.6-27B while producing a lower
optimization-only mean.

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
| Optimization-only mean | 56.1 | 75.4 | 79.0 |

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

- Cross-model summary: [`runs/150_ultimate/CROSS_MODEL_REPORT.md`](../runs/150_ultimate/CROSS_MODEL_REPORT.md)
- Raw campaign evidence: [`runs/150_ultimate/`](../runs/150_ultimate/)
- Frozen task manifest: [`tasks/track_a_150/candidate_manifest.json`](../tasks/track_a_150/candidate_manifest.json)
- Generated paper values: [`technical-paper/results_generated.tex`](../technical-paper/results_generated.tex)
- Track-A compliance evidence: [`docs/p0-compliance-report.md`](p0-compliance-report.md)

Regenerate the paper macros from the repository root:

```bash
python3 technical-paper/scripts/update_results.py
```

All reported campaigns use source snapshot
`0a06af39777b6ae7f3962afa2910232eaf782e91727e0f184ec168f1`, temperature 0,
a 4,096-token output limit, a 180-second request timeout, and at most two
retries.
