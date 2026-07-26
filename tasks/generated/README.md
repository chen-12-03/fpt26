# 从 hls-eval 转换的 Benchmark 汇总

总计: 196 个任务


| 套件 | 数量 | 难度 | 类型 |
|---|---|---|---|
| c2hlsc | 12 | 3 | optimize |
| chstone | 20 | 2 | optimize |
| flowgnn | 3 | 3 | generate |
| gnnbuilder | 3 | 3 | generate |
| machsuite | 17 | 4 | optimize |
| polybench | 28 | 4 | optimize |
| pp4fpga | 3 | 3 | optimize |
| rosetta | 8 | 5 | optimize |
| amd_intro | 73 | 3 | optimize |
| amd_accel | 29 | 3 | optimize |

## Public HLS expansion

- 新增 validated public-only HLS tasks: 102
- 来源分布: AMD Vitis-HLS-Introductory-Examples 73, AMD Vitis_Accel_Examples 29
- 验证门: Vitis 2025.2 CSim + Synth smoke 全部通过
- 失败候选: 28 个，已从 `tasks/generated` 移到 `/tmp/fpt26_failed_public_hls_tasks`
- 清单: `public_hls_validated_tasks_manifest.json`
