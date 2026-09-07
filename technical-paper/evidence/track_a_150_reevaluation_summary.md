# Track-A 150 final-kernel independent reevaluation

- Generated: 2026-09-05T15:26:13.062238+00:00
- Evaluator: Vitis 2025.2, xcu55c-fsvh2892-2L-e, hidden grading source
- Scope: evaluator ran only for the 432 kernels that completed the original public gate; 18 public failures were not evaluated.

## Independent metrics

| Model | Public gate | Submission proxy (QoR-25) | Hidden correct / evaluated | Reference-scoreable / 150 | Reference mean (scoreable only) | Reference QoR-25 mean |
|---|---:|---:|---:|---:|---:|---:|
| DeepSeek V4 Pro | 144/150 (96.0%) | 85.5 | 144/144 (100.0%) | 112/150 | 81.78 | 83.11 |
| Qwen3.5-122B-A10B | 140/150 (93.3%) | 76.3 | 140/140 (100.0%) | 109/150 | 79.89 | 70.77 |
| Qwen3.6-27B | 148/150 (98.7%) | 79.7 | 148/148 (100.0%) | 115/150 | 79.50 | 75.33 |

## Interpretation

- Public-gate completion and the submission proxy are reconstructed from the original submission reports. The proxy exactly reproduces the paper values (85.5, 76.3, 79.7).
- Fresh hidden evaluation found no additional functional failures: all 432 evaluated kernels passed hidden CSim, candidate synthesis, and required hidden CoSim.
- Reference-anchored scoring is incomplete on the full corpus because many starter/reference syntheses report data-dependent or missing latency/interval. Missing scores are marked unavailable, not estimated or silently treated as zero.
- On the 106 tasks with valid reference scores for all three models, the comparable means are DeepSeek 84.03, Qwen3.5 80.48, and Qwen3.6 82.20.
- The comparable QoR-25 slice is fully reference-scoreable for all three models: DeepSeek 83.11, Qwen3.5 70.77, Qwen3.6 75.33.
- One Qwen3.5 evaluator report has status failed / required_metric_missing despite hidden correctness passing; neither starter nor reference supplied the required fixed metric.

## Audit

- 450/450 final-kernel SHA-256 values match their submission evidence.
- 432/432 evaluator reports use grading source hidden.
- Original runs/150_ultimate was not modified.

## Files

- Per-task and aggregate machine-readable data: REEVALUATION_SUMMARY.json
- Raw evaluator reports: model/category/task/run_report.json
- Batch launcher logs: model/category/task/launcher.log (429 files; the 3 preflight gate samples were captured by the launcher session)
