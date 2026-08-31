"""Build a qbt warehouse from the factor platform's immutable RQData snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qbt.data.ingest_rq_snapshot import RQSnapshotIngestConfig, build_rq_snapshot_warehouse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    manifest = build_rq_snapshot_warehouse(
        RQSnapshotIngestConfig(args.snapshot, args.output, overwrite=args.overwrite)
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
