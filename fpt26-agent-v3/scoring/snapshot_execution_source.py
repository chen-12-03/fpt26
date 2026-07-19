"""Write one immutable execution-source snapshot for acceptance provenance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scoring.run_p0_real_api_shard import execution_source_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite output: {args.output}")
    snapshot = execution_source_snapshot()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"execution source snapshot: files={snapshot['file_count']} "
        f"tree={snapshot['tree_sha256']} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
