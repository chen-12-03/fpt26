#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
IMAGE=${FPT26_AGENT_IMAGE:?set FPT26_AGENT_IMAGE to the clean image tag}
ENV_FILE=${FPT26_ENV_FILE:-/tmp/fpt26.env}
OUTPUT_NAME=${1:?usage: run-p0-official-fresh.sh <fresh-output-name>}
HOST_OUTPUT_ROOT="$REPO_ROOT/runs/$OUTPUT_NAME"
CONTAINER_OUTPUT_ROOT="/workspace/runs/$OUTPUT_NAME"
TASK_ROOT=/workspace/tasks/official
VITIS_ROOT=/tools/Xilinx/2025.2/Vitis

test -f "$ENV_FILE" || {
  echo "official-fresh: env file not found: $ENV_FILE" >&2
  exit 2
}
test ! -e "$HOST_OUTPUT_ROOT" || {
  echo "official-fresh: refusing to reuse output: $HOST_OUTPUT_ROOT" >&2
  exit 2
}
mkdir -p "$HOST_OUTPUT_ROOT"

docker_base=(
  docker run --rm
  -e PYTHONPATH=/workspace:/workspace/fpt26-agent-v3:/workspace/fpt26-harness
  -e PYTHONDONTWRITEBYTECODE=1
  -v "$REPO_ROOT:/workspace"
  -v /tools/Xilinx:/tools/Xilinx:ro
  -w /workspace/fpt26-agent-v3
)

"${docker_base[@]}" \
  "$IMAGE" \
  python3 -m scoring.snapshot_execution_source \
    --output "$CONTAINER_OUTPUT_ROOT/execution-source-start.json"

for task_id in \
  projection_bugfix \
  dotProduct_optimize \
  residual_stream_deadlock
do
  submission_root="$CONTAINER_OUTPUT_ROOT/$task_id/submission"
  evaluator_root="$CONTAINER_OUTPUT_ROOT/$task_id/evaluator"
  "${docker_base[@]}" \
    --env-file "$ENV_FILE" \
    "$IMAGE" \
    bash -lc \
    "source '$VITIS_ROOT/settings64.sh' && \
     python3 -m agent.main \
       --task '$TASK_ROOT/$task_id' \
       --mode auto \
       --run-role submission \
       --backend custom \
       --output-root '$submission_root'" \
    >"$HOST_OUTPUT_ROOT/${task_id}_submission.log" 2>&1

  final_candidates=(
    "$HOST_OUTPUT_ROOT/$task_id/submission/$task_id"/final_*.cpp
  )
  test "${#final_candidates[@]}" -eq 1
  final_container_path=$(
    realpath --relative-to="$REPO_ROOT" "${final_candidates[0]}"
  )
  submission_evidence_host_path="$HOST_OUTPUT_ROOT/$task_id/submission/$task_id/submission_evidence.json"
  test -f "$submission_evidence_host_path"
  submission_evidence_container_path=$(
    realpath --relative-to="$REPO_ROOT" \
      "$submission_evidence_host_path"
  )

  "${docker_base[@]}" \
    "$IMAGE" \
    bash -lc \
    "source '$VITIS_ROOT/settings64.sh' && \
     python3 -m agent.main \
       --task '$TASK_ROOT/$task_id' \
       --run-role evaluator \
       --final-kernel '/workspace/$final_container_path' \
       --submission-evidence \
         '/workspace/$submission_evidence_container_path' \
       --output-root '$evaluator_root'" \
    >"$HOST_OUTPUT_ROOT/${task_id}_evaluator.log" 2>&1
done

"${docker_base[@]}" \
  "$IMAGE" \
  python3 -m scoring.snapshot_execution_source \
    --output "$CONTAINER_OUTPUT_ROOT/execution-source-end.json"

echo "official-fresh: completed output=$HOST_OUTPUT_ROOT"
