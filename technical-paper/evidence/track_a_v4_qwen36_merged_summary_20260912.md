# Track-A v4 Qwen3.6 merged evidence for paper update

> Superseded by `track_a_v4_paper_data_update_20260913.md` after the final four-task API retry. The historical values below cover only the base run plus the first retry pass.

Status: ready to update the Qwen3.6 row, but not yet ready for a new three-model ranking.

This document merges the 150-task Qwen3.6-27B run with one retry pass over the 15 original infrastructure-error records. A retry record replaces its original record only when the original outcome was `infrastructure_error`. Successful records and the functional failure are not retried or replaced.

## Paper-ready headline results

| Metric | Qwen3.6-27B result | Denominator and interpretation |
| --- | ---: | --- |
| Public-gate completion | 140/150 (93.3%) | All frozen v4 tasks |
| Non-infrastructure conditional completion | 140/141 (99.3%) | Excludes nine unresolved infrastructure errors |
| Evaluator-side hidden correctness | 140/140 (100.0%) | All completed submissions; coverage is 140/150 |
| Reference-anchored official score coverage | 119/150 (79.3%) | Twenty-one additional completed tasks are validity-only |
| Reference-anchored official score | mean 85.82, median 88.63 | Scoreable tasks only, n=119 |
| Submission-side starter-anchored QoR proxy | mean 77.06, median 74.14 | QoR-25 slice, n=24/25 |
| Evaluator-side reference-anchored QoR score | mean 78.56, median 74.96 | QoR-25 slice, n=24/25 |

The four quantities must remain separate in the paper. Public-gate completion is not hidden correctness. The submission proxy is not the official score. A completed validity-only task contributes to completion and hidden correctness, but not to the reference-score mean. Hidden correctness is conditional on reaching the evaluator and is not an independent 150-task success rate; its corpus coverage must be reported beside it. The 85.82 reference mean is also conditional on the 119 scoreable tasks and must not be presented as a zero-imputed whole-corpus average.

## Per-category results

| Category | Completed | Infrastructure error | Functional failure | Reference-scoreable | Validity-only completed | Reference mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Code generation | 24/25 | 1 | 0 | 22 | 2 | 89.36 |
| Compile repair | 22/25 | 3 | 0 | 5 | 17 | 91.60 |
| Functional repair | 20/25 | 4 | 1 | 19 | 1 | 88.83 |
| QoR optimization | 24/25 | 1 | 0 | 24 | 0 | 78.56 |
| Synthesis repair | 25/25 | 0 | 0 | 25 | 0 | 89.92 |
| Structural repair | 25/25 | 0 | 0 | 24 | 1 | 81.97 |

The compile-repair reference mean has only five scoreable tasks and should not be interpreted as a robust category comparison. Its other 17 completed tasks passed validity checks but lack fixed reference anchors.

## QoR-25 slice

The submission-side proxy is reconstructed from the selected submission reports as:

`100 × best_q_hw × max(0.8, 1 − 0.10 × credit utilization − 0.10 × metered tool-time utilization)`

For the 24 available QoR reports, the proxy mean is 77.06, the median is 74.14, and 9/24 exceed 76. The corresponding evaluator-side reference-anchored score has mean 78.56, median 74.96, and 9/24 exceed 76. Task `ta2_qo_022` has neither value because it reached the 900-second task timeout.

Therefore, the current paper statement that all 25 optimization tasks have complete QoR coverage is false for this v4 campaign. It must be changed to 24/25 for Qwen3.6 or deferred until the missing task is resolved under a prespecified policy.

## Failure and retry accounting

The base run produced 131 completed records, 18 infrastructure errors, and one functional failure. The prespecified retry eligibility for this pass was the 15 API-timeout records; three base-run launcher timeouts were not retried. The retry recovered nine eligible tasks and left six infrastructure errors. The merged result is 140 completed, nine infrastructure errors, and one functional failure.

Unresolved infrastructure errors:

- API read timeout: `ta2_cg_012`, `ta2_cr_009`, `ta2_fr_014`, `ta2_fr_020`.
- 900-second task timeout: `ta2_cr_014`, `ta2_cr_015`, `ta2_fr_009`, `ta2_fr_025`, `ta2_qo_022`.

The sole non-infrastructure failure is `ta2_fr_004` with `csim_failed`. A manual diagnostic audit found an over-repair: the model removed the intended off-by-one defect but also changed a static accumulator into a local variable, breaking cross-transaction state. This diagnostic note is not used to compute any aggregate. The record remains a model failure rather than an infrastructure failure.

## Token and cost accounting

| Accounting view | Records | API requests/responses | Failed requests | Observed tokens | Exact-known tokens | Credits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Selected merged records | 150 | 415/411 | 4 | 4,990,950 | 4,930,226 | 2,985 |
| All attempts, including superseded retry inputs | 165 | 454/435 | 19 | 5,284,581 | 4,930,226 | 3,258 |

The observed totals include usage reported by partial records but remain lower bounds because failed requests provide no usage. For a selected-record comparison table, report 4.99M observed tokens. For actual campaign consumption, report at least 5.28M observed tokens. The paper must choose the same policy for every model; it should not present 4.93M as the complete campaign cost.

## Ready-to-paste English evaluation paragraph

On the frozen Track-A v4 corpus, Qwen3.6-27B completed 140 of 150 tasks (93.3%) after one infrastructure-only retry pass. The evaluator accepted all 140 completed kernels under hidden validation, yielding 140/140 hidden correctness with 140/150 corpus coverage. The remaining records comprise nine infrastructure errors and one CSim failure. Reference-anchored scores are available for 119 tasks and average 85.82; 21 additional completed tasks lack fixed anchor metrics and remain validity-only. On the QoR-25 slice, the submission-side starter-anchored proxy averages 77.06 over 24 available reports, while the evaluator-side reference-anchored score averages 78.56 over the same 24 scoreable tasks.

## 可直接粘贴的中文评估段落

在冻结的 Track-A v4 语料上，Qwen3.6-27B 在一次仅针对基础设施错误的重试后完成了 150 个任务中的 140 个，完成率为 93.3%。评估器通过隐藏验证接受了全部 140 个已完成内核，因此隐藏正确性为 140/140，覆盖整个语料的 140/150。其余记录包括 9 个基础设施错误和 1 个 CSim 失败。119 个任务具有 reference-anchored 分数，均值为 85.82；另有 21 个已完成任务由于缺少固定参考锚点而仅计为 validity-only。在 QoR-25 子集上，submission-side starter-anchored proxy 在 24 个可用报告上的均值为 77.06，evaluator-side reference-anchored score 在相同 24 个可评分任务上的均值为 78.56。

## Suggested LaTeX macros

```tex
\newcommand{\QwenThreeSixSuccessCount}{140}
\newcommand{\QwenThreeSixSuccessRate}{93.3\%}
\newcommand{\QwenThreeSixHiddenCorrectCount}{140}
\newcommand{\QwenThreeSixHiddenEvaluatedCount}{140}
\newcommand{\QwenThreeSixReferenceScoreableCount}{119}
\newcommand{\QwenThreeSixValidityOnlyCount}{21}
\newcommand{\QwenThreeSixReferenceMean}{85.82}
\newcommand{\QwenThreeSixQorProxyCount}{24}
\newcommand{\QwenThreeSixQorProxyMean}{77.06}
\newcommand{\QwenThreeSixReferenceQorCount}{24}
\newcommand{\QwenThreeSixReferenceQorMean}{78.56}
\newcommand{\QwenThreeSixSelectedObservedTokensM}{4.99}
\newcommand{\QwenThreeSixAllAttemptObservedTokensM}{5.28}
```

Suggested main-table row, with token policy still to be selected uniformly across models:

```tex
Qwen3.6-27B & 140/150 & 140/140 & [4.99 or 5.28] & 77.06 (24/25) & 78.56 (24/25) \\
```

Suggested category row in the current paper order of code generation, compile repair, synthesis repair, functional repair, structural repair, and QoR optimization:

```tex
Qwen3.6-27B & 24/25 & 22/25 & 25/25 & 20/25 & 25/25 & 24/25 & 77.06 \\
```

## Update boundaries

This evidence can replace the old Qwen3.6 row. It must not be combined with DeepSeek or Qwen3.5 rows obtained from an older corpus release. A new cross-model ranking is justified only after those endpoints are finalized on the same v4 release with the same retry and accounting policy.

At minimum, a later paper synchronization must update `results_generated.tex`, `evaluator_results_generated.tex`, the evaluation narrative, the appendix category table, and any abstract or conclusion sentence that asserts the old ranking or complete 25/25 QoR coverage.

## Provenance

- Frozen release: `releases/track_a_150_v4_20260911`
- Public corpus manifest: `releases/track_a_150_v4_20260911/public_agent/PUBLIC_CORPUS_MANIFEST.json`
- Evaluator mapping: `releases/track_a_150_v4_20260911/evaluator_private/EVALUATOR_MAPPING.json`
- Base shard summaries: `runs/track_a_150_v4_qwen36_full150_20260911_v1/shard_*/shard_summary.json`
- Retry shard summaries: `runs/track_a_150_v4_qwen36_api_timeout15_retry1_20260912/shard_*/shard_summary.json`
- Public tree SHA256: `105e34dbc3ba9e146ae99cb4ce020c65ea5b77d4a87cef6c9674dba04aa4d537`
- Evaluator tree SHA256: `2261ba6c9c874b49c51f3e87870c217e9f241e33d6089fbd5e0ccf267bc4b21e`
- Frozen agent source tree SHA256: `51ebeb770639fa6873e62b93824bad7cb92693537ab7f0ef6862e56ad00c4474`
- Machine-readable companion: `technical-paper/evidence/track_a_v4_qwen36_merged_summary_20260912.json`
- Reproduction script: `tools/summarize_track_a_v4_campaign.py`
