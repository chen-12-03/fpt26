## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: validate
- Origin Date: 2026-08-03
- Verification Status: VERIFIED
- Version Label: resource_aggregation_validation_v1

# Capacity-normalized resource aggregation validation

- **Verdict**: `AUTOMATED_CHECKS_PASS`
- **Deployment recommendation**: `DO_NOT_ADOPT_AS_IS`
- **Overall Confidence**: `CAUTION`
- **Frozen pairs**: 36
- **Resource-valid pairs**: 29
- **Full-qhw scorable pairs**: 24
- **External API calls**: 0
- **Candidate attempts in this validation**: 1
- **Production scorer modified**: no

## Frozen candidate formula

`U(R) = sum(R_r / C_r)`

`area_growth = (tau + U(reference)) / (tau + U(starter))`

`area_ratio = 1 / area_growth`

`tau = 0.002327513909` (median of the 29 valid starter footprints).
The production performance/area weights remain 0.55/0.45.

## Acceptance checks

| Check | Result |
|---|---|
| `pareto_direction_preserved` | PASS |
| `zero_boundary_cliff_resolved` | PASS |
| `score_distribution_not_collapsed` | PASS |
| `significant_resource_growth_still_penalized` | PASS |

## Aggregate comparison

| Metric | Current | Proposed |
|---|---:|---:|
| Mean score | 69.74 | 75.39 |
| Median score | 75.00 | 75.00 |
| Population stddev | 14.50 | 11.21 |
| Minimum | 32.04 | 31.63 |
| Maximum | 97.98 | 99.76 |
| Pareto direction correct | 9/9 | 9/9 |

Spearman rank correlation: `0.7310`. 
Mean absolute paired score change: `5.94` points; maximum: `36.97` points.

## Outlier review

The automated checks are necessary but not sufficient for deployment. The candidate fixes the observed BRAM-to-URAM transfer, but the corpus-level median `tau` suppresses relative resource changes in small designs:

- `interface_memory_ram_uram`: normalized footprint falls from 0.014227 to 0.008607, so the score moves from 48.41 to 79.44. This is the intended correction of a resource-transfer reversal.
- `task_level_parallelism_data_driven_using_directio_none_in_tasks`: LUT rises 148→166 and FF rises 2→37 with no performance gain, but the score moves from 37.90 to 74.88 because `tau` dominates both footprints. This is an unacceptable loss of relative-efficiency sensitivity for a sole area metric.
- `pipelining_loops_using_free_running_pipeline`: aggregate footprint grows 4.18x and performance improves 1.87x; the score rises from 56.96 to 72.16. This is a policy-sensitive tradeoff and shows that the candidate systematically softens area penalties.

Therefore the capacity-normalized aggregate `U(R)` is supported as a common resource currency, while the global median smoothing term is not supported for production use. A follow-up candidate should retain `U(R)` but use either a negligible all-zero guard or a separately validated hybrid relative-growth term. No such second formula is calculated in this report.

## Per-task results

| Task | P | U starter→reference | A current | A proposed | Score current | Score proposed | Delta | Zero boundary |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `array_array_partition_block_cyclic` | 1.064 | 0.030033→0.015407 | 1.000 | 1.825 | 75.85 | 81.99 | +6.14 | - |
| `dsp_fir_decimator` | 1.050 | 0.001739→0.001713 | 1.000 | 1.006 | 75.67 | 75.74 | +0.07 | - |
| `interface_aggregation_disaggregation_aggregation_of_nested_structs` | 0.588 | 0.000118→0.000119 | 0.993 | 1.000 | 67.15 | 67.23 | +0.08 | - |
| `interface_aggregation_disaggregation_struct_ii_issue` | 1.000 | 0.010768→0.015367 | 0.267 | 0.740 | 58.47 | 71.50 | +13.04 | - |
| `interface_memory_aliasing_axi_master_ports` | 1.970 | 0.004225→0.004413 | 0.883 | 0.972 | 82.24 | 83.12 | +0.88 | - |
| `interface_memory_burst_rw` | 1.000 | 0.004501→0.004501 | 1.000 | 1.000 | 75.00 | 75.00 | +0.00 | - |
| `interface_memory_coefficient_filter` | 1.000 | 0.000424→0.000424 | 1.000 | 1.000 | 75.00 | 75.00 | +0.00 | - |
| `interface_memory_ecc_flags` | 0.983 | 0.005355→0.007601 | 0.500 | 0.774 | 66.39 | 71.78 | +5.39 | URAM |
| `interface_memory_lmem_2rw` | 1.141 | 0.004282→0.004414 | 0.939 | 0.980 | 76.09 | 76.57 | +0.48 | - |
| `interface_memory_max_widen_port_width` | 1.000 | 0.001573→0.001573 | 1.000 | 1.000 | 75.00 | 75.00 | +0.00 | - |
| `interface_memory_ram_uram` | 1.000 | 0.014227→0.008607 | 0.125 | 1.514 | 48.41 | 79.44 | +31.02 | BRAM_18K,URAM |
| `misc_initialization_and_reset_static_array_of_struct_with_array_ram` | 1.000 | 0.000333→0.000932 | 0.333 | 0.816 | 61.42 | 72.66 | +11.25 | BRAM_18K |
| `misc_initialization_and_reset_static_array_ram` | 0.083 | 0.000188→0.001567 | 0.671 | 0.646 | 32.04 | 31.63 | -0.41 | BRAM_18K,URAM |
| `misc_initialization_and_reset_static_array_rom` | 1.000 | 0.000031→0.000274 | 1.161 | 0.907 | 76.65 | 73.89 | -2.77 | BRAM_18K |
| `misc_rtl_as_blackbox` | 1.000 | 0.000094→0.000093 | 1.017 | 1.001 | 75.18 | 75.01 | -0.18 | - |
| `modeling_conditional_control_of_pragmas_using_template_function` | 2.000 | 0.000220→0.000515 | 0.412 | 0.896 | 74.56 | 82.55 | +7.98 | - |
| `modeling_free_running_kernel_remerge_ii4to1` | 1.744 | 0.000596→0.000567 | 0.829 | 1.010 | 80.21 | 82.10 | +1.89 | - |
| `modeling_using_array_stencil_2d` | 456.169 | 0.012109→0.033452 | 0.031 | 0.403 | 97.98 | 99.76 | +1.78 | - |
| `pipelining_functions_function_instantiate` | 1.000 | 0.000023→0.000023 | 1.000 | 1.000 | 75.00 | 75.00 | +0.00 | - |
| `pipelining_loops_using_free_running_pipeline` | 1.866 | 0.002820→0.011777 | 0.111 | 0.365 | 56.96 | 72.16 | +15.20 | - |
| `task_level_parallelism_control_driven_channels_simple_fifos` | 1.010 | 0.000475→0.000416 | 1.038 | 1.022 | 75.55 | 75.37 | -0.18 | - |
| `task_level_parallelism_control_driven_channels_using_fifos` | 3.474 | 0.013609→0.014232 | 0.947 | 0.962 | 88.40 | 88.51 | +0.11 | - |
| `task_level_parallelism_data_driven_using_directio_none_in_tasks` | 1.000 | 0.000114→0.000142 | 0.054 | 0.989 | 37.90 | 74.88 | +36.97 | - |
| `task_level_parallelism_data_driven_using_maxi_in_tasks` | 1.000 | 0.001433→0.002008 | 0.500 | 0.867 | 66.67 | 73.37 | +6.71 | BRAM_18K |

## Warnings

| Type | Detail | Affected |
|---|---|---|
| Construct validity | Capacity-normalized utilization measures resource scarcity, not placed-and-routed silicon area, power, or congestion. | All tasks |
| Sample scope | All pairs come from one AMD/Xilinx examples repository and one FPGA target/tool version. | Generalization |
| Selection | 24/36 pairs have defined latency and enter full qhw comparison; all 29 synthesis-valid pairs remain in resource analysis. | Score distribution |
| Calibration reuse | Tau is derived from the same frozen starters used for validation; no parameter sweep was performed, but independent-corpus confirmation is still needed. | Tau |

## Fallacy scan

- **Coverage**: 11/11 checked

| Fallacy | Severity | Finding |
|---|---|---|
| Simpson's paradox | NOTE | No subgroup reversal test is possible with one-source corpus. |
| Ecological fallacy | NOTE | No individual-level inference is made. |
| Berkson's paradox | CAUTION | Only synthesis-valid/scorable pairs contribute to corresponding summaries. |
| Collider bias | NOTE | No regression controls are used. |
| Base-rate neglect | NOTE | No diagnostic probabilities are reported. |
| Regression to the mean | NOTE | No repeated extreme-score selection. |
| Survivorship bias | CAUTION | Full qhw uses 24/36; failures and undefined-latency cases remain explicitly reported. |
| Look-elsewhere effect | NOTE | Exactly one candidate formula and no tau/weight sweep were evaluated. |
| Garden of forking paths | CAUTION | Formula was proposed after observing the resource-transfer defect; independent confirmation is required. |
| Correlation != causation | NOTE | Descriptive formula validation only; no causal claim. |
| Reverse causality | NOTE | Not applicable to deterministic metric comparison. |

## Reproducibility

- **Method**: deterministic re-analysis of frozen JSON evidence
- **Verdict**: `REPRODUCIBLE` — JSON, CSV, and Markdown outputs matched byte-for-byte across two network-disabled Docker runs.

## Interpretation boundary

Passing the automated checks establishes mathematical continuity, sample-level Pareto consistency, and improved handling of observed resource transfers. The outlier review prevents promotion of the exact candidate formula. The experiment does not establish physical-area accuracy because no implementation-level area, power, or congestion ground truth is available.
