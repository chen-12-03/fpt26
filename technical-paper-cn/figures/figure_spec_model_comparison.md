# Figure Spec: Three-Endpoint Comparison

## Identity

- **Figure ID:** `fig:results`
- **Paper section:** Section IV
- **Placement:** one column (`figure`)
- **Generation backend:** user-supplied vector PDF
- **Expected asset:** `technical-paper/figures/model_comparison.pdf`

## Content

Compare DeepSeek V4 Pro, Qwen3.5-122B-A10B, and Qwen3.6-27B using four values
from `technical-paper/results_generated.tex`:

1. overall task completion rate (%);
2. structural-repair completion rate (%);
3. mean official score on the 25 QoR tasks; and
4. total model tokens (millions).

Use a compact grouped-bar or dot-plot design. Keep the two success measures
visually distinct from QoR score and token use, and label every axis with its
unit. Do not recompute values from prose.

## Layout

- **Size target:** 3.45 inches wide and approximately 1.05 inches high,
  excluding caption
- **Text:** legible at final one-column size; prefer direct labels over a large
  legend
- **Output:** vector PDF with embedded fonts

## Caption

Structural repair separates the three endpoints. Plot overall and structural
completion (%), mean official score on the 25 QoR tasks, and total tokens
using the generated merged-record aggregates.
