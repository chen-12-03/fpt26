"""Iter3 Unified HLS optimization pattern lookup — keyword-matching only, no task-type awareness."""
from __future__ import annotations
from typing import Any

_PATTERNS = [
    {
        "keywords": ["single loop", "vector", "dot product", "accumulate", "reduction", "sum"],
        "family": "Reduction / Single-Loop Pipeline",
        "steps": [
            "1. PIPELINE II=1 on the accumulation loop (highest ROI, single pragma).",
            "2. If II>1 after pipelining: check array port count → ARRAY_PARTITION dim=1 on the input arrays.",
            "3. For very long vectors: tiled loop + ARRAY_PARTITION cyclic + PIPELINE on tiled outer loop.",
            "4. If multiple independent accumulations exist: separate them into parallel paths.",
        ],
        "signal": "Achieved II=1, latency ≈ trip_count + pipeline depth.",
        "warning": "Do NOT fully unroll if trip_count > 64. UNROLL on long vectors causes massive FF/LUT explosion.",
    },
    {
        "keywords": ["nested loop", "double loop", "2d", "matrix", "row", "column", "grid"],
        "family": "Nested-Loop Pipeline",
        "steps": [
            "1. PIPELINE the inner loop first (best ROI, lowest resource cost).",
            "2. If outer loop is the bottleneck: PIPELINE outer loop instead (forces inner concurrency).",
            "3. For 2D access: ARRAY_PARTITION dim=2 (column access) or dim=1 (row access) based on pattern.",
            "4. UNROLL inner by 2-4 + PIPELINE outer for moderate speedup without resource explosion.",
        ],
        "signal": "Latency reduced by ~inner_trip_count factor; moderate FF growth.",
        "warning": "Outer PIPELINE forces all inner loops to run concurrently — check memory port count FIRST.",
    },
    {
        "keywords": ["parallel array", "multiple access", "bank", "memory port", "bandwidth", "dual port"],
        "family": "Array Partition for Memory Bandwidth",
        "steps": [
            "1. Identify the loop dimension that performs multiple reads/writes per iteration.",
            "2. ARRAY_PARTITION variable=<name> dim=<access_dim> factor=<N> cyclic (or block).",
            "3. Match UNROLL factor=N on the same loop that accesses the partitioned array.",
            "4. Check resource growth: each partition factor doubles BRAM/register count.",
        ],
        "signal": "II decreases from >1 to 1; LUT/FF grow proportionally to partition factor.",
        "warning": "PARTITION + RESHAPE on same variable is redundant — pick ONE. Cyclic is usually better for interleaved access.",
    },
    {
        "keywords": ["producer consumer", "stream", "stage", "dataflow", "fifo", "pipeline stage"],
        "family": "Dataflow with Stream FIFOs",
        "steps": [
            "1. Split the design into clear stages: producer → compute → consumer.",
            "2. Define hls::stream<T> channels between stages with EXPLICIT depth: stream.depth(N).",
            "3. Apply DATAFLOW pragma on the top-level function (not inside sub-functions).",
            "4. Set stream depth = max(producer_burst_size, consumer_burst_size) + pipeline latency margin.",
            "5. For cosim safety: start with depth=16 or more, then reduce after cosim passes.",
        ],
        "signal": "Stages run concurrently; throughput = 1 / max(stage_latency).",
        "warning": "DATAFLOW without explicit .depth() → cosim DEADLOCK with default depth-2 FIFOs. C-simulation CANNOT detect this.",
    },
    {
        "keywords": ["deadlock", "cosim fail", "timeout", "fifo depth", "stream depth", "burst"],
        "family": "Streaming Deadlock Resolution",
        "steps": [
            "1. Identify ALL hls::stream declarations — check if any lack .depth(N).",
            "2. Trace the DATAFLOW: does any stage write an ENTIRE stream before writing side-channel data?",
            "3. If stage A writes main stream fully before skip/control stream: RESTRUCTURE to interleave writes in a SINGLE loop.",
            "4. Alternative: increase ALL stream depths to cover worst-case burst (depth ≥ burst_size).",
            "5. For skip/residual patterns: ensure BOTH streams are read alternately by consumer, not sequentially.",
            "6. Re-run cosim after EACH change to verify.",
        ],
        "signal": "Cosim passes without timeout; stream depths are explicit and bounded.",
        "warning": "Simply increasing all depths to large values hides the architectural bug — prefer restructuring to interleaved writes.",
    },
    {
        "keywords": ["matmul", "matrix multiply", "gemm", "triple loop", "blocked", "tile"],
        "family": "Tiled Matrix Multiply",
        "steps": [
            "1. PIPELINE outermost loop for maximum throughput.",
            "2. UNROLL innermost by factor 4-8 for parallel MAC.",
            "3. ARRAY_PARTITION accumulator dim=2 for parallel reduction.",
            "4. For large matrices: tile into local buffers + DATAFLOW between tile load/compute/store.",
        ],
        "signal": "Dramatic latency reduction (10-100x); DSP usage = unroll factor.",
        "warning": "O(N²) resource growth with tile size. Start with factor=2 and measure before scaling.",
    },
    {
        "keywords": ["fir", "filter", "tap", "coefficient", "symmetric", "convolution"],
        "family": "FIR Filter Optimization",
        "steps": [
            "1. PIPELINE II=1 on the sample-processing loop.",
            "2. For symmetric FIR: halve MAC operations by pre-adding symmetric tap pairs.",
            "3. ARRAY_PARTITION coefficient array for parallel coefficient read.",
            "4. For streaming (AXIS): DATAFLOW with separate coefficient load and MAC stages.",
        ],
        "signal": "II=1 sustained; DSP count ≈ taps/2 (symmetric) or taps (direct).",
        "warning": "Full unroll of large FIR (>100 taps) → massive DSP usage. Prefer PIPELINE over UNROLL.",
    },
    {
        "keywords": ["csim fail", "mismatch", "wrong", "bug", "incorrect", "assert", "fix", "error"],
        "family": "Functional Bug Diagnosis & Repair",
        "steps": [
            "1. Read the csim error log: find the EXACT line where output differs from expected.",
            "2. Trace the dataflow to that output: which input values, which computation path?",
            "3. Check edge cases: zero values, boundary indices, off-by-one, sign errors, missing terms in sums.",
            "4. Fix the minimal code section — do NOT restructure the entire kernel.",
            "5. Re-run csim to verify the fix BEFORE adding any pragmas.",
        ],
        "signal": "Csim passes; output matches expected values.",
        "warning": "Do NOT add pragmas to a functionally broken kernel. Fix correctness FIRST, then optimize.",
    },
    {
        "keywords": ["ap_fixed", "fixed point", "quantize", "precision", "overflow", "underflow"],
        "family": "Fixed-Point Precision Tuning",
        "steps": [
            "1. Document required integer bits: ceil(log2(max_abs_value)) + 1 (sign).",
            "2. Allocate remaining bits to fractional precision: W = I + F.",
            "3. Use AP_RND and AP_SAT for rounding/overflow control.",
            "4. Add assertions in testbench to catch overflow/underflow in csim.",
        ],
        "signal": "Resource reduction vs float; precision within error budget.",
        "warning": "Fixed-point range violations are SILENT in csim without assertions. Add them.",
    },
    {
        "keywords": ["cordic", "trig", "sin", "cos", "atan", "rotation", "angle", "projection"],
        "family": "CORDIC / Trigonometric Optimization",
        "steps": [
            "1. ap_fixed<W,I> with well-documented bit widths for angle and result.",
            "2. PIPELINE the iterative shift-add loop for throughput.",
            "3. UNROLL CORDIC stages for latency reduction (costs DSP/LUT).",
            "4. Pre-compute arctan table as static const array for the CORDIC gain.",
        ],
        "signal": "No DSP blocks for trig; latency = stages × II.",
        "warning": "CORDIC gain factor must be compensated. Check rotation mode vs vectoring mode.",
    },
]


def lookup_patterns(desc: str) -> list[dict]:
    """Find matching HLS optimization patterns by keyword matching only.

    Returns top 3 patterns matching the description keywords.
    """
    d = desc.lower()
    scored: list[tuple[int, dict]] = []
    for p in _PATTERNS:
        kw_score = sum(1 for kw in p["keywords"] if kw in d)
        if kw_score > 0:
            scored.append((kw_score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:3]]


def format_for_prompt(matches: list[dict]) -> str:
    """Format matched patterns as actionable optimization hints for the LLM."""
    if not matches:
        return ""

    lines = ["## Applicable HLS Optimization Patterns"]
    for i, m in enumerate(matches, 1):
        lines.append(f"\n### Pattern {i}: {m['family']}")
        lines.append("**Steps:**")
        lines.extend(f"  {step}" for step in m["steps"])
        lines.append(f"**Expected Signal:** {m['signal']}")
        lines.append(f"**⚠ Warning:** {m['warning']}")

    lines.append("\n---")
    lines.append("**Apply ONLY ONE pattern at a time.** Re-synthesize and verify improvement.")
    lines.append("If the pattern does not improve the limiting metric, REMOVE the added pragma and try another.")
    return "\n".join(lines)
