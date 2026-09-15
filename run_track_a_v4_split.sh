#!/usr/bin/env bash
# Reproducible Track-A v4 campaign with OS-level submission/evaluator isolation.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
HOST_REPO=${HOST_REPO:-$SCRIPT_DIR}
IMAGE=${IMAGE:-fpt26-agent-v3:latest}
ENV_FILE=${ENV_FILE:-/tmp/fpt26.env}
PUBLIC_ROOT=${PUBLIC_ROOT:-$HOST_REPO/releases/track_a_150_v4_20260911/public_agent}
PRIVATE_ROOT=${PRIVATE_ROOT:-$HOST_REPO/releases/track_a_150_v4_20260911/evaluator_private}
RUN_LABEL=${RUN_LABEL:?set RUN_LABEL to a fresh output name}
MODEL_ID=${MODEL_ID:?set MODEL_ID to the exact provider model ID}
BACKEND=${BACKEND:-custom}
SHARD_COUNT=${SHARD_COUNT:-3}
SHARD_INDEX=${SHARD_INDEX:-all}
TASK_IDS=${TASK_IDS:-}
RESUME=${RESUME:-0}
COMPETITION=${COMPETITION:-0}
LLM_TIMEOUT_S=${LLM_TIMEOUT_S:-360}
MAX_REPAIR_ATTEMPTS=${MAX_REPAIR_ATTEMPTS:-6}
MAX_OPTIMIZATION_CANDIDATES=${MAX_OPTIMIZATION_CANDIDATES:-5}
MAX_STRUCTURAL_REPAIR_ATTEMPTS=${MAX_STRUCTURAL_REPAIR_ATTEMPTS:-3}
CSIM_TIMEOUT_S=${CSIM_TIMEOUT_S:-30}
SYNTH_TIMEOUT_S=${SYNTH_TIMEOUT_S:-180}
COSIM_TIMEOUT_S=${COSIM_TIMEOUT_S:-240}
HOST_OUTPUT_ROOT=$HOST_REPO/runs/$RUN_LABEL
AGENT_ROOT=$HOST_REPO/fpt26-agent-v3
HARNESS_ROOT=$HOST_REPO/fpt26-harness
VITIS_ROOT=/tools/Xilinx/2025.2/Vitis

test -f "$ENV_FILE" || { echo "env file not found: $ENV_FILE" >&2; exit 2; }
test -d "$PUBLIC_ROOT" || { echo "public corpus not found: $PUBLIC_ROOT" >&2; exit 2; }
test -d "$PRIVATE_ROOT" || { echo "evaluator corpus not found: $PRIVATE_ROOT" >&2; exit 2; }
test -d "$AGENT_ROOT" || { echo "agent source not found: $AGENT_ROOT" >&2; exit 2; }
test -d "$HARNESS_ROOT" || { echo "harness source not found: $HARNESS_ROOT" >&2; exit 2; }
[[ "$SHARD_COUNT" =~ ^[1-9][0-9]*$ ]] || { echo "invalid SHARD_COUNT" >&2; exit 2; }
[[ "$RUN_LABEL" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || {
  echo "RUN_LABEL may contain only letters, digits, dot, underscore, and hyphen" >&2
  exit 2
}
if [[ "$SHARD_INDEX" != all ]]; then
  [[ "$SHARD_INDEX" =~ ^[0-9]+$ ]] || { echo "invalid SHARD_INDEX" >&2; exit 2; }
  (( SHARD_INDEX < SHARD_COUNT )) || { echo "SHARD_INDEX is outside SHARD_COUNT" >&2; exit 2; }
fi
if [[ -e "$HOST_OUTPUT_ROOT" && "$RESUME" != 1 ]]; then
  echo "refusing to reuse output root without RESUME=1: $HOST_OUTPUT_ROOT" >&2
  exit 2
fi
mkdir -p "$HOST_OUTPUT_ROOT"

mapfile -t ALL_TASK_IDS < <(
  docker run --rm \
    -v "$PUBLIC_ROOT:/fpt26-public-tasks:ro" \
    "$IMAGE" \
    python3 -c 'import json; from pathlib import Path; d=json.loads(Path("/fpt26-public-tasks/PUBLIC_CORPUS_MANIFEST.json").read_text()); print("\n".join(x["task_id"] for x in d["tasks"]))'
)
(( ${#ALL_TASK_IDS[@]} == 150 )) || {
  echo "expected 150 public tasks, found ${#ALL_TASK_IDS[@]}" >&2
  exit 2
}

declare -A AVAILABLE=()
for task_id in "${ALL_TASK_IDS[@]}"; do AVAILABLE["$task_id"]=1; done
SELECTED_TASK_IDS=()
if [[ -n "$TASK_IDS" ]]; then
  read -r -a SELECTED_TASK_IDS <<<"$TASK_IDS"
  for task_id in "${SELECTED_TASK_IDS[@]}"; do
    [[ -n "${AVAILABLE[$task_id]:-}" ]] || {
      echo "unknown task ID: $task_id" >&2
      exit 2
    }
  done
else
  SELECTED_TASK_IDS=("${ALL_TASK_IDS[@]}")
fi

common_mounts=(
  -v "$AGENT_ROOT:/opt/fpt26-agent:ro"
  -v "$HARNESS_ROOT:/opt/fpt26-harness:ro"
  -v /tools/Xilinx:/tools/Xilinx:ro
  -e PYTHONPATH=/opt/fpt26-agent:/opt/fpt26-harness
  -e PYTHONDONTWRITEBYTECODE=1
  -e PYTHONUNBUFFERED=1
  -e LLM4HLS_CSIM_TIMEOUT_S="$CSIM_TIMEOUT_S"
  -e LLM4HLS_SYNTH_TIMEOUT_S="$SYNTH_TIMEOUT_S"
  -e LLM4HLS_COSIM_TIMEOUT_S="$COSIM_TIMEOUT_S"
  -w /opt/fpt26-agent
)

run_submission() {
  local task_id=$1 attempt_root=$2
  local competition_args=()
  [[ "$COMPETITION" == 1 ]] && competition_args+=(--competition)
  docker run --rm \
    --name "fpt26-${RUN_LABEL//[^a-zA-Z0-9_.-]/-}-${task_id}-submission" \
    --env-file "$ENV_FILE" \
    "${common_mounts[@]}" \
    -e FPT26_LLM_TIMEOUT_SECONDS="$LLM_TIMEOUT_S" \
    -e FPT26_MAX_REPAIR_ATTEMPTS="$MAX_REPAIR_ATTEMPTS" \
    -e FPT26_MAX_OPTIMIZATION_CANDIDATES="$MAX_OPTIMIZATION_CANDIDATES" \
    -e FPT26_MAX_STRUCTURAL_REPAIR_ATTEMPTS="$MAX_STRUCTURAL_REPAIR_ATTEMPTS" \
    -v "$PUBLIC_ROOT:/fpt26-public-tasks:ro" \
    -v "$attempt_root/submission:/fpt26-output" \
    "$IMAGE" \
    bash -lc 'source /tools/Xilinx/2025.2/Vitis/settings64.sh && exec python3 -m scoring.isolated_role_entrypoint "$@"' \
    fpt26-entry submission \
      --task "/fpt26-public-tasks/$task_id" \
      --output-root /fpt26-output \
      --backend "$BACKEND" \
      --model "$MODEL_ID" \
      "${competition_args[@]}"
}

submission_completed() {
  local task_id=$1 attempt_root=$2
  docker run --rm \
    -v "$attempt_root/submission:/submission:ro" \
    "$IMAGE" \
    python3 -c 'import json,sys; from pathlib import Path; p=Path("/submission")/sys.argv[1]/"run_report.json"; raise SystemExit(0 if p.is_file() and json.loads(p.read_text()).get("status")=="completed" else 1)' \
    "$task_id"
}

run_evaluator() {
  local task_id=$1 attempt_root=$2
  docker run --rm \
    --name "fpt26-${RUN_LABEL//[^a-zA-Z0-9_.-]/-}-${task_id}-evaluator" \
    --network none \
    "${common_mounts[@]}" \
    -v "$PRIVATE_ROOT:/fpt26-evaluator-tasks:ro" \
    -v "$attempt_root/submission:/fpt26-submission:ro" \
    -v "$attempt_root/evaluator:/fpt26-output" \
    "$IMAGE" \
    bash -lc 'source /tools/Xilinx/2025.2/Vitis/settings64.sh && exec python3 -m scoring.isolated_role_entrypoint "$@"' \
    fpt26-entry evaluator \
      --task "/fpt26-evaluator-tasks/$task_id" \
      --submission-root /fpt26-submission \
      --output-root /fpt26-output
}

assemble_shard() {
  local shard=$1 shard_root=$2
  docker run --rm --network none \
    -v "$AGENT_ROOT:/opt/fpt26-agent:ro" \
    -v "$HARNESS_ROOT:/opt/fpt26-harness:ro" \
    -v "$shard_root:/fpt26-run" \
    -e PYTHONPATH=/opt/fpt26-agent:/opt/fpt26-harness \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -w /opt/fpt26-agent \
    "$IMAGE" \
    python3 -m scoring.assemble_isolated_shard \
      --shard-root /fpt26-run \
      --shard-index "$shard" \
      --shard-count "$SHARD_COUNT" \
      --report-prefix "runs/$RUN_LABEL/shard_$(printf '%02d' "$shard")" \
      --csim-timeout-s "$CSIM_TIMEOUT_S" \
      --synth-timeout-s "$SYNTH_TIMEOUT_S" \
      --cosim-timeout-s "$COSIM_TIMEOUT_S"
}

run_one_shard() {
  local shard=$1
  local shard_root=$HOST_OUTPUT_ROOT/shard_$(printf '%02d' "$shard")
  mkdir -p "$shard_root/tasks"
  local ordinal=0 selected=0
  for task_id in "${SELECTED_TASK_IDS[@]}"; do
    if (( ordinal % SHARD_COUNT != shard )); then
      ((ordinal+=1))
      continue
    fi
    ((ordinal+=1))
    ((selected+=1))
    local task_run_root=$shard_root/tasks/$task_id
    local attempt_number=1 attempt_root
    while [[ -d "$task_run_root/attempt_$(printf '%03d' "$attempt_number")" ]]; do
      ((attempt_number+=1))
    done
    if (( attempt_number > 1 )); then
      ((attempt_number-=1))
    fi
    attempt_root=$task_run_root/attempt_$(printf '%03d' "$attempt_number")
    if [[ -d "$attempt_root" \
          && ! -f "$attempt_root/submission/$task_id/run_report.json" \
          && "$RESUME" == 1 ]]; then
      ((attempt_number+=1))
      attempt_root=$task_run_root/attempt_$(printf '%03d' "$attempt_number")
    fi
    mkdir -p "$attempt_root/submission" "$attempt_root/evaluator"
    if [[ -f "$attempt_root/evaluator/$task_id/run_report.json" && "$RESUME" == 1 ]]; then
      echo "shard=$shard task=$task_id already evaluated; skipping"
      continue
    fi
    if [[ ! -f "$attempt_root/submission/$task_id/run_report.json" ]]; then
      echo "shard=$shard task=$task_id role=submission model=$MODEL_ID"
      if ! run_submission "$task_id" "$attempt_root" >"$attempt_root/submission.log" 2>&1; then
        echo "shard=$shard task=$task_id submission did not complete; see $attempt_root/submission.log" >&2
      fi
    fi
    if submission_completed "$task_id" "$attempt_root"; then
      echo "shard=$shard task=$task_id role=evaluator network=none"
      if ! run_evaluator "$task_id" "$attempt_root" >"$attempt_root/evaluator.log" 2>&1; then
        echo "shard=$shard task=$task_id evaluator did not complete; see $attempt_root/evaluator.log" >&2
      fi
    else
      echo "shard=$shard task=$task_id evaluator skipped: submission not completed"
    fi
  done
  local assemble_status=0
  assemble_shard "$shard" "$shard_root" || assemble_status=$?
  echo "shard=$shard finished selected=$selected output=$shard_root"
  return "$assemble_status"
}

echo "Track-A v4 physically isolated run"
echo "  run=$RUN_LABEL model=$MODEL_ID backend=$BACKEND"
echo "  public=$PUBLIC_ROOT"
echo "  evaluator=$PRIVATE_ROOT"
echo "  tasks=${#SELECTED_TASK_IDS[@]} shards=$SHARD_COUNT selected_shard=$SHARD_INDEX"

if [[ "$SHARD_INDEX" == all ]]; then
  pids=()
  for (( shard=0; shard<SHARD_COUNT; shard++ )); do
    run_one_shard "$shard" &
    pids+=("$!")
  done
  status=0
  for pid in "${pids[@]}"; do wait "$pid" || status=1; done
  exit "$status"
fi
run_one_shard "$SHARD_INDEX"
