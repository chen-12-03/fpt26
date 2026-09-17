# Track-A v4 DeepSeek full-run reproduction validation

## Material Passport

- Origin Skill: experiment-agent
- Origin Mode: validate
- Origin Date: 2026-09-17
- Verification Status: VERIFIED
- Version Label: track_a_v4_deepseek_reproduction_v1

## Verdict

- Overall confidence: **CAUTION**
- Paper-level verdict: **REPRODUCIBLE**
- Strict task-level verdict: **PARTIALLY_REPRODUCIBLE**
- Experiment class: stochastic hosted-model output plus environment-sensitive Vitis evaluation
- Symmetric relative-difference tolerance: 5.0%

The rerun reproduces the paper-level completion, score, QoR, token, failure-set, and isolation conclusions. Candidate source is not expected to be byte-identical for a hosted model, so task-level source and score differences are reported separately.

## Aggregate comparison

| Metric | Paper | Rerun | Difference | Status |
|---|---:|---:|---:|---|
| Completed tasks | 143/150 | 144/150 | +1 | within tolerance |
| Reference-score mean | 84.3317 | 84.0109 | -0.3208 | within tolerance |
| QoR-25 reference mean | 75.6556 | 75.6584 | +0.0028 | within tolerance |
| Observed tokens | 2,128,323 | 2,115,160 | -13,163 | within tolerance |
| Tool calls | 654 | 654 | +0 | descriptive |

## Task-level comparison

- Status transitions: `{"completed->completed": 143, "failed->completed": 1, "failed->failed": 6}`
- Common numeric scores: 120
- Exact scores: 60/120
- Absolute score difference <= 0.1: 114/120
- Within 5.0%: 118/120
- Matching final-kernel hashes: 129/150

### Score outliers

| Task | Paper score | Rerun score | Relative difference | Kernel hash |
|---|---:|---:|---:|---|
| ta2_cg_009 | 83.84 | 31.06 | 62.95% | different |
| ta2_xr_023 | 60.44 | 67.92 | 11.01% | different |

### Failure sets

- Paper: `ta2_cg_010, ta2_cg_025, ta2_fr_009, ta2_fr_010, ta2_fr_021, ta2_xr_020, ta2_xr_022`
- Rerun: `ta2_cg_025, ta2_fr_009, ta2_fr_010, ta2_fr_021, ta2_xr_020, ta2_xr_022`
- Recovered: `ta2_cg_010`
- New failures: `none`

## Contract, isolation, and provenance

- LLM contract matches canonical: `true`
- Submission private mount absent in every shard: `true`
- Evaluator private mount present and network disabled in every shard: `true`
- Rerun execution-source hash: `b1d982786b640bf0f54d46d3742f524d62b5f7a0daa5986586ed6949b1659508` (88 files)
- Paper execution-source hash: `e75e42d70b013990ef92642085cb071ce804ae511fde3d61d94b7b3b530fc281` (86 files)
- Repository commit inspected after the run: `fc172820c2f497ad634d41e29bddd9f836770037`; dirty=`true`
- Docker image reference: `fpt26-agent-v3:latest`
- Docker image ID inspected after the run: `sha256:11055bbefde68d3928466c3f8e7ed39f90802c53e18c5e1891ec3e7796132a3a`
- The local image has no registry RepoDigest; the immutable local image ID is recorded instead.
- Git and image metadata were inspected after completion because the historical launcher did not yet embed them in shard summaries.

## Compliance interpretation

- Records with any audit error: 150
- Records whose only audit error is `model_compliance_unproven`: 150
- Records with execution/isolation audit errors: 0

The nonzero launcher status is therefore a model-provenance/compliance result, not evidence that the 150-task execution or HLS evaluation failed.

## Fallacy scan

Coverage: **11/11 checked**

| Fallacy | Status | Assessment |
|---|---|---|
| Simpson's paradox | N/A | All six task categories and the aggregate are retained; no subgroup reversal claim is made. |
| Ecological fallacy | N/A | Claims stay at configuration and task level, not individual or population level. |
| Berkson's paradox | PASS | The comparison uses the complete frozen 150-task corpus rather than outcome-selected tasks. |
| Collider bias | N/A | No regression adjustment or conditioned causal model is used. |
| Base-rate neglect | PASS | Completion and failure counts always retain the full 150-task denominator. |
| Regression to the mean | N/A | Tasks were not selected for rerun based on extreme scores. |
| Survivorship bias | PASS | Failed and completed tasks are both retained in task-level and aggregate results. |
| Look-elsewhere effect | PASS | All task differences and every score outlier are present in the machine-readable report. |
| Garden of forking paths | CAUTION | This is one post-hoc validation campaign; the 5% threshold is the stated protocol default, not an inferential significance boundary. |
| Correlation != causation | PASS | The report makes a reproducibility comparison and no causal model-performance claim. |
| Reverse causality | N/A | No directional observational association is interpreted. |

## Limitations

- This validation is a full 150-task rerun for DeepSeek only; the two Qwen configurations received smoke and targeted checks rather than new full campaigns.
- Hosted-model behavior is stochastic even at temperature zero, so source-code identity is not a valid universal acceptance criterion.
- The historical source snapshot covered the agent but not the harness, launcher, Git state, or image identity; the launcher has been updated for future campaigns.
- No inferential significance claim is made from a single campaign per configuration.

## Inputs

- Canonical JSON: `technical-paper/evidence/track_a_v4_three_model_paper_data_20260913.json` (`a5dcf8653fdbbaa0009f4fa234062bdfb1c76f249c2af7e230cd9f80e89d9d9c`)
- Historical paper run: `runs/track_a_150_v4_deepseek_v4pro_nothink_full150_20260912_v1`
- Rerun: `runs/track_a_v4_deepseek_repro_full150_20260916_v1`
- Machine-readable comparison: `technical-paper/evidence/track_a_v4_deepseek_reproduction_validation_20260917.json`
