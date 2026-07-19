# Track-A P0 compliance report

This report maps the P0 execution-layer remediation to the Track-A
requirements in [aaa Submission Guidelines for Track-A.md](aaa%20Submission%20Guidelines%20for%20Track-A.md).
All acceptance claims below must be backed by fresh Docker artifacts; archived
pre-P0 reports are not counted.

**Current status (2026-07-19): real acceptance passed; final clean-image build
pending explicit execution approval.** The seven P0 remediations are
implemented. Fresh final-source runs passed the 97-task aggregate audit and
the three-official split-role audit with real custom API and Vitis 2025.2.
The remaining release operation is the no-cache final image build, its
post-build reruns, and the final execution-freeze manifest. No mock, replay,
cached kernel, or mixed-revision evidence is counted.

## Scope and trust boundary

The implemented workflow is:

```text
public task package
  -> submission preflight
  -> auto baseline/repair/structural repair/optimization
  -> public final kernel
  -> isolated evaluator
  -> hidden grading or explicitly labelled public_fallback
```

The submission process constructs an official `Task` object from public files
only. It neither loads nor grades `hidden/` or `reference/`. The evaluator is a
separate CLI role and receives only the finalized kernel path plus the
evaluator-owned task package.

For every new candidate, the mandatory order is:

```text
Interface
  -> CSim
  -> Synth
  -> 100 MHz frequency gate
  -> device-capacity gate
  -> required CoSim
  -> Q_HW comparison
```

No failed or partially checked LLM proposal can replace the last fully
verified kernel.

## Seven P0 remediations

| P0 item | Implementation | Fail-closed behavior |
|---|---|---|
| Submission/evaluator isolation | `--run-role submission\|evaluator`, public-only loader, evaluator-owned grading | submission task metadata cannot name hidden/reference paths; submission reports contain no grading trace |
| Unified candidate validator | immutable top signature/include contract and SHA-256 interface fingerprint | interface failure spends no downstream tool credits |
| Correctness-first candidate acceptance | one shared gate sequence in repair, structural repair, optimization and evaluator paths | failed CSim/Synth/capacity/frequency/required CoSim discards the candidate |
| 100 MHz final gate | measured synthesis clock must be finite, positive and `<=10.0 ns` | missing, zero, NaN or `>10.0 ns` fails; no inferred frequency is used |
| Canonical status semantics | `running`, `completed`, `failed`, `budget_exceeded`, `infrastructure_error` | status, stop reason, report and CLI exit code are aligned; bootstrap exceptions also write reports |
| Tool-result-driven auto route | default `--mode auto`; routing uses CSim/Synth/CoSim results, not task type labels | unsuccessful/no-op repair, timeout or insufficient budget returns verified best/fallback with a non-success status |
| Preflight, budget and audit | U55C, Vitis 2025.2, task files, official budget, model evidence, tokens, credits, wall time and tool count | budget cannot be increased; unproven models are labelled unproven; sensitive endpoint/key text is redacted |

The scoring implementation and `scoring-freeze.json` are unchanged.

## Docker verification

Clean image: `fpt26-agent-v3:p0-clean-20260719`, local immutable image ID
`sha256:2450e1d03d85f7141164e7b6c420eeb37c9d1eaa78626e863d86f900e59efa89`.
It has no registry `RepoDigest`; the value above is an image ID, not a claimed
registry digest.

| Suite | Result |
|---|---:|
| P0 targeted tests | **75 passed in 9.42 s** |
| Final complete `tests` + `scoring` suite | **237 passed in 21.18 s** |
| Scoring and scoring-freeze focused tests | **84 passed in 0.20 s** |
| Execution + scoring freeze focused tests | **5 passed in 0.24 s** |
| Failures | **0** |
| Skips | **0** |

The real-Vitis test command sets `FPT26_REAL_VITIS_TESTS=1`, sources Vitis
2025.2 inside Docker, mounts `/tools/Xilinx` read-only, and targets
`xcu55c-fsvh2892-2L-e`.

After the fresh official and 97-task real acceptance runs passed, the
execution freeze was advanced last. It now locks all 29 Agent Python sources,
the execution/scoring launchers and auditors, Docker definitions, both harness
implementations, and all 745 files in the task corpus. The complete suite then
passed with zero failures and zero skips.

The official acceptance auditor also independently recomputes frequency from
the measured candidate clock rather than trusting `gate.ok`. Submission final
kernel, submission required-CoSim source, evaluator input kernel and evaluator
required-CoSim source must have matching SHA-256 values. This closes the
evidence gap where a truthful-looking report could otherwise refer to a
different kernel.

## Three official fresh runs

The final-source isolated split-role run is
`runs/p0_official_final_20260719_v3`. Its execution source was stable from
start to end at
`b06672fbcae284a4f562f2f214a3e486e202c898ee7975f4af890e4670d8538e`.
The independent machine auditor passed 3/3 tasks with zero errors:

| Task | Submission | Evaluator | Final MHz | Required CoSim | API requests / tokens | Credits | Grading source |
|---|---:|---:|---:|---:|---:|---:|---|
| `projection_bugfix` | completed | completed, score 73.37 | 394.011 | N/A | 3 / 12,198 | 11 / 20 | `public_fallback` |
| `dotProduct_optimize` | completed | completed, score 76.52 | 315.457 | N/A | 2 / 6,464 | 15 / 40 | `public_fallback` |
| `residual_stream_deadlock` | completed | completed, score 85.33 | 354.862 | pass, measured latency 66 | 2 / 7,779 | 50 / 80 | `public_fallback` |

The supplied official packages do not contain evaluator hidden testbench
files. Therefore their evaluator results are deliberately labelled
`public_fallback`; this report does not claim that official hidden tests
passed. The generated regression corpus does contain hidden testbenches and is
reported separately as `hidden`.

The final clean-image official rerun remains blocked by the external API
account state. The interim artifacts are under
`runs/p0_official_fresh_20260719_v1`; they are preserved but explicitly
excluded from final freeze acceptance.

## 97-task fresh regression

The fresh split-role run recorded exactly 97 tasks and 97 evaluator reports.
The current machine audit intentionally returns exit code 4 because 53
submissions have incomplete API usage after the provider rejected their real
requests:

| Measure | Fresh result |
|---|---:|
| Exact task coverage | **97 / 97; no missing or unexpected task** |
| `completed` | **29** |
| `no_valid_anchor` | **7** |
| `failed` | **8** |
| `budget_exceeded` | **0** |
| `infrastructure_error` | **53** |
| Submission hidden/reference accesses | **0; public-only 97 / 97** |
| Tasks with complete real-API usage evidence | **44 / 97** |
| API requests / responses / failed requests | **119 / 66 / 53** |
| Prompt / completion / total tokens | **283,585 / 48,166 / 331,751** |
| Credits / tool calls | **711 / 278** |
| Interface / 100 MHz / resource gates | **97 / 88 / 96** |
| Fully verified final artifacts | **87** |
| Required CoSim gates | **0 / 1 in this regression; residual candidate rejected** |
| Minimum observed reported frequency | **66.028 MHz** |
| Evaluator grading source counts | **94 `hidden`, 3 `public_fallback`** |

Tasks stopped by a deterministic pre-LLM gate may correctly have zero API
requests. They still record the configured real custom client and an exact
zero-request usage snapshot; they are not presented as API successes.

The eight deterministic failures are fail-closed candidate clock/frequency
failures. They did not continue to scoring after the failed gate. The seven
`no_valid_anchor` records completed real API, public correctness and synthesis,
but no finite starter/reference anchor existed. The 53 infrastructure errors
are the exact retry set in the machine audit.

This run remains valid diagnostic evidence, but it predates the final
required-CoSim source-hash and execution-source snapshot strengthening.
Consequently, final acceptance will rerun all 97 tasks with the final source
tree; it will not merely replace the 53 API failures and mix evidence from two
execution revisions.

A new clean-image probe with the Vitis tree mounted read-only and Vitis 2025.2
sourced made one real custom API request. Submission returned canonical
`infrastructure_error`/exit 6 with incomplete token usage; its independent
hidden evaluator completed successfully. The provider response was HTTP 400
`account is not in good standing`. Endpoint and credentials are redacted in
the report. This isolates the current blocker from Docker, Vitis and evaluator
operation.

The same condition was verified for the third consecutive Goal turn using the
current 39-file execution source tree. The fresh r3 probe recorded
source-stable=true, submission request/response/failed=`1/0/1`, submission
`infrastructure_error`/exit 6, and hidden evaluator `completed`/exit 0. Under
the Goal blocked-audit policy, completion is now formally blocked on restoring
the external API account; no additional local implementation or validation
step can make the mandatory real-API runs succeed.

## Model compliance

The acceptance model alias is `qwen3-coder-plus`. The run report maps it to
`Qwen/Qwen3-Coder-480B-A35B-Instruct`, records Apache-2.0 evidence, and labels
the claim `proven`. The evidence is the
[official Qwen3-Coder release](https://qwenlm.github.io/blog/qwen3-coder/) and
the [official model card](https://huggingface.co/Qwen/Qwen3-Coder-480B-A35B-Instruct).
Unknown aliases are fail-closed as `unproven` unless model, license and source
evidence are all supplied explicitly.

## Reproduction

Full Docker/Vitis tests:

```bash
cd /home/chen1/projects/fpt26_new
FPT26_AGENT_IMAGE=<clean-image-tag> \
  ./fpt26-agent-v3/test_all.sh
```

Three fresh official split-role runs:

```bash
cd /home/chen1/projects/fpt26_new
FPT26_AGENT_IMAGE=<clean-image-tag> \
FPT26_ENV_FILE=/tmp/fpt26.env \
  ./fpt26-agent-v3/run-p0-official-fresh.sh <new-output-name>
```

The 97-task runner uses three Docker shards with
`scoring.run_p0_real_api_shard`; `scoring.reconcile_p0_evaluators` fills only
missing evaluator roles in the same fresh attempt, and
`scoring.audit_p0_acceptance` produces the final machine JSON.

Each shard records SHA-256 for 39 execution/scoring files at start and
after every task. Source drift aborts the shard; resume after source drift is
refused; the aggregate auditor requires identical stable source-tree hashes
across all shards. The accepted final-source tree SHA-256 is
`b06672fbcae284a4f562f2f214a3e486e202c898ee7975f4af890e4670d8538e`.

The accepted 97-task run used these fresh roots:

```bash
docker run --rm --env-file /tmp/fpt26.env \
  -e PYTHONPATH=/workspace/fpt26-agent-v3 \
  -v /home/chen1/projects/fpt26_new:/workspace \
  -v /tools/Xilinx:/tools/Xilinx:ro \
  -w /workspace/fpt26-agent-v3 \
  fpt26-agent-v3:p0-clean-20260719 \
  bash -lc 'source /tools/Xilinx/2025.2/Vitis/settings64.sh &&
    python3 -m scoring.run_p0_real_api_shard
      --task-root /workspace/tasks
      --output-root /workspace/runs/p0_97_finalsrc_20260719_s<0-or-1-or-2>
      --shard-index <0-or-1-or-2> --shard-count 3'
```

The aggregate contains 97/97 records, zero audit errors, zero infrastructure
errors and no retry IDs. Outcomes are completed=79, deterministic
frequency/clock failure=8, and no-valid-anchor=10. API request/response is
169/169 with zero failed or unreported responses and 793,267 tokens.
Submission isolation is public-only 97/97 with zero forbidden accesses;
evaluator sources are hidden=94 and explicitly labelled public fallback=3.
The final required-CoSim task passed 1/1.

## Final artifacts

| Artifact | Path / digest |
|---|---|
| 97-task final-source machine audit | `runs/p0_97_finalsrc_20260719_acceptance.json`, SHA-256 `43687ddf01fcd9b7b4c668d525732bad5a4395c27705588914f13dc2627f5b1d` |
| Real API blocker probe | `runs/p0_api_probe_20260719_r2/shard_summary.json`, SHA-256 `fac3199e2892c39b5f425a56801caf562f6cd7bf51207e589c22265dfa9be92e` |
| Third-turn formal blocker probe | `runs/p0_api_blocker_probe_20260719_r3/shard_summary.json`, SHA-256 `86b90ebcc1f96758341d5715bca725c9ad6b6a002747398e64267e55d2e78804` |
| Execution-source/Vitis zero-API probe | `runs/p0_source_snapshot_probe_20260719_v2/shard_summary.json`, SHA-256 `ae52d04f75cf26e89b285e541b55ae71a293dd8a84de681165fb7b1c75979300` |
| Official final-source machine audit | `runs/p0_official_final_20260719_v3_acceptance.json`, SHA-256 `b16127cbee402988430f7ffaf9d91362efe7b7d56c064ed798e90bb5ff004b51` |
| Current clean runtime image ID | `sha256:2450e1d03d85f7141164e7b6c420eeb37c9d1eaa78626e863d86f900e59efa89` |
| Scoring freeze | unchanged; SHA-256 `b067d4bf2fa02937412f5e367f40ca8f11b128e048bb9b7ff5007d157f200cf6` |
| Execution freeze | `fpt26-agent-v3/execution-freeze.json`, SHA-256 `372bd5c98840268ce38c3099e01a4951c614b5f1f7d3bdce07b4d7d2b3aacb38` |
| Interim official kernels and reports | `runs/p0_official_fresh_20260719_v1` (**not final clean acceptance**) |
| 97-task final-source kernels and reports | `runs/p0_97_finalsrc_20260719_s{0,1,2}` |

The machine audits contain SHA-256 values for every run report and final
kernel. The execution freeze and full regression are complete. Packaging the
final submission image/archive remains a release-material task; it does not
invalidate the accepted official execution evidence.
