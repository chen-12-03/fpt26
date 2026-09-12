# Qwen3.5 completes 129 of 150 Track-A v4 tasks before retry

Status: paper-readable single-campaign evidence. Apply the same infrastructure retry policy before using this result in a cross-model ranking.

Qwen3.5-122B-A10B ran once on all 150 tasks in the frozen Track-A v4 corpus. This report contains the base run only because no Qwen3.5 retry run exists.

## Paper-ready headline results

| Metric | Qwen3.5-122B-A10B result | Denominator and interpretation |
| --- | ---: | --- |
| Public-gate completion | 129/150 (86.0%) | All frozen v4 tasks |
| Non-infrastructure conditional completion | 129/131 (98.5%) | Excludes 19 infrastructure errors |
| Evaluator-side hidden correctness | 129/129 (100.0%) | Conditional on completion; corpus coverage is 129/150 |
| Reference-anchored official score coverage | 108/150 (72.0%) | Twenty-one additional completed tasks are validity-only |
| Reference-anchored official score | mean 85.65, median 88.63 | Scoreable tasks only, n=108 |
| Submission-side starter-anchored QoR proxy | mean 77.16, median 74.34 | QoR-25 slice, n=21/25 |
| Evaluator-side reference-anchored QoR score | mean 78.41, median 74.89 | QoR-25 slice, n=21/25 |

Public-gate completion, evaluator-side hidden correctness, submission-side starter-anchored QoR proxy, and reference-anchored QoR score measure different stages. Hidden correctness conditions on the 129 tasks that reached the evaluator, so the paper must pair 129/129 with its 129/150 corpus coverage. The 85.65 reference mean covers 108 scoreable tasks; a whole-corpus mean would require an explicit missing-value policy.

## Per-category results

| Category | Completed | Infrastructure error | Functional failure | Reference-scoreable | Validity-only completed | Reference mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Code generation | 24/25 | 1 | 0 | 21 | 3 | 91.08 |
| Compile repair | 22/25 | 3 | 0 | 4 | 18 | 91.98 |
| Functional repair | 17/25 | 7 | 1 | 17 | 0 | 88.84 |
| QoR optimization | 21/25 | 4 | 0 | 21 | 0 | 78.41 |
| Synthesis repair | 23/25 | 2 | 0 | 23 | 0 | 90.39 |
| Structural repair | 22/25 | 2 | 1 | 22 | 0 | 78.82 |

Compile repair has only four reference-scoreable tasks. Its 91.98 mean therefore supports no stable category comparison. Functional repair has the lowest completion, with 17 completed tasks, seven infrastructure errors, and one CSim failure. Structural repair has a mean of 78.82, a median of 88.25, and a minimum of 18.47 on `ta2_xr_024`; report its median beside its mean.

## QoR-25 slice

The submission-side proxy uses the selected submission reports:

`100 × best_q_hw × max(0.8, 1 − 0.10 × credit utilization − 0.10 × metered tool-time utilization)`

The 21 available proxy reports yield a mean of 77.16 and a median of 74.34; 6/21 exceed 76. The same 21 tasks have evaluator-side reference scores with a mean of 78.41 and a median of 74.89; 10/21 exceed 76. Four optimization tasks lack both values because their runs ended with API errors: `ta2_qo_009`, `ta2_qo_010`, `ta2_qo_011`, and `ta2_qo_013`.

## Failure accounting

The 21 non-completed records consist of 19 infrastructure errors and two model failures.

- Seventeen records ended with API read timeouts. Fifteen expose the timeout in the stop reason; two use `all_api_requests_failed` as the aggregate stop reason and retain `TimeoutError` in their LLM failure records.
- Two records reached the 900-second task timeout.
- `ta2_fr_003` failed CSim.
- `ta2_xr_022` failed CoSim.

The first two groups count as infrastructure failures. The final two records remain model failures. The run contains 17 API-failure records that match the retry class used for Qwen3.6.

## Token and cost accounting

| Records | API requests/responses | Failed requests | Observed tokens | Exact-known tokens | Credits | Submission tool calls |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 150 | 424/407 | 17 | 3,863,170 | 3,567,473 | 2,853 | 821 |

The observed total includes usage from partial records but remains a lower bound because failed requests return no usage. The paper should report 3.86M observed tokens if every model uses this accounting policy. The 3.57M exact-known subtotal omits partial-response usage and understates campaign consumption.

## Ready-to-paste English evaluation paragraph

On the frozen Track-A v4 corpus, Qwen3.5-122B-A10B completes 129 of 150 tasks (86.0%) in its base run. The evaluator accepts all 129 completed kernels under hidden validation, yielding 129/129 hidden correctness with 129/150 corpus coverage. The remaining records comprise 19 infrastructure errors, one CSim failure, and one CoSim failure. Reference-anchored scores cover 108 tasks and average 85.65; 21 additional completed tasks lack fixed anchor metrics and remain validity-only. On the QoR-25 slice, the submission-side starter-anchored proxy averages 77.16 over 21 available reports, while the evaluator-side reference-anchored score averages 78.41 over the same 21 tasks.

## 可直接粘贴的中文评估段落

在冻结的 Track-A v4 语料上，Qwen3.5-122B-A10B 在基础运行中完成了 150 个任务中的 129 个，完成率为 86.0%。评估器通过隐藏验证接受了全部 129 个已完成内核，因此隐藏正确性为 129/129，覆盖整个语料的 129/150。其余记录包括 19 个基础设施错误、1 个 CSim 失败和 1 个 CoSim 失败。108 个任务具有 reference-anchored 分数，均值为 85.65；另有 21 个已完成任务因缺少固定参考锚点而仅计为 validity-only。在 QoR-25 子集上，submission-side starter-anchored proxy 在 21 个可用报告上的均值为 77.16，evaluator-side reference-anchored score 在相同 21 个任务上的均值为 78.41。

## Suggested LaTeX macros

```tex
\newcommand{\QwenThreeFiveSuccessCount}{129}
\newcommand{\QwenThreeFiveSuccessRate}{86.0\%}
\newcommand{\QwenThreeFiveHiddenCorrectCount}{129}
\newcommand{\QwenThreeFiveHiddenEvaluatedCount}{129}
\newcommand{\QwenThreeFiveReferenceScoreableCount}{108}
\newcommand{\QwenThreeFiveValidityOnlyCount}{21}
\newcommand{\QwenThreeFiveReferenceMean}{85.65}
\newcommand{\QwenThreeFiveQorProxyCount}{21}
\newcommand{\QwenThreeFiveQorProxyMean}{77.16}
\newcommand{\QwenThreeFiveReferenceQorCount}{21}
\newcommand{\QwenThreeFiveReferenceQorMean}{78.41}
\newcommand{\QwenThreeFiveObservedTokensM}{3.86}
```

Suggested single-campaign table row:

```tex
Qwen3.5-122B-A10B & 129/150 & 129/129 & 3.86 & 77.16 (21/25) & 78.41 (21/25) \\
```

Suggested category row in the paper order of code generation, compile repair, synthesis repair, functional repair, structural repair, and QoR optimization:

```tex
Qwen3.5-122B-A10B & 24/25 & 22/25 & 23/25 & 17/25 & 22/25 & 21/25 & 77.16 \\
```

## Cross-model comparison boundary

Qwen3.6 received one retry pass over its eligible API failures; Qwen3.5 has no retry result. The paper can report this Qwen3.5 run as a single-campaign result, but a completion ranking against post-retry Qwen3.6 uses unequal retry policies. Applying the same rule would make 17 Qwen3.5 records eligible for one retry. Keep these values labeled as base-run or pre-retry until the experiment protocol settles that decision.

## Provenance

- Frozen release: `releases/track_a_150_v4_20260911`
- Public corpus manifest: `releases/track_a_150_v4_20260911/public_agent/PUBLIC_CORPUS_MANIFEST.json`
- Evaluator mapping: `releases/track_a_150_v4_20260911/evaluator_private/EVALUATOR_MAPPING.json`
- Shard summaries: `runs/track_a_150_v4_qwen35_full150_20260912_v1/shard_*/shard_summary.json`
- Public tree SHA256: `105e34dbc3ba9e146ae99cb4ce020c65ea5b77d4a87cef6c9674dba04aa4d537`
- Evaluator tree SHA256: `2261ba6c9c874b49c51f3e87870c217e9f241e33d6089fbd5e0ccf267bc4b21e`
- Frozen agent source tree SHA256: `51ebeb770639fa6873e62b93824bad7cb92693537ab7f0ef6862e56ad00c4474`
- Machine-readable companion: `technical-paper/evidence/track_a_v4_qwen35_base_summary_20260912.json`
- Reproduction script: `tools/summarize_track_a_v4_campaign.py`
