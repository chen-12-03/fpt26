# Paper Experiment Results

This page preserves the detailed Track-A v4 results omitted from the two-page
FPT'26 short paper. Values come from the canonical dataset generated on
2026-09-13.

## Reporting policy

- Each deployed configuration contains one final record for every one of the
  150 frozen tasks.
- The deterministic retry rule applies only when the currently selected record
  is an LLM-API infrastructure error; the chronological retry replaces it
  regardless of retry outcome. Validation failures and 900-second task
  timeouts are ineligible.
- Public completion keeps all 150 tasks in the denominator.
- API-conditioned completion excludes only unresolved LLM API-call records;
  task timeouts and validation failures remain in the denominator.
- Hidden-gate pass conditions on public completion and does not certify general
  correctness.
- Cross-endpoint QoR comparisons use the same 24 scoreable tasks.
- Qwen token totals are lower bounds because failed calls omit usage.

## Final campaign results

| Configuration | Public completion | API-conditioned completion | Conditional hidden-gate pass | Selected tokens | All-attempt tokens |
|---|---:|---:|---:|---:|---:|
| DeepSeek V4 Pro | 143/150 (95.3%) | 143/150 (95.3%) | 143/143 | 2.128M | 2.128M |
| Qwen3.5-122B-A10B | 140/150 (93.3%) | 140/145 (96.6%) | 140/140 | >=3.965M | >=4.261M |
| Qwen3.6-27B | 141/150 (94.0%) | 141/147 (95.9%) | 141/141 | >=5.044M | >=5.398M |

The first-pass public-completion counts were 143, 129, and 131; 0, 17, and 19
eligible retry records produced the final counts shown above. All 424 final
outputs that pass the public gate also pass the evaluator's finite hidden-gate
suite; the other 26 endpoint--task runs are outside that denominator. DeepSeek
has the largest raw-completion point estimate and lowest observed token total;
Qwen3.5 has the largest API-conditioned point estimate. These metrics answer
different questions and are not merged or relabelled.

## Paired QoR comparison

| Configuration | Starter-anchored proxy mean | Reference-anchored mean | Common tasks |
|---|---:|---:|---:|
| DeepSeek V4 Pro | 74.98 | 75.69 | 24 |
| Qwen3.5-122B-A10B | 77.77 | 78.93 | 24 |
| Qwen3.6-27B | 77.06 | 78.56 | 24 |

Qwen3.5 has the largest point estimate under both anchors on the paired subset;
its reference mean exceeds Qwen3.6 by 0.37. With one campaign per
configuration, there is no uncertainty interval or stable-ranking claim.

## Available-task score coverage

| Configuration | Reference-scoreable | Reference mean | QoR available | Starter proxy | Reference QoR |
|---|---:|---:|---:|---:|---:|
| DeepSeek V4 Pro | 120/150 | 84.33 | 25/25 | 74.95 | 75.66 |
| Qwen3.5-122B-A10B | 116/150 | 85.58 | 25/25 | 77.55 | 78.77 |
| Qwen3.6-27B | 120/150 | 85.84 | 24/25 | 77.06 | 78.56 |

These raw means use different denominators and are not the primary
cross-endpoint QoR ranking. Qwen3.6 task ta2_qo_022 remains unavailable after a
900-second task timeout. Completed tasks without fixed reference metrics remain
validity-only rather than receiving an imputed zero.

## Completion by category

Each category contains 25 tasks.

| Category | DeepSeek V4 Pro | Qwen3.5-122B-A10B | Qwen3.6-27B |
|---|---:|---:|---:|
| Code generation | 23/25 | 25/25 | 24/25 |
| Compile repair | 25/25 | 24/25 | 22/25 |
| Synthesis repair | 25/25 | 25/25 | 25/25 |
| Functional repair | 22/25 | 18/25 | 21/25 |
| Structural repair | 23/25 | 23/25 | 25/25 |
| QoR optimization | 25/25 | 25/25 | 24/25 |

Functional repair remains the weakest category for both Qwen endpoints. All
three endpoints complete every synthesis-repair task.

## Token, credit, and request accounting

| Configuration | Requests/responses | Failed requests | Selected tokens | All-attempt tokens | Selected credits | Tool calls |
|---|---:|---:|---:|---:|---:|---:|
| DeepSeek V4 Pro | 320/320 | 0 | 2,128,323 | 2,128,323 | 2,477 | 654 |
| Qwen3.5-122B-A10B | 422/417 | 5 | >=3,964,982 | >=4,260,679 | 2,895 | 839 |
| Qwen3.6-27B | 417/414 | 3 | >=5,044,095 | >=5,398,450 | 2,995 | 860 |

Selected totals describe the final 150 records; all-attempt totals include
superseded retry attempts. DeepSeek usage is exact for all responses.

## Remaining failures

- DeepSeek: five CSim failures and two CoSim failures; no API failure.
- Qwen3.5: five unresolved API failures, two task timeouts, two CSim failures,
  and one CoSim failure.
- Qwen3.6: three unresolved API failures, five task timeouts, and one CSim
  failure.

## Frozen corpus

The Track-A v4 release contains six balanced 25-task categories. All tasks
require C simulation and synthesis; the 25 structural-repair tasks additionally
require C/RTL co-simulation.

| Upstream repository | Tasks | Commit |
|---|---:|---|
| sharc-lab/hls-eval | 70 | e628c0ad |
| Xilinx/Vitis-HLS-Introductory-Examples | 70 | aa5c160f |
| Xilinx/Vitis_Accel_Examples | 9 | 81187602 |
| Xilinx/Vitis-HLS-Performance-Pragma | 1 | 7ca88131 |

Public tree SHA256:
105e34dbc3ba9e146ae99cb4ce020c65ea5b77d4a87cef6c9674dba04aa4d537.
Evaluator tree SHA256:
2261ba6c9c874b49c51f3e87870c217e9f241e33d6089fbd5e0ccf267bc4b21e.

## Evidence and limitations

- [Canonical 2026-09-13 paper data](../technical-paper/evidence/track_a_v4_three_model_paper_data_20260913.json)
- [Human-readable final update](../technical-paper/evidence/track_a_v4_paper_data_update_20260913.md)
- [Qwen3.5 merged summary](../technical-paper/evidence/track_a_v4_qwen35_merged_summary_20260912.json)
- [Qwen3.6 merged summary](../technical-paper/evidence/track_a_v4_qwen36_merged_summary_20260912.json)
- [DeepSeek summary](../technical-paper/evidence/track_a_v4_deepseek_base_summary_20260912.json)
- [Frozen release](../releases/track_a_150_v4_20260911/)
- [Paper-data generator](../tools/build_track_a_v4_paper_data.py)
- [Campaign summarizer](../tools/summarize_track_a_v4_campaign.py)

The frozen corpus, timeout, token limit, temperature, tool timeouts, and
deterministic replacement rule are matched. Retry counts differ because the
configurations produced different eligible failures. The snapshots match in
83/86 tracked files, including controller, prompts, gates, and scoring. The
three differences concern provider/run-contract, metric-recording, and
runner/record-validation plumbing; the latter also resolves provider reasoning
mode. The execution snapshot omits the provider adapter, so neutrality cannot
be established, and immutable license evidence for the exact DeepSeek endpoint
identity is not archived. Repeated campaigns, sensitivity analysis, and
matched component ablations are absent. Accordingly, claims remain descriptive
at the deployed-configuration level.
