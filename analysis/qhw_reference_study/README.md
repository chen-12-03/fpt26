# QHW reference study

This directory retains the compact, publication-facing evidence for the
schema-11 hardware-quality formula. Construction scripts, temporary task
copies, and raw Vitis project trees are intentionally excluded from the public
repository.

The main result is that the production `performance=0.55 / area=0.45` weighting
agreed with all nine examples having an unambiguous Pareto direction. Across
the 24 scoreable public starter/reference pairs, changing the weighting to
`0.60 / 0.40` did not improve that agreement, so the production weighting was
kept.

Retained evidence:

- `results/analysis.json` and `results/task_metrics.csv`: task-level metrics
  and aggregate conclusions.
- `results/upstream_audit.json`: upstream source identity and provenance.
- `results/reference_score_formula_search.{json,csv}`: bounded formula search.
- `results/resource_aggregation_validation.{json,csv}`: heterogeneous-resource
  aggregation validation.
- The Markdown files beside this README describe the formula and validation
  logic used to interpret those machine-readable results.

`results/SHA256SUMS` authenticates this retained evidence subset. The current
paper-level results are reproduced independently from the canonical v4 dataset
under `technical-paper/evidence/`.
