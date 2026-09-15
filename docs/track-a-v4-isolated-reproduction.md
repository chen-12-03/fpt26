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
MODEL_ID=qwen3.6-27b \
ENV_FILE=/tmp/fpt26_qwen36.env \
BACKEND=custom \
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
MODEL_ID=qwen3.6-27b \
ENV_FILE=/tmp/fpt26_qwen36.env \
BACKEND=custom \
SHARD_COUNT=3 SHARD_INDEX=all \
./run_track_a_v4_split.sh
```

Interrupted output is never silently overwritten. Continue only the same run
contract with `RESUME=1`; use a fresh `RUN_LABEL` for retries or changed code,
model, budgets, or inputs.

The launcher returns a nonzero status when any shard record has an audit
error. A completed HLS result can still fail this audit, for example when the
model environment omits required license and source evidence.

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

The historical `scoring.run_p0_real_api_shard` shared-container entry point is
disabled by default. Its `--allow-legacy-shared-container` switch exists only
to reproduce already published historical execution, not for new evidence.
