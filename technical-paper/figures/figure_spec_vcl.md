# Figure Spec: Verified-Candidate Loop

## Identity

- **Figure ID:** `fig:vcl`
- **Paper section:** Section II
- **Placement:** full-width (`figure*`)
- **Archetype:** architecture overview
- **Generation backend:** user-supplied vector PDF

## Purpose

- **Paper claim supported:** The VCL prevents a candidate that fails any
  available required gate from replacing the verified fallback.
- **What it shows:** The LLM proposes a candidate. A candidate reaches
  promotion only after the complete validation chain passes; it replaces the
  verified fallback only when its `Q_HW` also increases. Failures feed repair
  or Failure Reflection, and an unaffordable validation returns the verified
  fallback.
- **Why this figure exists:** The gate ordering, feedback branches, and
  promotion boundary are harder to recover from equations or prose.
- **Role in narrative:** design explanation

## Content Specification

### Components

| Component | Label | Shape | Color | Description |
|---|---|---|---|---|
| task | Task + starter | parallelogram | Grey | Public specification and editable kernel |
| proposer | LLM proposal | rounded box | Cyan | Produces one full source candidate |
| budget | Budget admission | diamond | Yellow | Requires credits for the complete candidate tool plan |
| interface | Interface gate | diamond | Blue | Checks includes, signature, and source shape |
| csim | CSim gate | diamond | Blue | Checks public functional behavior |
| synth | Synth gate | diamond | Blue | Produces latency, clock, and resource evidence |
| target | Target gates | diamond | Blue | Checks 100 MHz and U55C capacity |
| cosim | Required CoSim | diamond | Blue | Checks RTL behavior for streaming tasks |
| metric | Metric completeness | diamond | Blue | Requires latency, clock, and five resource counts |
| qor | `Q_HW` selection | diamond | Green | Promotes only a measured improvement |
| reflection | Failure Reflection | rounded box | Yellow | Extracts diagnostics, diff, and next constraint |
| rag | QoR-RAG | rounded box | Cyan | Retrieves a rule, success, and failure case |
| fallback | Verified fallback | cylinder | Green | Stores the latest kernel that passed every available required gate |
| output | Verified fallback + evidence | parallelogram | Green | Submission artifact and report |

### Connections

| From | To | Label | Style | Description |
|---|---|---|---|---|
| task | proposer | task context | arrow | Starts one proposal round |
| rag | proposer | bounded context | arrow | Adds compatible evidence |
| proposer | budget | candidate | arrow | Checks affordability before candidate tools |
| budget | interface | admit | arrow | Begins candidate validation |
| interface | csim | pass | arrow | Continues the validation chain |
| csim | synth | pass | arrow | Continues the validation chain |
| synth | target | report | arrow | Applies timing and capacity checks |
| target | cosim | when required | arrow | Checks bounded streaming behavior |
| cosim | metric | pass / N.A. | arrow | Checks score inputs |
| metric | qor | complete | arrow | Enters measured selection |
| qor | fallback | improve | arrow | Promotes the candidate |
| fallback | output | stop | arrow | Emits the selected verified fallback |
| any failed gate | reflection | fail | dashed arrow | Builds bounded failure evidence |
| reflection | rag | history | arrow | Changes the next retrieval query |
| reflection | proposer | repair constraint | arrow | Guides the next candidate |
| budget | fallback | insufficient credits | dashed arrow | Stops before partial validation |

### Groupings

| Group | Contains | Label | Style |
|---|---|---|---|
| proposal | rag, proposer, reflection | Evidence-guided proposal | dashed border |
| admission | budget | Budget control | dashed border |
| validation | interface, csim, synth, target, cosim, metric | Validation chain | dashed border |
| promotion | qor, fallback | Promotion boundary | dashed border |

### Annotations

- Mark the candidate boundary before the interface gate.
- Mark every failure edge as non-promoting.
- Show CoSim as conditional.
- Show that Budget admission precedes the validation chain.

## Layout

- **Flow direction:** left-to-right main path with one lower feedback loop
- **Hierarchy levels:** two
- **Symmetry constraints:** all validation diamonds share size and style
- **Size target:** 7.0 inches wide and approximately 1.15 inches high,
  excluding caption

## Styling

- **Color mapping:** Grey for inputs, Cyan for proposal/retrieval, Blue for
  validation, Yellow for failure evidence, Green for accepted state/output
- **Emphasis:** `Q_HW` selection and Verified fallback use a 1.0 pt green border
- **Consistency notes:** future component figures must reuse these names and colors

## Generation

**Expected asset:** `technical-paper/figures/vcl_workflow.pdf`

## Caption

**Draft caption:** Measured evidence controls every state transition. The
agent proposes through a bounded interface; only a candidate that passes every
applicable gate and improves `Q_HW` can replace the verified fallback.

## Status

- **Spec complete:** yes
- **Generated:** no
- **Critique passed:** no
- **Iteration notes:** Generation is outside the current text-only stage.
