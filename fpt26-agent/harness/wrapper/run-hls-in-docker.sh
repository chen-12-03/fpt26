#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
AGENT_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)

usage() {
  cat >&2 <<'EOF'
usage: run-hls-in-docker.sh \
  --task-id <id> \
  --candidate-prefix <prefix> \
  --top <function> \
  --source <path> \
  --testbench <path> \
  --clock-period <ns> \
  [--hls-part <part>]
EOF
}

TASK_ID=
CANDIDATE_PREFIX=
KERNEL_ENTRY=
SOURCE_FILE=
TESTBENCH_FILE=
HLS_CLOCK_PERIOD_NS=
HLS_PART=${HLS_PART:-xcu55c-fsvh2892-2L-e}
HLS_ARRAY_DEPTH=${HLS_ARRAY_DEPTH:-16}
HLS_TOP=${HLS_TOP:-top}
CSIM_ENTRY=
RUN_COSIM=${RUN_COSIM:-0}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task-id)
      TASK_ID=${2:-}
      shift 2
      ;;
    --candidate-prefix)
      CANDIDATE_PREFIX=${2:-}
      shift 2
      ;;
    --top)
      KERNEL_ENTRY=${2:-}
      shift 2
      ;;
    --source)
      SOURCE_FILE=${2:-}
      shift 2
      ;;
    --testbench)
      TESTBENCH_FILE=${2:-}
      shift 2
      ;;
    --clock-period)
      HLS_CLOCK_PERIOD_NS=${2:-}
      shift 2
      ;;
    --hls-part)
      HLS_PART=${2:-}
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

for required in TASK_ID CANDIDATE_PREFIX KERNEL_ENTRY SOURCE_FILE TESTBENCH_FILE HLS_CLOCK_PERIOD_NS; do
  if [[ -z "${!required}" ]]; then
    echo "error: missing required argument: $required" >&2
    usage
    exit 2
  fi
done

if ! python3 - "$HLS_CLOCK_PERIOD_NS" <<'PY'
import sys

try:
    value = float(sys.argv[1])
except ValueError:
    sys.exit(1)

if value <= 0:
    sys.exit(1)
PY
then
  echo "error: invalid clock period: $HLS_CLOCK_PERIOD_NS" >&2
  exit 2
fi

case "$SOURCE_FILE" in
  /*) SOURCE_FILE_ABS=$SOURCE_FILE ;;
  *) SOURCE_FILE_ABS=$AGENT_ROOT/$SOURCE_FILE ;;
esac
case "$TESTBENCH_FILE" in
  /*) TESTBENCH_FILE_ABS=$TESTBENCH_FILE ;;
  *) TESTBENCH_FILE_ABS=$AGENT_ROOT/$TESTBENCH_FILE ;;
esac

if [[ ! -f "$SOURCE_FILE_ABS" ]]; then
  echo "error: source file does not exist: $SOURCE_FILE_ABS" >&2
  exit 2
fi
if [[ ! -f "$TESTBENCH_FILE_ABS" ]]; then
  echo "error: testbench file does not exist: $TESTBENCH_FILE_ABS" >&2
  exit 2
fi
if [[ "$RUN_COSIM" != "0" ]]; then
  echo "error: RUN_COSIM is intentionally disabled for this baseline task" >&2
  exit 2
fi

CSIM_ENTRY=${CSIM_ENTRY:-$KERNEL_ENTRY}
CSIM_STATUS=not_run
SYNTH_STATUS=not_run
REPORT_STATUS=not_run
CSIM_EXIT_CODE=
SYNTH_EXIT_CODE=
REPORT_EXIT_CODE=
FINAL_EXIT_CODE=
CSYNTH_RPT=
REPORT_JSON=

if [[ -z "${RUN_DIR:-}" ]]; then
  RUN_ROOT=${RUN_ROOT:-$AGENT_ROOT/runs/$TASK_ID}
  mkdir -p "$RUN_ROOT"
  for index in $(seq -f "%03g" 0 999); do
    candidate="$RUN_ROOT/${CANDIDATE_PREFIX}_$index"
    if mkdir "$candidate" 2>/dev/null; then
      RUN_DIR=$candidate
      break
    fi
  done
  if [[ -z "${RUN_DIR:-}" ]]; then
    echo "error: no free run directory under $RUN_ROOT" >&2
    exit 2
  fi
else
  if [[ -e "$RUN_DIR" ]]; then
    echo "error: RUN_DIR already exists: $RUN_DIR" >&2
    exit 2
  fi
  mkdir -p "$RUN_DIR"
fi

mkdir -p "$RUN_DIR/logs" "$RUN_DIR/reports"

write_manifest() {
  CSIM_STATUS="$CSIM_STATUS" \
  SYNTH_STATUS="$SYNTH_STATUS" \
  REPORT_STATUS="$REPORT_STATUS" \
  CSIM_EXIT_CODE="$CSIM_EXIT_CODE" \
  SYNTH_EXIT_CODE="$SYNTH_EXIT_CODE" \
  REPORT_EXIT_CODE="$REPORT_EXIT_CODE" \
  FINAL_EXIT_CODE="$FINAL_EXIT_CODE" \
  CSYNTH_RPT="$CSYNTH_RPT" \
  REPORT_JSON="$REPORT_JSON" \
  python3 - "$RUN_DIR/manifest.json" <<'PY'
import json
import os
import sys

path = sys.argv[1]

def nullable_int(value):
    if value == "":
        return None
    return int(value)

manifest = {
    "task_id": os.environ["TASK_ID"],
    "candidate_prefix": os.environ["CANDIDATE_PREFIX"],
    "top": os.environ["HLS_TOP"],
    "kernel_entry": os.environ["KERNEL_ENTRY"],
    "source_file": os.environ["SOURCE_FILE_ORIGINAL"],
    "hls_source_file": os.environ["HLS_SOURCE_FILE"],
    "csim_helper_file": os.environ["CSIM_HELPER_FILE_STAGED"],
    "testbench_file": os.environ["TESTBENCH_FILE_ORIGINAL"],
    "hls_part": os.environ["HLS_PART"],
    "hls_clock_period_ns": os.environ["HLS_CLOCK_PERIOD_NS"],
    "hls_array_depth": os.environ["HLS_ARRAY_DEPTH"],
    "csim_entry": os.environ["CSIM_ENTRY"],
    "platform": os.environ.get("PLATFORM", ""),
    "run_dir": os.environ["RUN_DIR"],
    "run_cosim": os.environ["RUN_COSIM"],
    "stages": {
        "csim": os.environ["CSIM_STATUS"],
        "synth": os.environ["SYNTH_STATUS"],
        "report": os.environ["REPORT_STATUS"],
        "cosim": "not_run",
    },
    "stage_exit_codes": {
        "csim": nullable_int(os.environ["CSIM_EXIT_CODE"]),
        "synth": nullable_int(os.environ["SYNTH_EXIT_CODE"]),
        "report": nullable_int(os.environ["REPORT_EXIT_CODE"]),
    },
    "artifacts": {
        "csynth_report": os.environ["CSYNTH_RPT"] or None,
        "report_json": os.environ["REPORT_JSON"] or None,
    },
    "final_exit_code": nullable_int(os.environ["FINAL_EXIT_CODE"]),
}

with open(path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)
    f.write("\n")
PY
}

on_exit() {
  local code=$?
  FINAL_EXIT_CODE=$code
  write_manifest >/dev/null 2>&1 || true
  exit "$code"
}

trap on_exit EXIT

cp "$SOURCE_FILE_ABS" "$RUN_DIR/kernel.cpp"
cp "$TESTBENCH_FILE_ABS" "$RUN_DIR/host.cpp"
cp "$SCRIPT_DIR/run.tcl" "$RUN_DIR/run.tcl"
cp "$RUN_DIR/kernel.cpp" "$RUN_DIR/kernel_csim.cpp"

if [[ "$CSIM_ENTRY" != "$KERNEL_ENTRY" ]]; then
  sed -i \
    -e "s/extern \"C\" void ${KERNEL_ENTRY}(/void ${CSIM_ENTRY}(/" \
    -e "0,/const int a/s//int a/" \
    -e "0,/const int b/s//int b/" \
    -e "s/${KERNEL_ENTRY}(a, b, c);/${CSIM_ENTRY}(a, b, c);/" \
    "$RUN_DIR/host.cpp"
fi

mkdir -p "$RUN_DIR/project" "$RUN_DIR/project_csim"
cp "$RUN_DIR/kernel.cpp" "$RUN_DIR/project/kernel.cpp"
cp "$RUN_DIR/kernel.cpp" "$RUN_DIR/project_csim/kernel.cpp"
cp "$RUN_DIR/kernel_csim.cpp" "$RUN_DIR/project_csim/kernel_csim.cpp"

cat > "$RUN_DIR/kernel_wrapper.cpp" <<EOF
#define ${KERNEL_ENTRY} ${KERNEL_ENTRY}_impl
#include "kernel.cpp"
#undef ${KERNEL_ENTRY}

void ${HLS_TOP}(int a[${HLS_ARRAY_DEPTH}], int b[${HLS_ARRAY_DEPTH}], int c[${HLS_ARRAY_DEPTH}])
{
    ${KERNEL_ENTRY}_impl(a, b, c);
}
EOF

cp "$RUN_DIR/kernel_wrapper.cpp" "$RUN_DIR/project/kernel_wrapper.cpp"
cp "$RUN_DIR/kernel_wrapper.cpp" "$RUN_DIR/project_csim/kernel_wrapper.cpp"

export TASK_ID
export CANDIDATE_PREFIX
export SOURCE_FILE_ORIGINAL="$SOURCE_FILE_ABS"
export TESTBENCH_FILE_ORIGINAL="$TESTBENCH_FILE_ABS"
export HLS_SOURCE_FILE="$RUN_DIR/kernel_wrapper.cpp"
export CSIM_HELPER_FILE_STAGED="$RUN_DIR/kernel_csim.cpp"
export TOP="$HLS_TOP"
export HLS_TOP
export SOURCE_FILE="$RUN_DIR/kernel_wrapper.cpp"
export TESTBENCH_FILE="$RUN_DIR/host.cpp"
export CSIM_HELPER_FILE="$RUN_DIR/kernel_csim.cpp"
export KERNEL_ENTRY
export CSIM_ENTRY
export HLS_PART
export HLS_CLOCK_PERIOD_NS
export HLS_ARRAY_DEPTH
export RUN_DIR
export RUN_COSIM

write_manifest

vivado_part_check="$RUN_DIR/logs/vivado_part_check.log"
vivado -mode batch -nojournal -nolog -notrace \
  -source "$SCRIPT_DIR/verify-part.tcl" \
  -tclargs "$HLS_PART" \
  >"$vivado_part_check" 2>&1

echo "wrapper: run_dir=$RUN_DIR"
echo "wrapper: hls_part=$HLS_PART"
echo "wrapper: csim starting"
CSIM_STATUS=running
write_manifest
if (
  cd "$RUN_DIR"
  RUN_PROJECT_DIR="$RUN_DIR/project_csim" RUN_CSIM=1 RUN_SYNTH=0 vitis-run --mode hls --tcl "$RUN_DIR/run.tcl"
) >"$RUN_DIR/logs/csim.stdout.log" 2>"$RUN_DIR/logs/csim.stderr.log"; then
  CSIM_EXIT_CODE=0
  CSIM_STATUS=pass
else
  CSIM_EXIT_CODE=$?
  CSIM_STATUS=fail
  write_manifest
  exit "$CSIM_EXIT_CODE"
fi
write_manifest
echo "wrapper: csim passed"

echo "wrapper: synth starting"
SYNTH_STATUS=running
write_manifest
if (
  cd "$RUN_DIR"
  RUN_PROJECT_DIR="$RUN_DIR/project" RUN_CSIM=0 RUN_SYNTH=1 vitis-run --mode hls --tcl "$RUN_DIR/run.tcl"
) >"$RUN_DIR/logs/synth.stdout.log" 2>"$RUN_DIR/logs/synth.stderr.log"; then
  SYNTH_EXIT_CODE=0
  SYNTH_STATUS=pass
else
  SYNTH_EXIT_CODE=$?
  SYNTH_STATUS=fail
  write_manifest
  exit "$SYNTH_EXIT_CODE"
fi
write_manifest
echo "wrapper: synth passed"

csynth_rpt=$(find "$RUN_DIR/project" -path "*/syn/report/*_csynth.rpt" -type f | sort | head -n 1)
if [[ -z "$csynth_rpt" ]]; then
  echo "error: csynth.rpt was not found under $RUN_DIR/project" >&2
  exit 3
fi
cp "$csynth_rpt" "$RUN_DIR/reports/$(basename "$csynth_rpt")"
CSYNTH_RPT="$RUN_DIR/reports/$(basename "$csynth_rpt")"
write_manifest
echo "wrapper: csynth_rpt=$csynth_rpt"

echo "wrapper: report parsing starting"
REPORT_STATUS=running
write_manifest
if python3 "$SCRIPT_DIR/parse_csynth_report.py" --run-dir "$RUN_DIR" --output "$RUN_DIR/report.json" \
  >"$RUN_DIR/logs/report.stdout.log" 2>"$RUN_DIR/logs/report.stderr.log"; then
  REPORT_EXIT_CODE=0
  REPORT_STATUS=pass
  REPORT_JSON="$RUN_DIR/report.json"
else
  REPORT_EXIT_CODE=$?
  REPORT_STATUS=fail
  write_manifest
  exit "$REPORT_EXIT_CODE"
fi
write_manifest
echo "wrapper: report parsing passed"
echo "wrapper: report_json=$REPORT_JSON"
