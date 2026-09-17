# Track-A v4 isolated reproduction

The current campaign entry point is `run_track_a_v4_split.sh`. It enforces two
different Docker security boundaries for every task:

| Role | Task mount | API credentials | Network | Cross-boundary input |
|---|---|---|---|---|
| Submission | `public_agent/` only | yes | enabled | none |
| Evaluator | `evaluator_private/` only | no | `none` | final kernel and `submission_evidence.json`, read-only |

The Submission container does not mount the repository root. Its entry point
also reads `/proc/self/mountinfo` and fails if `/workspace`, an evaluator path,
or a `hidden/reference` mount is visible. The Evaluator fails unless its only
network interface is `lo`, no known API credential is present, both private
directories exist, the public task identity matches, and the final-kernel hash
matches both submission records.

## Inputs

- Docker image: `fpt26-agent-v3:latest`
- Vitis 2025.2: mounted read-only from `/tools/Xilinx` by default; set
  `VITIS_SDK` when the host installation lives elsewhere
- Public bundle: `releases/track_a_150_v4_20260911/public_agent`
- Evaluator bundle: `releases/track_a_150_v4_20260911/evaluator_private`
- One untracked environment file per model containing its API endpoint, key,
  exact model ID, and model-license/source evidence

The evaluator bundle may be moved outside the public repository. Set
`PRIVATE_ROOT=/absolute/path/to/evaluator_private`; the Submission mount list
is unchanged.

The name `evaluator_private` means private from the Submission process at
runtime. It is intentionally included in the public reproducibility release;
physical mount isolation, not repository secrecy, is the enforced boundary.

## Deterministic paper-data check

The submitted paper macros come from the committed canonical dataset and the
frozen evaluator mapping. This check uses no network, API key, or Vitis
license:

```bash
docker run --rm --network none \
  -v "$PWD:/workspace:ro" -w /workspace \
  fpt26-agent-v3:latest \
  python3 technical-paper/scripts/update_results.py --check
```

The command verifies both `technical-paper/results_generated.tex` and
`technical-paper/evaluator_results_generated.tex`. To regenerate the files,
use a writable repository mount, add `--user "$(id -u):$(id -g)"`, and remove
`--check`.

Verify the frozen public and evaluator corpus manifests separately:

```bash
VITIS_SDK=${VITIS_SDK:-/tools/Xilinx/2025.2/Vitis}
VITIS_MOUNT_ROOT=${VITIS_MOUNT_ROOT:-$(dirname "$(dirname "$VITIS_SDK")")}
VITIS_RELATIVE_PATH=$(realpath --relative-to="$VITIS_MOUNT_ROOT" "$VITIS_SDK")

docker run --rm --network none \
  -v "$PWD:/workspace:ro" \
  -v "$VITIS_MOUNT_ROOT:/tools/Xilinx:ro" \
  -e "LLM4HLS_VITIS_HLS_ROOT=/tools/Xilinx/$VITIS_RELATIVE_PATH" \
  -w /workspace \
  fpt26-agent-v3:latest \
  /bin/bash -lc 'source "$LLM4HLS_VITIS_HLS_ROOT/settings64.sh" && \
    python3 tools/audit_track_a_release.py \
      --release-root releases/track_a_150_v4_20260911 \
      --output /tmp/track_a_v4_release_audit.json'
```

`VITIS_SDK` must point to the directory containing `settings64.sh`, and it must
be below `VITIS_MOUNT_ROOT`. The launcher applies the same path mapping.

Evidence reproduction is deterministic. A new hosted-model campaign may
produce different source candidates because provider implementations and
model sampling can change.

## Basic smoke run

```bash
RUN_LABEL=split_smoke_qwen36 \
MODEL_ID=qwen/qwen3.6-27b \
ENV_FILE=/tmp/fpt26_qwen36.env \
BACKEND=openrouter \
SHARD_COUNT=1 SHARD_INDEX=0 \
TASK_IDS="ta2_cr_001 ta2_qo_001" \
MAX_REPAIR_ATTEMPTS=2 MAX_OPTIMIZATION_CANDIDATES=1 \
./run_track_a_v4_split.sh
```

## Full 150-task run

Omit `TASK_IDS`. `SHARD_INDEX=all` launches all shards concurrently; use a
single numeric shard index when jobs are managed externally.

```bash
RUN_LABEL=track_a_v4_qwen36_full150 \
MODEL_ID=qwen/qwen3.6-27b \
ENV_FILE=/tmp/fpt26_qwen36.env \
BACKEND=openrouter \
SHARD_COUNT=3 SHARD_INDEX=all \
./run_track_a_v4_split.sh
```

Interrupted output is never silently overwritten. Continue only the same run
contract with `RESUME=1`; use a fresh `RUN_LABEL` for retries or changed code,
model, budgets, or inputs.

Use the exact provider model identifier in both `MODEL_ID` and the environment
file. The identifiers used by the documented OpenRouter route are
`deepseek/deepseek-v4-pro`, `qwen/qwen3.5-122b-a10b`, and
`qwen/qwen3.6-27b`. A custom OpenAI-compatible endpoint may expose a different
identifier; record that exact endpoint value rather than silently rewriting it.

The launcher remains fail-closed and returns exit code 4 when any shard record
has an audit error. New summaries separate `execution_audit` from
`model_compliance`: a run may have a valid, isolated HLS execution while model
license/source provenance remains `unproven`. `overall_audit` still fails until
both dimensions pass.

## Reproducibility evidence

Each attempt contains:

```text
runs/<run>/shard_XX/tasks/<task>/attempt_NNN/
├── submission.log
├── submission/<task>/
│   ├── container_isolation.json
│   ├── final_<kernel>.cpp
│   ├── run_report.json
│   └── submission_evidence.json
├── evaluator.log
└── evaluator/<task>/
    ├── container_isolation.json
    └── run_report.json
```

`shard_summary.json` preserves the existing record structure used by the paper
data scripts and adds an explicit `isolation_contract`. The paper's starter-
anchored and reference-anchored values remain reproducible because the
Evaluator retains both private reference inputs and the unchanged scoring
engine; only the Submission container's visibility changed.

Future summaries use execution-source schema 2. The tree hash covers the agent,
the mounted `fpt26-harness`, and `run_track_a_v4_split.sh`; runtime provenance
also records the Git commit and dirty flag, Docker image ID/RepoDigests, and
Vitis SDK path. A locally built image may have no registry RepoDigest, in which
case its immutable local image ID is retained.

## Compare a rerun with the paper result

The comparison tool never modifies the canonical paper JSON. It writes a
separate task-level JSON and Markdown report:

```bash
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD:/workspace" -w /workspace \
  fpt26-agent-v3:latest \
  python3 tools/compare_track_a_v4_reproduction.py \
    --rerun-root runs/<new-run> \
    --paper-run-root runs/track_a_150_v4_deepseek_v4pro_nothink_full150_20260912_v1 \
    --output-json technical-paper/evidence/<comparison>.json \
    --output-md technical-paper/evidence/<comparison>.md
```

The retained cleanup-validation result is
[`track_a_v4_deepseek_reproduction_validation_20260917.md`](../technical-paper/evidence/track_a_v4_deepseek_reproduction_validation_20260917.md).

The historical `scoring.run_p0_real_api_shard` shared-container entry point is
disabled by default. Its `--allow-legacy-shared-container` switch exists only
to reproduce already published historical execution, not for new evidence.
