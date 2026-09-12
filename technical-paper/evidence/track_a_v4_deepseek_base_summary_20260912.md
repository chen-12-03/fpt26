# DeepSeek completes 143 of 150 Track-A v4 tasks

Status: paper-readable base-run evidence. The result supports descriptive endpoint claims after the paper states the provider adapter and model-license evidence boundary.

DeepSeek V4 Pro ran once on every task in the frozen Track-A v4 corpus. The run produced 150 unique task records and no API failures.

## Paper-ready headline results

| Metric | DeepSeek V4 Pro result | Denominator and interpretation |
| --- | ---: | --- |
| Public-gate completion | 143/150 (95.3%) | All frozen v4 tasks |
| Non-infrastructure conditional completion | 143/150 (95.3%) | The run has no infrastructure errors |
| Evaluator-side hidden correctness | 143/143 (100.0%) | Conditional on completion; corpus coverage is 143/150 |
| Reference-anchored official score coverage | 120/150 (80.0%) | Twenty-three additional completed tasks are validity-only |
| Reference-anchored official score | mean 84.33, median 88.60 | Scoreable tasks only, n=120 |
| Submission-side starter-anchored QoR proxy | mean 74.95, median 74.34 | QoR-25 slice, n=25/25 |
| Evaluator-side reference-anchored QoR score | mean 75.66, median 74.89 | QoR-25 slice, n=25/25 |

Public-gate completion, evaluator-side hidden correctness, and the two QoR measures describe separate stages. Hidden correctness conditions on the 143 tasks that reached the evaluator. The paper must pair 143/143 with 143/150 corpus coverage. The 84.33 reference mean covers 120 scoreable tasks; the other 23 completed tasks lack fixed reference-anchor metrics.

## Per-category results

| Category | Completed | Infrastructure error | Functional failure | Reference-scoreable | Validity-only completed | Reference mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Code generation | 23/25 | 0 | 2 | 22 | 1 | 89.28 |
| Compile repair | 25/25 | 0 | 0 | 5 | 20 | 88.65 |
| Functional repair | 22/25 | 0 | 3 | 20 | 2 | 88.63 |
| QoR optimization | 25/25 | 0 | 0 | 25 | 0 | 75.66 |
| Synthesis repair | 25/25 | 0 | 0 | 25 | 0 | 89.47 |
| Structural repair | 23/25 | 0 | 2 | 23 | 0 | 78.76 |

Compile repair has five reference-scoreable tasks, so its 88.65 mean needs its sample count. Structural repair has a mean of 78.76, a median of 88.15, and a minimum of 18.47. The paper should report its median beside its mean if space permits.

## QoR-25 slice

The submission-side proxy uses the selected submission report:

`100 × best_q_hw × max(0.8, 1 − 0.10 × credit utilization − 0.10 × metered tool-time utilization)`

All 25 optimization tasks supply both QoR values. The submission proxy has a mean of 74.95 and a median of 74.34; 2/25 exceed 76. The evaluator-side reference score has a mean of 75.66 and a median of 74.89; 3/25 exceed 76.

## Failure accounting

Seven records failed functional gates:

- CSim: `ta2_cg_010`, `ta2_cg_025`, `ta2_fr_009`, `ta2_fr_010`, and `ta2_fr_021`.
- CoSim: `ta2_xr_020` and `ta2_xr_022`.

The run has zero launcher errors, zero API failures, and zero infrastructure-error outcomes. Each of its 320 API requests returned a response.

## Token and cost accounting

| Records | API requests/responses | Failed requests | Observed tokens | Credits | Submission tool calls |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 150 | 320/320 | 0 | 2,128,323 | 2,477 | 654 |

Every response reports usage, so the observed and exact-known token totals agree at 2.13M for this campaign.

## Ready-to-paste English evaluation paragraph

On the frozen Track-A v4 corpus, DeepSeek V4 Pro completes 143 of 150 tasks (95.3%) in one base run. The evaluator accepts all 143 completed kernels under hidden validation, yielding 143/143 hidden correctness with 143/150 corpus coverage. The remaining seven records comprise five CSim failures and two CoSim failures; the campaign records no API or launcher errors. Reference-anchored scores cover 120 tasks and average 84.33, while 23 additional completed tasks remain validity-only. On the QoR-25 slice, all 25 tasks provide both scores: the submission-side starter-anchored proxy averages 74.95, and the evaluator-side reference-anchored score averages 75.66.

## 可直接粘贴的中文评估段落

在冻结的 Track-A v4 语料上，DeepSeek V4 Pro 在一次基础运行中完成了 150 个任务中的 143 个，完成率为 95.3%。评估器通过隐藏验证接受了全部 143 个已完成内核，因此隐藏正确性为 143/143，覆盖整个语料的 143/150。其余 7 个记录包括 5 个 CSim 失败和 2 个 CoSim 失败；本次运行没有 API 或 launcher 错误。120 个任务具有 reference-anchored 分数，均值为 84.33；另有 23 个已完成任务仅计为 validity-only。在 QoR-25 子集上，全部 25 个任务均具有两种分数：submission-side starter-anchored proxy 均值为 74.95，evaluator-side reference-anchored score 均值为 75.66。

## Suggested LaTeX macros

```tex
\newcommand{\DeepSeekSuccessCount}{143}
\newcommand{\DeepSeekSuccessRate}{95.3\%}
\newcommand{\DeepSeekHiddenCorrectCount}{143}
\newcommand{\DeepSeekHiddenEvaluatedCount}{143}
\newcommand{\DeepSeekReferenceScoreableCount}{120}
\newcommand{\DeepSeekValidityOnlyCount}{23}
\newcommand{\DeepSeekReferenceMean}{84.33}
\newcommand{\DeepSeekQorProxyCount}{25}
\newcommand{\DeepSeekQorProxyMean}{74.95}
\newcommand{\DeepSeekReferenceQorCount}{25}
\newcommand{\DeepSeekReferenceQorMean}{75.66}
\newcommand{\DeepSeekObservedTokensM}{2.13}
```

Suggested base-run table row:

```tex
DeepSeek V4 Pro & 143/150 & 143/143 & 2.13 & 74.95 (25/25) & 75.66 (25/25) \\
```

## Protocol and provenance boundaries

- The release has public tree SHA256 `105e34dbc3ba9e146ae99cb4ce020c65ea5b77d4a87cef6c9674dba04aa4d537` and evaluator tree SHA256 `2261ba6c9c874b49c51f3e87870c217e9f241e33d6089fbd5e0ccf267bc4b21e`.
- The recorded agent source tree SHA256 is `e75e42d70b013990ef92642085cb071ce804ae511fde3d61d94b7b3b530fc281`. It differs from both Qwen runs in three recorded files: `agent/integrations/llm/protocol.py`, `agent/reporting/metrics.py`, and `scoring/run_p0_real_api_shard.py`.
- The run contract records temperature 0, 8,192 output tokens, zero client retries, a 360-second LLM timeout, and disabled DeepSeek thinking.
- The source snapshot omits `llm4hls/llm.py`, which implements the provider adapter. The paper must state this provenance limit until a separate immutable hash covers that file.
- All 150 DeepSeek records mark model compliance as unproven because the run uses the endpoint alias `deepseek-v4-pro`, while the local registry recognizes a different model identifier. Resolve the model identity and license evidence before asserting competition compliance.

## Provenance

- Frozen release: `releases/track_a_150_v4_20260911`
- Base run: `runs/track_a_150_v4_deepseek_v4pro_nothink_full150_20260912_v1`
- Shard summaries: `runs/track_a_150_v4_deepseek_v4pro_nothink_full150_20260912_v1/shard_*/shard_summary.json`
- Machine-readable campaign summary: `technical-paper/evidence/track_a_v4_deepseek_base_summary_20260912.json`
- Canonical three-model dataset: `technical-paper/evidence/track_a_v4_three_model_paper_data_20260912.json`
- Reproduction scripts: `tools/summarize_track_a_v4_campaign.py` and `tools/build_track_a_v4_paper_data.py`
