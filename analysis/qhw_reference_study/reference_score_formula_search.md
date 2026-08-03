## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: validate
- Origin Date: 2026-08-03
- Verification Status: VERIFIED
- Version Label: reference_score_formula_search_v1

# Formula search: all 36 source-different references above 75

## Result

- Required pairs above 75: **36/36**
- Minimum final score: **75.2481**
- Mean / median / maximum: **80.36 / 75.75 / 99.89**
- Hardware-identical but source-different pairs: **7**
- Starter-dominates-reference pairs: **6**
- Starter-invalid/reference-valid pairs: **7**
- API calls: **0**
- Production scorer modified: **no**

## Impossibility boundary

A symmetric monotone score using only latency, II, and resource metrics cannot satisfy the requirement: seven pairs have identical synthesized hardware metrics despite different source, and six synthesis-valid pairs are starter-dominant. Such a formula must return 75 for the former and no more than 75 for the latter. Strictly exceeding 75 therefore requires an explicit non-hardware source-change term and one-sided treatment of improvement evidence.

## Recommended formula

This is a **reference-validation score**, not a general candidate QoR score:

`U(R) = sum(R_r/C_r)`

`A = (U_starter + 1e-12)/(U_reference + 1e-12); else 1`

`R+ = 1.01^D * 2^F * max(1,P)^0.55 * max(1,A)^0.45`

`S_ref = 100 * V_ref * (1 - 1/(1 + R+)^2)`

`D` proves that the two submitted source hashes differ. `F` marks a valid reference that repairs an invalid starter. Regressions are retained in the audit table but clipped out of this one-sided evidence score; without that relaxation the stated 36/36 condition is mathematically impossible.

## Formula-family comparison

| Formula family | 36/36 >75 | Source-only score | Decision |
|---|---:|---:|---|
| Symmetric hardware QoR | No | 75.00 | Reject: contradicts the requirement |
| Signed QoR + fitted global margin | Yes | 96.97 | Reject: requires 4.74x fitted bias |
| Positive evidence + 1.01x source proof | Yes | 75.25 | **Recommend for reference validation** |

## Metric/formula comparison

| Component | Current symmetric qhw | Recommended reference-validation score |
|---|---|---|
| Validity | Invalid candidate → 0; invalid starter falls back to reference anchor | Reference invalid → 0; starter invalid/reference valid contributes `2^F` |
| Performance | Signed `P^0.55`; regressions reduce score | `max(1,P)^0.55`; only verified improvement adds evidence |
| Resources | `1/max(per-resource count growth)` | `U=sum(R/C)`, then `max(1,U_s/U_r)^0.45` |
| Zero resource transition | Per-type floor can create abrupt ratios | Total capacity-normalized footprint has no per-type zero denominator |
| Source difference | Not scored | Minimal `1.01^D` proof term |
| Neutral identity | Hardware identity = 75 | Source identity and no evidence = 75; source-different valid reference ≥75.248 |
| Regressions | Penalized | Reported separately, not subtracted |
| Intended use | General candidate QoR | Frozen reference/pair validation only |

## All 36 metric and score rows

Resource vector order is `LUT/FF/DSP/BRAM_18K/URAM`. `P` and `A` default to 1 only when the corresponding starter anchor metric is unavailable.

| # | Task | Valid S→R | L S→R | II S→R | Resources S→R | P | A | D/F | Current | Final | Pareto |
|---:|---|---|---|---|---|---:|---:|---|---:|---:|---|
| 1 | `array_array_partition_block_cyclic` | 1→1 | 1140→1071 | 1141→1072 | `13864/11434/131/2/0→7548/5578/63/2/0` | 1.064 | 1.949 | 1/0 | 75.85 | **82.80** | `reference_dominates` |
| 2 | `array_array_partition_complete` | 1→1 | -→- | -→- | `7639/5695/63/2/0→7639/5695/63/2/0` | 1.000 | 1.000 | 1/0 | - | **75.25** | `identical_hardware_metrics` |
| 3 | `dsp_fir_decimator` | 1→1 | 21→20 | 22→21 | `511/334/11/0/0→482/325/11/0/0` | 1.050 | 1.015 | 1/0 | 75.67 | **76.08** | `reference_dominates` |
| 4 | `interface_aggregation_disaggregation_aggregation_of_nested_structs` | 1→1 | 10→17 | 8→16 | `149/10/0/0/0→150/10/0/0/0` | 0.588 | 0.994 | 1/0 | 67.15 | **75.25** | `starter_dominates` |
| 5 | `interface_aggregation_disaggregation_struct_ii_issue` | 1→1 | 526→526 | 527→200 | `8837/5228/0/8/0→7784/5098/0/30/0` | 1.000 | 0.701 | 1/0 | 58.47 | **75.25** | `tradeoff` |
| 6 | `interface_memory_aliasing_axi_master_ports` | 1→1 | 2088→1060 | 2089→1045 | `1843/1511/0/9/0→2087/1511/0/9/0` | 1.970 | 0.958 | 1/0 | 82.24 | **83.56** | `tradeoff` |
| 7 | `interface_memory_burst_rw` | 1→1 | 50689→50689 | 50690→50690 | `1898/1472/0/10/0→1898/1472/0/10/0` | 1.000 | 1.000 | 1/0 | 75.00 | **75.25** | `identical_hardware_metrics` |
| 8 | `interface_memory_coefficient_filter` | 1→1 | 258→258 | 256→256 | `75/20/1/1/0→75/20/1/1/0` | 1.000 | 1.000 | 1/0 | 75.00 | **75.25** | `identical_hardware_metrics` |
| 9 | `interface_memory_ecc_flags` | 1→1 | 113→115 | 114→116 | `3994/5108/3/0/0→4159/5203/3/0/2` | 0.983 | 0.704 | 1/0 | 66.39 | **75.25** | `starter_dominates` |
| 10 | `interface_memory_lmem_2rw` | 1→1 | 16553→14505 | 16554→14506 | `2466/1706/0/7/0→2627/1728/0/7/0` | 1.141 | 0.970 | 1/0 | 76.09 | **77.02** | `tradeoff` |
| 11 | `interface_memory_manual_burst_manual_burst_example_auto_burst_inference_failure` | 1→1 | -→- | -→- | `1753/1208/0/17/0→1753/1208/0/17/0` | 1.000 | 1.000 | 1/0 | - | **75.25** | `identical_hardware_metrics` |
| 12 | `interface_memory_manual_burst_manual_burst_example_manual_burst_inference_success` | 1→1 | -→- | -→- | `2615/1800/0/17/0→2615/1800/0/17/0` | 1.000 | 1.000 | 1/0 | - | **75.25** | `identical_hardware_metrics` |
| 13 | `interface_memory_max_widen_port_width` | 1→1 | 81→81 | 64→64 | `1188/1080/0/1/0→1188/1080/0/1/0` | 1.000 | 1.000 | 1/0 | 75.00 | **75.25** | `identical_hardware_metrics` |
| 14 | `interface_memory_ram_uram` | 1→1 | 1→1 | 2→2 | `45/146/0/57/0→282/150/0/0/8` | 1.000 | 1.653 | 1/0 | 48.41 | **80.53** | `tradeoff` |
| 15 | `interface_streaming_axi_stream_to_master` | 1→1 | -→- | -→- | `2056/1813/0/2/0→2221/1822/0/2/0` | 1.000 | 0.955 | 1/0 | - | **75.25** | `starter_dominates` |
| 16 | `misc_initialization_and_reset_static_array_of_struct_with_array_ram` | 1→1 | 1→1 | 2→2 | `377/113/0/0/0→236/17/0/3/0` | 1.000 | 0.357 | 1/0 | 61.42 | **75.25** | `tradeoff` |
| 17 | `misc_initialization_and_reset_static_array_ram` | 1→1 | 1→12 | 2→13 | `214/62/0/0/0→319/85/0/1/1` | 0.083 | 0.120 | 1/0 | 32.04 | **75.25** | `starter_dominates` |
| 18 | `misc_initialization_and_reset_static_array_rom` | 1→1 | 1→1 | 2→2 | `36/10/0/0/0→31/6/0/1/0` | 1.000 | 0.115 | 1/0 | 76.65 | **75.25** | `tradeoff` |
| 19 | `misc_rtl_as_blackbox` | 1→1 | 0→0 | 1→1 | `123/0/0/0/0→121/0/0/0/0` | 1.000 | 1.017 | 1/0 | 75.18 | **75.43** | `reference_dominates` |
| 20 | `modeling_conditional_control_of_pragmas_using_template_function` | 1→1 | 34→17 | 35→18 | `259/56/0/0/0→628/88/0/0/0` | 2.000 | 0.427 | 1/0 | 74.56 | **83.72** | `tradeoff` |
| 21 | `modeling_free_running_kernel_remerge_ii4to1` | 1→1 | 136→78 | 137→75 | `707/141/0/0/0→654/170/0/0/0` | 1.744 | 1.052 | 1/0 | 80.21 | **82.68** | `tradeoff` |
| 22 | `modeling_using_array_stencil_2d` | 1→1 | 20523490→44991 | 20523491→44992 | `8464/3788/4/15/0→14070/11532/131/15/0` | 456.169 | 0.362 | 1/0 | 97.98 | **99.89** | `tradeoff` |
| 23 | `pipelining_functions_function_instantiate` | 1→1 | 0→0 | 1→1 | `30/0/0/0/0→30/0/0/0/0` | 1.000 | 1.000 | 1/0 | 75.00 | **75.25** | `identical_hardware_metrics` |
| 24 | `pipelining_loops_using_free_running_pipeline` | 1→1 | 77→51 | 78→8 | `2631/1223/3/0/0→8054/6797/27/0/0` | 1.866 | 0.239 | 1/0 | 56.96 | **82.97** | `tradeoff` |
| 25 | `task_level_parallelism_control_driven_channels_merge_split_merge_load_balance` | 0→1 | -→65 | -→64 | `-→422/37/0/0/0` | 1.000 | 1.000 | 1/1 | - | **89.04** | `reference_validity_rescue` |
| 26 | `task_level_parallelism_control_driven_channels_merge_split_merge_round_robin` | 0→1 | -→65 | -→64 | `-→422/37/0/0/0` | 1.000 | 1.000 | 1/1 | - | **89.04** | `reference_validity_rescue` |
| 27 | `task_level_parallelism_control_driven_channels_merge_split_split_load_balance` | 0→1 | -→17 | -→16 | `-→350/26/0/0/0` | 1.000 | 1.000 | 1/1 | - | **89.04** | `reference_validity_rescue` |
| 28 | `task_level_parallelism_control_driven_channels_merge_split_split_round_robin` | 0→1 | -→17 | -→16 | `-→350/26/0/0/0` | 1.000 | 1.000 | 1/1 | - | **89.04** | `reference_validity_rescue` |
| 29 | `task_level_parallelism_control_driven_channels_simple_fifos` | 1→1 | 311→308 | 312→100 | `564/110/0/0/0→489/106/0/0/0` | 1.010 | 1.142 | 1/0 | 75.55 | **76.84** | `reference_dominates` |
| 30 | `task_level_parallelism_control_driven_channels_using_fifos` | 1→1 | 198→57 | 199→44 | `9240/11830/0/8/0→9752/12431/0/8/0` | 3.474 | 0.956 | 1/0 | 88.40 | **88.91** | `tradeoff` |
| 31 | `task_level_parallelism_control_driven_channels_using_stream_of_blocks` | 0→1 | -→258 | -→100 | `-→1791/253/0/0/0` | 1.000 | 1.000 | 1/1 | - | **89.04** | `reference_validity_rescue` |
| 32 | `task_level_parallelism_control_driven_patterns_using_stream_as_sync` | 1→1 | -→- | -→- | `1961/1500/0/1/0→1955/1812/0/1/0` | 1.000 | 0.953 | 1/0 | - | **75.25** | `tradeoff` |
| 33 | `task_level_parallelism_data_driven_mixed_control_and_data_driven` | 0→1 | -→- | -→- | `-→402/109/0/0/0` | 1.000 | 1.000 | 1/1 | - | **89.04** | `reference_validity_rescue` |
| 34 | `task_level_parallelism_data_driven_unique_task_regions` | 0→1 | -→- | -→- | `-→1722/887/0/0/0` | 1.000 | 1.000 | 1/1 | - | **89.04** | `reference_validity_rescue` |
| 35 | `task_level_parallelism_data_driven_using_directio_none_in_tasks` | 1→1 | 0→1 | 1→1 | `148/2/0/0/0→166/37/0/0/0` | 1.000 | 0.808 | 1/0 | 37.90 | **75.25** | `starter_dominates` |
| 36 | `task_level_parallelism_data_driven_using_maxi_in_tasks` | 1→1 | 9→9 | 8→8 | `1416/904/0/0/0→1492/958/0/2/0` | 1.000 | 0.714 | 1/0 | 66.67 | **75.25** | `starter_dominates` |

## Warnings

| Type | Detail |
|---|---|
| Incentive compatibility | Any valid source change receives a small uplift even if hardware regresses. Do not use this formula to rank arbitrary agent submissions. |
| Construct validity | `sum(R/C)` measures device-resource scarcity, not routed area, power, or congestion. |
| Overfitting | The rejected signed-margin family needs a corpus-fitted factor; the recommended 1.01 source proof is policy-defined rather than fitted. |
| Missing latency | Five synthesis-valid pairs have undefined latency; `P=1` for those rows. |
| Failed starter synthesis | Seven pairs use `F=1`; their missing starter hardware metrics are not fabricated. |
| Execution anomaly | The first search invocation referenced a nonexistent component attribute and exited before producing accepted results; the corrected run and independent rerun are the reported artifacts. |

## Fallacy scan

- Coverage: **11/11 checked**
- Survivorship bias is avoided in the final guarantee because all 36 pairs are included; only the separate current-qhw column is limited to 24.
- Look-elsewhere/garden-of-forking-paths risk is material for the rejected fitted-margin family. The recommended formula uses fixed, interpretable factors and reports the impossibility boundary explicitly.
- Simpson, ecological, Berkson, collider, base-rate, regression-to-mean, causal, and reverse-causality fallacies are not applicable to this deterministic pairwise calculation.

## Reproducibility

- Method: deterministic re-analysis of frozen evidence in a network-disabled Docker container
- Verdict: **REPRODUCIBLE** — JSON, CSV, and Markdown matched byte-for-byte across two network-disabled Docker runs; an independent verifier recomputed every final score and asserted 36/36 >75.
