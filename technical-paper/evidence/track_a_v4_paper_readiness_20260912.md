# Track-A v4 data support descriptive paper revision

> Superseded for final reporting by `track_a_v4_paper_data_update_20260913.md`. The values below preserve the pre-retry readiness decision and must not be used as the final campaign results.

Decision: begin paper optimization now, using the one-attempt base view as the primary three-model comparison. The data support descriptive endpoint results. Causal claims about model weights or individual agent components require added experiments.

## Canonical base-run comparison

Each endpoint receives one attempt on each of the same 150 frozen tasks in this view.

| Model | Public completion | Hidden correctness | Reference mean | Reference coverage | QoR proxy | QoR reference | Observed tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DeepSeek V4 Pro | 143/150 (95.3%) | 143/143 | 84.33 | 120/150 | 74.95 (25/25) | 75.66 (25/25) | 2.13M |
| Qwen3.5-122B-A10B | 129/150 (86.0%) | 129/129 | 85.65 | 108/150 | 77.16 (21/25) | 78.41 (21/25) | 3.86M |
| Qwen3.6-27B | 131/150 (87.3%) | 131/131 | 85.68 | 112/150 | 76.81 (23/25) | 78.33 (23/25) | 4.76M |

The base view contains 403 completed submissions, and every completed submission passes evaluator-side hidden validation. DeepSeek leads base-run completion and uses the fewest observed tokens. The raw QoR means use different task counts, so they require their denominators.

## Common-task QoR comparison

Twenty QoR tasks provide both metrics for all three base runs. This paired subset removes task-availability bias from the endpoint comparison.

| Model | Starter-anchored proxy mean | Reference-anchored score mean | Common tasks |
| --- | ---: | ---: | ---: |
| DeepSeek V4 Pro | 75.11 | 75.85 | 20 |
| Qwen3.5-122B-A10B | 77.40 | 78.59 | 20 |
| Qwen3.6-27B | 76.10 | 77.69 | 20 |

Qwen3.5 has the highest mean on this common subset. One campaign per endpoint limits this statement to the observed run set.

## Qwen3.6 retry view

One infrastructure-only retry pass raises Qwen3.6 completion from 131/150 to 140/150. Its selected-record token count becomes 4.99M, while all attempts consume at least 5.28M observed tokens. Qwen3.5 received no matching retry. The paper may report this result as a supplementary recovery analysis; the primary endpoint table should retain the base-only view.

## Completeness audit

| Evidence item | Status | Assessment |
| --- | --- | --- |
| Frozen corpus | Ready | All models use the same 150-task v4 release and identical public/private tree hashes |
| Exact task coverage | Ready | Each base run contains 150 unique task IDs |
| Hidden correctness | Ready | Every public-completed kernel has a hidden evaluator result |
| QoR-25 submission proxy | Ready | Coverage is 25, 21, and 23 tasks; the common paired subset has 20 tasks |
| QoR-25 reference score | Ready | The same task-level reports support the available-task and common-task views |
| Token accounting | Ready with label | Qwen totals are lower bounds because failed requests omit usage; DeepSeek has exact usage for 320/320 responses |
| Full-corpus reference mean | Ready with denominator | Fixed anchors cover 120, 108, and 112 tasks; completed tasks outside that set remain validity-only |
| Retry fairness | Ready through base view | The base-only table gives one attempt per task; the Qwen3.6 retry belongs in a separate analysis |
| Agent identity | Limited | DeepSeek uses a different source hash; three recorded files differ from the Qwen snapshot |
| Provider-adapter provenance | Limited | The execution snapshot excludes `llm4hls/llm.py`, while the DeepSeek run records disabled thinking |
| Model license evidence | Blocking for compliance claim | All DeepSeek records mark the endpoint alias as unproven |
| Repeated runs | Missing | One campaign per endpoint supplies no variance or confidence interval |
| Component ablations | Missing | Current runs cannot isolate the effects of VCL, QoR-RAG, Failure Reflection, or the promotion score |

## Existing paper claims that must change

- Replace 432 hidden-accepted kernels with 403 for the primary base-run view. A mixed view that uses the Qwen3.6 retry has 412, but that view uses unequal retry policies.
- Replace “Qwen3.6 leads public completion” with “DeepSeek records the highest base-run completion, 143/150.”
- Remove “DeepSeek leads both QoR measures.” Qwen3.5 has the highest mean on the 20-task common subset.
- Replace “Qwen3.5 uses the fewest tokens” with “DeepSeek uses 2.13M observed tokens, the lowest base-run total.”
- Preserve 143/143, 129/129, and 131/131 as conditional hidden correctness, each paired with corpus coverage.
- Preserve reference-score means only with their scoreable-task counts.

## Paper optimization boundary

The results table, evaluation narrative, abstract, introduction, conclusion, and project context can now move to the v4 dataset. Use descriptive language such as “in these campaigns” and keep the base-run comparison primary. Use the 20-task common subset for the cross-model QoR claim.

Before final submission, resolve two provenance items: establish license evidence for the exact DeepSeek endpoint model, and record an immutable hash for the provider adapter. Matched ablations or repeated campaigns remain necessary only if the paper claims causal mechanism gains or model-level superiority. The present evidence already supports a bounded systems result about verified execution across three hosted endpoints.

## Sources of truth

- Canonical machine-readable dataset: `technical-paper/evidence/track_a_v4_three_model_paper_data_20260912.json`
- DeepSeek summary: `technical-paper/evidence/track_a_v4_deepseek_base_summary_20260912.json`
- Qwen3.5 summary: `technical-paper/evidence/track_a_v4_qwen35_base_summary_20260912.json`
- Qwen3.6 base and retry source: `technical-paper/evidence/track_a_v4_qwen36_merged_summary_20260912.json`
- Generator: `tools/build_track_a_v4_paper_data.py`
