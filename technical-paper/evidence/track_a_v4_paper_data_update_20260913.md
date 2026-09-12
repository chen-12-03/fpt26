# Track-A v4 final paper-data update

Status: ready for paper synchronization. This file treats each base campaign and its infrastructure-only retries as one final run result. It updates evidence files only; no paper source file has been changed.

## Reporting policy

- Public-gate completion uses the final selected record for every one of the 150 tasks.
- A retry replaces only an earlier `infrastructure_error` record for the same task.
- API-clean agent completion excludes only unresolved LLM API failures from the denominator.
- The 900-second task timeout remains an agent failure in the API-clean view.
- Evaluator-side hidden correctness is conditional on public-gate completion and includes corpus coverage.
- QoR means always carry the number of scoreable tasks.

## Final three-model results

| Model | Public-gate completion | API-clean agent completion | Hidden correctness | Overall reference score | Selected observed tokens | All-attempt observed tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DeepSeek V4 Pro | 143/150 (95.3%) | 143/150 (95.3%) | 143/143; coverage 143/150 | 84.33, n=120 | 2.128M | 2.128M |
| Qwen3.5-122B-A10B | 140/150 (93.3%) | 140/145 (96.6%) | 140/140; coverage 140/150 | 85.58, n=116 | 3.965M | 4.261M |
| Qwen3.6-27B | 141/150 (94.0%) | 141/147 (95.9%) | 141/141; coverage 141/150 | 85.84, n=120 | 5.044M | 5.398M |

The final campaigns contain 424 public-completed kernels. The hidden evaluator accepts all 424. DeepSeek records the highest raw public-gate completion. After removing only unresolved API failures, Qwen3.5 records the highest API-clean agent completion. These are separate metrics and should appear as separate columns or statements.

Observed token counts are lower bounds for Qwen because failed API calls do not return token usage. Selected-record totals describe the final 150-task result. All-attempt totals describe actual observed campaign consumption, including superseded retry attempts.

## QoR-25 results

| Model | Starter-anchored QoR proxy | Reference-anchored official score | Coverage |
| --- | ---: | ---: | ---: |
| DeepSeek V4 Pro | 74.95 | 75.66 | 25/25 |
| Qwen3.5-122B-A10B | 77.55 | 78.77 | 25/25 |
| Qwen3.6-27B | 77.06 | 78.56 | 24/25 |

Qwen3.5 has complete QoR coverage after retry. Qwen3.6 remains missing `ta2_qo_022` because the task reached the 900-second task timeout; this is not an API failure.

The 24 tasks scoreable for all three models give the paired comparison below.

| Model | Common-task starter proxy | Common-task reference score | Common tasks |
| --- | ---: | ---: | ---: |
| DeepSeek V4 Pro | 74.98 | 75.69 | 24 |
| Qwen3.5-122B-A10B | 77.77 | 78.93 | 24 |
| Qwen3.6-27B | 77.06 | 78.56 | 24 |

Qwen3.5 records the highest mean under both QoR measures on the common 24-task subset.

## Category completion

| Model | Code generation | Compile repair | Synthesis repair | Functional repair | Structural repair | QoR optimization |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DeepSeek V4 Pro | 23/25 | 25/25 | 25/25 | 22/25 | 23/25 | 25/25 |
| Qwen3.5-122B-A10B | 25/25 | 24/25 | 25/25 | 18/25 | 23/25 | 25/25 |
| Qwen3.6-27B | 24/25 | 22/25 | 25/25 | 21/25 | 25/25 | 24/25 |

Functional repair remains the weakest category for both Qwen endpoints. All three endpoints complete every synthesis-repair task.

## Failure accounting

### DeepSeek V4 Pro

- API failures: 0.
- CSim failures: 5 (`ta2_cg_010`, `ta2_cg_025`, `ta2_fr_009`, `ta2_fr_010`, `ta2_fr_021`).
- CoSim failures: 2 (`ta2_xr_020`, `ta2_xr_022`).

### Qwen3.5-122B-A10B

- Unresolved API failures: 5 (`ta2_fr_009`, `ta2_fr_018`, `ta2_fr_022`, `ta2_fr_025`, `ta2_xr_012`).
- 900-second task timeouts: 2 (`ta2_cr_002`, `ta2_fr_021`).
- CSim failures: 2 (`ta2_fr_003`, `ta2_fr_004`).
- CoSim failure: 1 (`ta2_xr_022`).

### Qwen3.6-27B

- Unresolved API failures: 3 (`ta2_cg_012`, `ta2_cr_009`, `ta2_fr_020`).
- 900-second task timeouts: 5 (`ta2_cr_014`, `ta2_cr_015`, `ta2_fr_009`, `ta2_fr_025`, `ta2_qo_022`).
- CSim failure: 1 (`ta2_fr_004`).

## Paper claims supported by the final data

- The three final campaigns complete 424 of 450 task attempts, and all 424 completed kernels pass evaluator-side hidden correctness.
- DeepSeek has the highest raw public-gate completion at 143/150.
- Qwen3.5 has the highest API-clean agent completion at 140/145.
- Qwen3.5 has the highest paired QoR means on the 24-task common subset.
- DeepSeek uses the fewest observed tokens.
- The evidence supports descriptive campaign comparisons. It does not isolate model weights or the causal contribution of individual agent components.

## Evidence provenance

- Frozen corpus: `releases/track_a_150_v4_20260911`
- Canonical machine-readable dataset: `technical-paper/evidence/track_a_v4_three_model_paper_data_20260913.json`
- Qwen3.5 merged summary: `technical-paper/evidence/track_a_v4_qwen35_merged_summary_20260912.json`
- Qwen3.6 merged summary: `technical-paper/evidence/track_a_v4_qwen36_merged_summary_20260912.json`
- DeepSeek summary: `technical-paper/evidence/track_a_v4_deepseek_base_summary_20260912.json`
- Qwen3.5 retry task list: `technical-paper/evidence/qwen35_api_timeout17_postfix_retry_20260912.json`
- Qwen3.6 final retry task list: `technical-paper/evidence/qwen36_api_timeout4_postfix_retry_20260912.json`
- Summary generator: `tools/summarize_track_a_v4_campaign.py`
- Three-model generator: `tools/build_track_a_v4_paper_data.py`

## Deferred paper-source synchronization

The next paper-editing pass should update the result table, evaluation text, abstract, introduction, conclusion, and appendix from this file. This evidence update deliberately leaves `technical-paper/*.tex`, `technical-paper/sections/*.tex`, and generated LaTeX tables unchanged.
