#!/usr/bin/env bash
# Compatibility name retained for old notes. New runs use the v4 two-container
# launcher; the deleted v2 release is never selected.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
echo "launch_track_a_v2_model.sh is deprecated; using run_track_a_v4_split.sh" >&2
exec "$SCRIPT_DIR/run_track_a_v4_split.sh" "$@"
