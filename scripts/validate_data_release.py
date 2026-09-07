"""Validate that factor-panel and backtest data share one complete trading calendar."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


def _dates(values: Any) -> pd.DatetimeIndex:
    result = pd.DatetimeIndex(values).normalize()
    if result.has_duplicates or not result.is_monotonic_increasing:
        raise ValueError("trading dates must be unique and increasing")
    return result


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_release(root: Path, *, expected_end: str | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    panel = root / "panel_shards"
    warehouse = root / "warehouse_rqdata"
    panel_meta = json.loads((panel / "metadata.json").read_text(encoding="utf-8"))
    panel_dates = _dates(panel_meta["dates"])
    if expected_end and panel_dates[-1].date().isoformat() != expected_end:
        raise ValueError(f"panel ends at {panel_dates[-1].date()}, expected {expected_end}")

    for field, details in panel_meta["fields"].items():
        partitions = details.get("partitions", [])
        if not partitions or partitions[-1]["end_date"] != str(panel_dates[-1].date()):
            raise ValueError(f"panel field {field} does not reach {panel_dates[-1].date()}")
        path = panel / partitions[-1]["path"]
        if f"sha256:{_hash_file(path)}" != partitions[-1]["sha256"]:
            raise ValueError(f"panel field hash mismatch: {field}")
        frame = pd.read_parquet(path)
        actual = _dates(frame.index)
        expected = panel_dates[panel_dates.year == actual[-1].year]
        if not actual.equals(expected):
            raise ValueError(f"panel field calendar mismatch: {field}")

    warehouse_meta = json.loads(
        (warehouse / "rqdata_warehouse_manifest.json").read_text(encoding="utf-8")
    )
    warehouse_calendar = pd.read_parquet(warehouse / "trading_calendar.parquet")
    warehouse_dates = _dates(warehouse_calendar["date"])
    if not warehouse_dates.equals(panel_dates):
        raise ValueError("factor panel and backtest warehouse calendars differ")
    if warehouse_meta["date_max"] != str(panel_dates[-1].date()):
        raise ValueError("warehouse manifest date_max differs from panel")
    if warehouse_meta["source"]["content_hash"] != panel_meta["content_hash"]:
        raise ValueError("warehouse was not built from this panel version")

    benchmark_manifest = json.loads(
        (warehouse / "benchmarks" / "manifest.json").read_text(encoding="utf-8")
    )
    benchmark_dates: dict[str, str] = {}
    for item in benchmark_manifest["benchmarks"]:
        path = warehouse / "benchmarks" / item["file"]
        if f"sha256:{_hash_file(path)}" != item["content_sha256"]:
            raise ValueError(f"benchmark hash mismatch: {item['benchmark_id']}")
        frame = pd.read_parquet(path)
        actual = _dates(frame["date"])
        if not actual.equals(panel_dates):
            missing = panel_dates.difference(actual)
            sample = ", ".join(value.date().isoformat() for value in missing[:10])
            raise ValueError(f"benchmark {item['benchmark_id']} calendar mismatch: {sample}")
        if frame["close"].isna().any() or (frame["close"] <= 0).any():
            raise ValueError(f"benchmark close is invalid: {item['benchmark_id']}")
        benchmark_dates[item["benchmark_id"]] = str(actual[-1].date())

    return {
        "status": "valid",
        "date_min": str(panel_dates[0].date()),
        "date_max": str(panel_dates[-1].date()),
        "trading_days": len(panel_dates),
        "panel_content_hash": panel_meta["content_hash"],
        "warehouse_content_hash": warehouse_meta["warehouse_content_hash"],
        "benchmarks": benchmark_dates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--expected-end")
    args = parser.parse_args()
    print(json.dumps(validate_release(args.release, expected_end=args.expected_end), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
