# FPT26 Agent v2 — Scoring Standard Redesign Brief

## For: Codex Goal — Design a mature, reliable HLS agent scoring standard

---

## 1. BACKGROUND: What exists and why it must change

### 1.1 The current scoring formula

```python
# llm4hls/scoring.py
ACCEL_CAP = 8.0

score = difficulty × (
    0.5 × correct       +   # functional pass (hidden testbench)
    0.2 × synthesizable +   # can C-synthesis succeed
    0.3 × ppa_norm          # min(acceleration, 8.0) / 8.0
)
```

**Max possible score** = `difficulty × 1.0`.

### 1.2 Proven defects (with real run data)

We ran the agent on the three official tasks. Here is what the current formula
misses:

| Defect | Real Example | Consequence |
|---|---|---|
| **Area is not in the formula (0% weight)** | dotProduct: LUT 156→13189 (+84x), FF 93→54194 (+582x) — scored 3.0/3.0 (perfect) | Agent is incentivised to brute-force unroll/pipeline everything regardless of area cost |
| **ACCEL_CAP=8.0 creates a ceiling** | dotProduct achieved 27.03x acceleration, but the formula treats it identically to any ≥8x result | Extra latency improvement beyond 8x earns ZERO additional score — agent has no reason to push further |
| **Repair tasks structurally capped at 70%** | projection_bugfix: latency=0 (combinational logic), ppa_norm=0 → max score = difficulty×0.7 | Repair-only tasks can never reach their theoretical max, even if the fix is perfect |
| **No budget efficiency dimension** | residual_stream_deadlock spent 66/80 credits (82.5% budget) with 2 failed cosim attempts | A wasteful agent and an efficient agent get the same score for the same final kernel |
| **No throughput/II dimension** | The SynthReport has `interval_min`/`interval_max` (initiation interval) — completely unused | A design with II=1 (new result every cycle) is indistinguishable from II=1025 (one result every 1025 cycles) |
| **Co-simulation measured latency is ignored** | CoSimResult has `latency_min`/`latency_avg`/`latency_max` from actual RTL simulation — the formula uses only C-synthesis estimates | For structural tasks, the ground-truth RTL latency is available but thrown away |
| **Resource utilization ratio is not capped by device** | dotProduct used 13189 LUT on a U55C (≈1.3M LUT available) — that's fine NOW, but if a task uses 80% of the device, area becomes a real constraint | No headroom-awareness in scoring |

### 1.3 What data is available

Every tool call produces a `ToolResult` (see `llm4hls/tools.py`):

| Field | Type | Description |
|---|---|---|
| `kind` | `"csim" \| "synth" \| "cosim"` | Which tool |
| `ok` | `bool` | Did it succeed? |
| `phase` | `str` | `"pass"`, `"compile_error"`, `"runtime_fail"`, `"synth_error"`, `"cosim_fail"`, `"timeout"` |
| `return_code` | `int` | Process exit code |
| `log` | `str` | Full stdout/stderr (truncated to 12KB) |
| `elapsed_s` | `float` | Wall-clock seconds |
| `report` | `SynthReport \| None` | Populated on successful synth — see below |
| `cosim` | `CoSimResult \| None` | Populated on cosim — see below |

`SynthReport` fields (from `csynth.xml`):
```
clock_period_ns: float | None
latency_best / latency_avg / latency_worst: int | None    (cycles)
interval_min / interval_max: int | None                   (II = initiation interval)
resources:  {"LUT": N, "FF": N, "DSP": N, "BRAM_18K": N, "URAM": N}
available:  {"LUT": N, ...}        (device total)
utilization: {"LUT": pct, ...}     (used / available as %)
```

`CoSimResult` fields (from RTL simulation report):
```
status: "Pass" | "Fail" | "NA"
latency_min / latency_avg / latency_max: int | None    (measured RTL cycles)
```

`Budget` (credit-tracking):
```
total: int      (task budget, e.g. 40)
spent: int      (cumulative credits used)
cost: dict      (per-tool cost: csim=1, synth=4, cosim=20)
calls: list     (per-call detail: kind, cost, spent_after)
```

`Task` metadata:
```
id: str              (e.g. "dotProduct_optimize")
type: str            ("generate" | "repair" | "optimize" | "synth_fix" | "structural")
difficulty: int      (1-5, acts as score multiplier)
top: str             (top-level function name)
requires_cosim: bool
clock_ns: float      (target clock period)
part: str            (FPGA part number, e.g. "xcu55c-fsvh2892-2L-e")
```

### 1.4 Task types and what they measure

| Type | Goal | Current formula coverage |
|---|---|---|
| `repair` | Fix a bug that causes csim failure | 0.5 (correctness) + 0.2 (synth) = 0.7 max — ppa_norm always 0 |
| `optimize` | Reduce latency of already-correct code | Full 1.0 possible if accel ≥ 8x |
| `structural` | Fix streaming/dataflow deadlock (only caught by cosim) | Same as optimize, but requires cosim pass gate |
| `generate` | Write kernel from natural-language spec | NOT COVERED — no tasks exist yet |
| `synth_fix` | Fix synthesis failure (code compiles but won't synthesize) | NOT COVERED — no tasks exist yet |

### 1.5 All harness parameters are modifiable

From the official documentation: the entire harness (`llm4hls/`) is a REFERENCE
implementation. All parameters — credit costs, timeouts, scoring weights,
ACCEL_CAP, device part, clock period, task budget — can be changed. The only
constraint is that the **tool interface** (csim/synth/cosim calling Vitis HLS)
should remain the evaluation mechanism; how we score the results is entirely up
to us.

---

## 2. OBJECTIVE

Design a **multi-dimensional scoring standard** for evaluating LLM-driven HLS
agents on FPGA design tasks. The standard must:

1. **Correctly reward what matters**: functional correctness → synthesizability
   → latency improvement → area efficiency → throughput → budget efficiency, in
   that priority order.

2. **Penalise pathological behaviour**: area bloat for trivial latency gains,
   infinite retry loops, budget waste.

3. **Not create arbitrary ceilings**: no single cap (like ACCEL_CAP=8.0) should
   make further improvement invisible.

4. **Be fair across task types**: repair, optimize, structural, and generate
   tasks should each have a realistic path to a high score.

5. **Support statistical rigour**: produce per-task and aggregate scores with
   confidence intervals (multi-run), generalisation gap (seen vs held-out tasks),
   and component ablation.

---

## 3. DESIGN CONSTRAINTS

### 3.1 Must preserve

- The tool interface: `csim(kernel) → ToolResult`, `synth(kernel) → ToolResult`,
  `cosim(kernel) → ToolResult`
- The task packaging format: `task.toml` + kernel source + headers + testbench
- Functional correctness as a hard gate (fail → score = 0 or near-zero)

### 3.2 May modify

- All weight coefficients in the scoring formula
- ACCEL_CAP (remove, raise, or replace with a diminishing-returns function)
- Credit costs per tool type
- Task difficulty scale (1-5, or change range)
- Budget allocation per task
- What counts as "ppa_norm" (add area, II, resource utilisation)
- How cosim measured latency factors in vs synthesis estimated latency

### 3.3 Should consider adding

- **Area growth penalty**: a term that decreases score when resource usage
  explodes relative to baseline
- **Throughput (II) dimension**: initiation interval matters for streaming/
  pipelined designs
- **Budget efficiency**: score should reflect credit economy
- **RTL-verified latency**: for structural tasks, cosim-measured latency is
  ground truth and should take priority over synthesis estimates
- **Device headroom awareness**: a design using 90% of device resources should
  be scored differently from one using 1%, even if both are "synthesizable"

---

## 4. KEY ACCEPTANCE CRITERIA

The redesigned scoring standard must pass these concrete tests:

### AC-1: Area penalty works
**Scenario**: Two dotProduct candidates, both 27x acceleration.
- Candidate A: LUT=500, FF=200 (area-efficient)
- Candidate B: LUT=13189, FF=54194 (area-bloated)
**Expected**: Candidate A scores strictly higher than Candidate B.

### AC-2: No arbitrary ceiling
**Scenario**: dotProduct candidates with accel = 8x, 27x, 100x, all with same
resource profile.
**Expected**: 100x > 27x > 8x (diminishing returns allowed, but strict equality is not).

### AC-3: Repair task can reach high score
**Scenario**: projection_bugfix — repair-only task, no latency change.
**Expected**: A correct fix with no resource regression can score ≥ 85% of max.

### AC-4: Budget matters
**Scenario**: Same final kernel achieved with:
- Agent A: 10/40 credits (efficient)
- Agent B: 38/40 credits (wasteful, many failed attempts)
**Expected**: Agent A scores higher.

### AC-5: Throughput (II) is rewarded
**Scenario**: Two candidates with same latency but II=1 vs II=100.
**Expected**: II=1 candidate scores higher.

### AC-6: Co-sim latency overrides synth latency
**Scenario**: Structural task where synth says 100 cycles but cosim measures 150.
**Expected**: The cosim-measured 150 is used for scoring (or at minimum, a
discrepancy between synth and cosim latency triggers a penalty).

### AC-7: Functional failure is catastrophic
**Scenario**: Candidate fails hidden testbench.
**Expected**: Score = 0, regardless of PPA.

### AC-8: Synthesizability failure is near-catastrophic
**Scenario**: Candidate passes csim but fails synthesis.
**Expected**: Score ≤ 20% of max (correctness-only partial credit).

---

## 5. WEB SEARCH DIRECTIVES

Research the following topics to inform the scoring design. For each, provide
citations (URLs) and a one-paragraph synthesis of relevant findings.

### Search 1: HLS PPA quality metrics
**Query**: "high-level synthesis PPA quality metric area-delay product FPGA design space exploration scoring"
**What to extract**: How academic literature and industry combine latency, area,
and throughput into a single quality metric for HLS designs. Look for ADP
(Area-Delay Product), ADPP (Area-Delay-Power Product), or similar compound
metrics used in design-space exploration (DSE).

### Search 2: FPGA vendor scoring rubrics
**Query**: "Xilinx Vitis HLS design contest scoring rubric acceleration area tradeoff benchmark"
**What to extract**: How Xilinx/AMD or other FPGA vendors score HLS designs in
competitions (Xilinx Open Hardware, FPGA design contests, etc.). What weights
do they assign to performance vs area vs power?

### Search 3: LLM-for-HLS evaluation benchmarks
**Query**: "LLM4HLS benchmark evaluation metric VerilogEval RTLLM agent scoring 2024 2025"
**What to extract**: How existing LLM-for-HLS benchmarks (VerilogEval, RTLLM,
HDL-Eval, etc.) evaluate generated hardware designs. Do they use pass@k?
Functional pass rate? PPA comparison? What metrics are standard in the field?

### Search 4: Diminishing returns functions for optimization scoring
**Query**: "diminishing returns scoring function log scale sublinear reward optimization benchmark"
**What to extract**: Mathematical functions (log, sqrt, atan, sigmoid) used to
model diminishing returns in optimisation benchmarks, so we can replace the
current hard cap (ACCEL_CAP=8.0) with a smooth function.

---

## 6. DELIVERABLES

Produce the following concrete outputs:

### D-1: Scoring formula specification
A precise mathematical specification of the new formula, including:
- The complete equation with all terms
- Weight coefficients with justification for each value
- How each input (SynthReport, CoSimResult, Budget, Task metadata) maps to formula terms
- Diminishing-returns function(s) replacing ACCEL_CAP
- Special-case handling for each task type (repair / optimize / structural / generate / synth_fix)

### D-2: Scoring module pseudocode
Python-like pseudocode for a `grade()` function that implements the formula.
Must show:
- Input validation and edge cases
- How area growth is computed and penalised
- How budget efficiency is factored in
- How cosim vs synth latency priority is resolved
- How the final score is normalised to a consistent range (suggestion: 0-100 or 0-10 scale independent of difficulty)

### D-3: Validation table
A table showing the new formula applied to the three existing tasks
(projection_bugfix, dotProduct_optimize, residual_stream_deadlock) with both
our real run data AND hypothetical "bad" candidates (area-bloated, budget-wasteful).
Must demonstrate that AC-1 through AC-8 all pass.

### D-4: Task difficulty / budget calibration
Recommendations for:
- Difficulty scale (1-5? 1-10?) with clear criteria per level
- Budget allocation per difficulty level
- Credit cost per tool type (should cosim really cost 20x csim?)

### D-5: Implementation roadmap
A phased plan for implementing the new scoring in code, including:
- Which files to change (`llm4hls/scoring.py`, `llm4hls/config.py`, etc.)
- Backward compatibility with existing run data
- Migration path for existing `run_report.json` files

---

## 7. REFERENCE: Complete file inventory

Key files the designer should read (all paths relative to `fpt26-agent-v2/`):

```
llm4hls/
  scoring.py       ← CURRENT scoring formula (the thing to redesign)
  config.py        ← Credit costs, timeouts, device target (all modifiable)
  harness.py       ← ToolServer — the metered tool interface
  tools.py         ← ToolResult / CSimTool / SynthTool / CoSimTool
  report.py        ← SynthReport / CoSimResult parsers
  task.py          ← Task dataclass and loader
  budget.py        ← Budget / BudgetExceeded

agent/
  reporting.py     ← write_run_report() — the JSON report generator
  eval.py          ← Cross-run evaluation tool (reads run_report.json)
  agents/base.py   ← RunState / AgentConfig / AgentResult
  workflow.py      ← Pipeline builder (step ordering)
  main.py          ← CLI entry point

tasks/
  dotProduct_optimize/     ← Example optimize task
  projection_bugfix/       ← Example repair task
  residual_stream_deadlock/ ← Example structural task
```

---

## 8. APPENDIX: Real run data for validation

The following is the COMPLETE raw output from running the v2 agent against all
three tasks with `--mode full`.  Each transcript is annotated with the specific
scoring-formula defect it exposes.

---

### 8.1 Task A: projection_bugfix (repair, difficulty=2, budget=20)

**Task goal**: Find and fix a functional bug in the `angle==0` branch.  This is
a pure repair task — no optimization is expected or possible (the kernel is
combinational logic, latency=0).

**Raw agent transcript**:
```
=== Agent run complete: completed ===
Transcript (4 tool calls):
  #1  [csim] runtime_fail (rc=1, 7.2s)   [spent 1/20]
  #2  [csim] pass (rc=0, 5.9s)   [spent 2/20]
  #3  [synth] pass (rc=0, 16.3s) | latency(worst)=0 cyc  II=1  clk~2.538ns
       LUT=692 FF=0 DSP=0 BRAM=0 URAM=0   [spent 6/20]
  #4  [synth] pass (rc=0, 16.2s) | latency(worst)=0 cyc  II=1  clk~2.538ns
       LUT=692 FF=0 DSP=0 BRAM=0 URAM=0   [spent 10/20]
  budget 10/20 credits spent (csimx2, synthx2)

=== Scorecard: projection_bugfix (difficulty 2) ===
  functional (hidden TB): PASS
  synthesizable         : PASS
  baseline latency      : 0 cyc
  candidate latency     : 0 cyc
  candidate resources   : LUT=692 FF=0 DSP=0 BRAM=0
  SCORE                 : 1.400
```

**Scoring breakdown** (current formula):
```
score = 2 × (0.5×1.0 + 0.2×1.0 + 0.3×0.0)
      = 2 × 0.7
      = 1.400
```
ppa_norm = 0 because latency_baseline=0, latency_candidate=0 → acceleration=0/0 (undefined) → treated as 0.

**Scoring defects exposed**:

| # | Defect | Evidence in this run |
|---|---|---|
| D1 | **Repair tasks structurally capped at 70%** | Agent found the bug in 1 LLM attempt, verified correctness, passed synth — a perfect repair. But max possible score = difficulty×0.7 = 1.4/2.0. A repair task can NEVER exceed 70% because latency=0 (combinational logic) means ppa_norm is always 0. |
| D2 | **No budget efficiency reward** | Agent used only 10/20 credits (50%) — very efficient. Same score whether it used 10 or 20. |
| D3 | **No attempt-efficiency metric** | First csim failed (as expected — the starting code has a bug). LLM fixed it on attempt #2. A "1-attempt fix" and "5-attempt fix" get identical scores. |

**The key question this run poses for the new formula**:
*If the agent does everything right on a repair task — finds the bug quickly,
wastes no budget, produces identical PPA — what score should it get?  Currently
1.4/2.0.  Arguably it should be closer to 2.0/2.0.*

---

### 8.2 Task B: dotProduct_optimize (optimize, difficulty=3, budget=40)

**Task goal**: Reduce latency of a sequential dot-product accumulation loop
(NUM_FEATURES=1024) through HLS pragmas (pipeline, unroll, array partition).

**Raw agent transcript**:
```
=== Agent run complete: completed ===
Transcript (6 tool calls):
  #1  [csim] pass (rc=0, 7.2s)   [spent 1/40]
  #2  [synth] pass (rc=0, 16.8s) | latency(worst)=1027 cyc  II=1025  clk~3.17ns
       LUT=156 FF=93 DSP=2 BRAM=0 URAM=0   [spent 5/40]
  #3  [csim] pass (rc=0, 6.2s)   [spent 6/40]
  #4  [synth] pass (rc=0, 184.2s) | latency(worst)=38 cyc  II=39  clk~3.17ns
       LUT=13189 FF=54194 DSP=64 BRAM=0 URAM=0   [spent 10/40]
  #5  [csim] pass (rc=0, 6.5s)   [spent 11/40]
  #6  [synth] synth_error (rc=1, 16.4s)   [spent 15/40]
  budget 15/40 credits spent (csimx3, synthx3)

=== Scorecard: dotProduct_optimize (difficulty 3) ===
  functional (hidden TB): PASS
  synthesizable         : PASS
  baseline latency      : 1027 cyc
  candidate latency     : 38 cyc
  acceleration          : 27.03x  (opt=True)
  candidate resources   : LUT=13189 FF=54194 DSP=64 BRAM=0
  SCORE                 : 3.000
```

**Scoring breakdown** (current formula):
```
acceleration  = 1027 / 38 = 27.03x
ppa_norm      = min(27.03, 8.0) / 8.0 = 1.0    ← CAPPED!
score         = 3 × (0.5×1.0 + 0.2×1.0 + 0.3×1.0) = 3.000
```

**Resource comparison**:
```
                    LUT      FF      DSP    Latency
Baseline:           156      93       2     1027 cyc
Candidate:         13189   54194     64       38 cyc
Growth:            +84.5x  +582.7x  +32x      -96.3%
```

**Scoring defects exposed**:

| # | Defect | Evidence in this run |
|---|---|---|
| D4 | **Area has ZERO weight** | LUT exploded by 84.5x, FF by 582.7x. The candidate uses 1% of the U55C's LUTs so this particular case "gets away with it" — but the formula does not distinguish this from a candidate that achieved the same 27x with LUT=500. Both get 3.0/3.0. A denser task that hits the device ceiling would fail synthesis entirely while a smarter agent might succeed. The formula should REWARD the smarter agent preemptively. |
| D5 | **ACCEL_CAP=8.0 eliminates differentiation** | 27.03x is reduced to 8.0 for scoring. The extra 19x of acceleration is invisible. If another agent got exactly 8x with the same area, both get identical scores. There is NO incentive to push beyond 8x. |
| D6 | **No throughput (II) reward** | Baseline II=1025 (one result every 1025 cycles, i.e., sequential). Candidate II=39 (pipelined but still has initiation interval). A design with II=1 (new result every cycle) at the same latency=38 would get the SAME score. II — which directly governs throughput — is completely ignored. |
| D7 | **No area-efficiency dimension** | The agent achieved 27x speedup but paid 84x area. The "speedup per unit area" (resource_efficiency) is 27/84.5 = 0.32x — the design is actually LESS area-efficient than baseline. A good scoring formula would flag this tradeoff. |

**The key question this run poses for the new formula**:
*How should the formula balance latency improvement against area cost?  If
Candidate A has acceleration=27x with area_growth=80x, and Candidate B has
acceleration=10x with area_growth=2x, which is "better"?  The current formula
says they're equal (both capped at 8x, area ignored).  A good formula forces
this tradeoff to be explicit.*

**Hypothetical counterfactuals for validation**:
```
┌─────────────────────┬──────────┬───────────┬──────────┬───────────────┐
│ Candidate           │ Accel    │ LUT       │ FF       │ Current score │
├─────────────────────┼──────────┼───────────┼──────────┼───────────────┤
│ A (our run)         │ 27.03x   │ 13189     │ 54194    │ 3.000 ← SAME  │
│ B (area-efficient)  │ 10.00x   │ 500       │ 200      │ 3.000 ← SAME  │
│ C (balanced)        │ 15.00x   │ 2000      │ 800      │ 3.000 ← SAME  │
│ D (extreme)         │ 100.00x  │ 50000     │ 200000   │ 3.000 ← SAME  │
└─────────────────────┴──────────┴───────────┴──────────┴───────────────┘
```
All four candidates score 3.000.  This is the central problem the new formula
must solve.

---

### 8.3 Task C: residual_stream_deadlock (structural, difficulty=4, budget=80)

**Task goal**: Fix a streaming/dataflow deadlock in a 3-stage pipeline connected
by `hls::stream` FIFOs.  C-simulation passes (unbounded FIFOs), but C/RTL
co-simulation deadlocks (bounded depth-2 RTL FIFOs).  Agent must diagnose from
cosim feedback and restructure the dataflow.

**Raw agent transcript**:
```
=== Agent run complete: completed ===
Transcript (6 tool calls):
  #1  [csim] pass (rc=0, 9.8s)   [spent 1/80]
  #2  [synth] pass (rc=0, 16.4s) | latency(worst)=135 cyc  II=136  clk~2.796ns
       LUT=539 FF=248 DSP=0 BRAM=0 URAM=0   [spent 5/80]
  #3  [cosim] cosim_fail (rc=1, 49.1s)   [spent 25/80]
  #4  [cosim] cosim_fail (rc=1, 38.7s)   [spent 45/80]
  #5  [csim] pass (rc=0, 4.8s)   [spent 46/80]
  #6  [cosim] pass (rc=0, 41.0s) | cosim=Pass measured_latency(max)=97
       [spent 66/80]
  budget 66/80 credits spent (csimx2, synthx1, cosimx3)

=== Scorecard: residual_stream_deadlock (difficulty 4) ===
  functional (hidden TB): PASS
  synthesizable         : PASS
  cosim (C/RTL verify)  : PASS
  baseline latency      : 135 cyc
  candidate latency     : 68 cyc
  acceleration          : 1.99x  (opt=True)
  candidate resources   : LUT=406 FF=231 DSP=0 BRAM=0
  SCORE                 : 3.098
```

**Scoring breakdown** (current formula):
```
acceleration  = 135 / 68 = 1.99x
ppa_norm      = min(1.99, 8.0) / 8.0 = 0.248
score         = 4 × (0.5×1.0 + 0.2×1.0 + 0.3×0.248)
              = 4 × 0.7745
              = 3.098
```

**Latency discrepancy**:
```
Synth estimated latency:  68 cycles
Cosim MEASURED latency:   97 cycles (max)   ← actual RTL ground truth
Cosim latency min/avg/max: min=? / avg=? / max=97
```
The formula uses synth-estimated 68 cycles → acceleration=1.99x.
If it used cosim-measured 97 cycles → acceleration=135/97=1.39x → ppa_norm=0.174 → score=2.896.
**The formula uses the wrong latency source for structural tasks.**

**Scoring defects exposed**:

| # | Defect | Evidence in this run |
|---|---|---|
| D8 | **Cosim failure cost is invisible in score** | cosim costs 20 credits per call. The agent failed twice (40 credits wasted = 50% of budget) before succeeding. The scorecard shows 3.098 regardless of whether it took 1 or 10 cosim attempts. |
| D9 | **Cosim-measured latency is ignored** | The CoSimResult contains actual RTL-measured latency (max=97). The formula uses synth-estimated 68 cycles instead. For structural tasks where the whole point is RTL-level correctness, using synthesis estimates over RTL measurements is inconsistent. |
| D10 | **Area improvement is not rewarded** | The candidate IMPROVED area (LUT 539→406, -25%; FF 248→231, -7%) while achieving 1.99x acceleration. This is an unambiguously good result — faster AND smaller. But the formula gives it 77.5% — lower than the area-bloated dotProduct's 100%. |
| D11 | **Budget consumption is not penalised** | 66/80 credits (82.5%) with 2 failed cosim attempts. A hypothetical agent that fixed the deadlock on the first cosim (spending 26/80 = 32.5%) would get the SAME score for the SAME final kernel. The wasted 40 credits are invisible. |

**The key question this run poses for the new formula**:
*A structural task where the agent improves BOTH latency and area — but needs 3
cosim attempts to get there — scores 77.5%. An optimize task where the agent
blows up area by 84x scores 100%. Is this the right ordering?  Arguably, the
residual result is objectively better engineering: faster, smaller, correct at
RTL level. The formula should reflect this.*

---

### 8.4 Summary: defect-to-task cross-reference

```
Defect                          projection   dotProduct   residual   Priority
─────────────────────────────────────────────────────────────────────────────
D1  Repair tasks capped at 70%      ●                                 CRITICAL
D2  No budget efficiency            ●                        ●         HIGH
D3  No attempt-efficiency           ●                        ●         MEDIUM
D4  Area has ZERO weight                       ●              ●         CRITICAL
D5  ACCEL_CAP removes diff.                    ●                        CRITICAL
D6  No throughput/II dimension                 ●                        HIGH
D7  No area-efficiency metric                  ●                        HIGH
D8  Cosim failure cost invisible                          ●         HIGH
D9  Cosim latency ignored                                 ●         HIGH
D10 Area improvement not rewarded                         ●         MEDIUM
D11 Budget overrun not penalised                           ●         HIGH
─────────────────────────────────────────────────────────────────────────────
```

**The three CRITICAL defects (D1, D4, D5) alone mean the current formula cannot
reliably rank agent performance.  The seven HIGH defects mean it misses
dimensions that an HLS engineer would consider essential in evaluating a design.
Fixing D1-D11 is the scope of this redesign.**

---

**END OF BRIEF**
