"""Validate that factor-panel and backtest data share one complete trading calendar."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd

BAR_HHMM = np.array(
    [
        *range(935, 960, 5),
        *range(1000, 1060, 5),
        *range(1100, 1131, 5),
        *range(1305, 1360, 5),
        *range(1400, 1460, 5),
        1500,
    ],
    dtype=np.int64,
)


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


def _validate_minbars(
    root: Path, panel: Path, panel_meta: dict[str, Any], expected_end: str
) -> dict[str, Any]:
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    if metadata["end_date"] != expected_end:
        raise ValueError(f"{root.name} ends at {metadata['end_date']}, expected {expected_end}")
    manifest = root / metadata["manifest"]
    if _hash_file(manifest) != metadata["manifest_sha256"].removeprefix("sha256:"):
        raise ValueError(f"{root.name} manifest hash mismatch")

    close_details = panel_meta["fields"]["close"]
    latest_part = panel / close_details["partitions"][-1]["path"]
    close = pd.read_parquet(latest_part).iloc[-1]
    active = [str(ticker) for ticker, value in close.items() if pd.notna(value) and value > 0]
    missing: list[str] = []
    malformed: list[str] = []
    expected_int = int(expected_end.replace("-", ""))
    for ticker in active:
        suffix = ".XSHE.h5" if ticker.endswith(".SZ") else ".XSHG.h5"
        path = root / "equities" / f"{ticker[:-3]}{suffix}"
        if not path.is_file():
            missing.append(ticker)
            continue
        with h5py.File(path, "r") as handle:
            index = handle["index"]
            data = handle["data"]
            if not len(index) or int(index[-1]["date"]) != expected_int:
                missing.append(ticker)
                continue
            start = int(index[-1]["line_no"])
            latest = data[start:]
            hhmm = (latest["datetime"] % 1_000_000) // 100
            if len(latest) != 48 or not np.array_equal(hhmm, BAR_HHMM):
                malformed.append(ticker)
                continue
            if metadata.get("stored_price_basis") == "post_adjusted" and not np.isclose(
                float(latest[-1]["close"]), float(close[ticker]), rtol=2e-6, atol=1e-6
            ):
                malformed.append(ticker)
    if missing:
        raise ValueError(f"{root.name} missing target-day bars: {', '.join(missing[:10])} ({len(missing)} total)")
    if malformed:
        raise ValueError(f"{root.name} malformed target-day bars: {', '.join(malformed[:10])} ({len(malformed)} total)")
    return {
        "date_max": expected_end,
        "active_tickers": len(active),
        "file_count": int(metadata["file_count"]),
        "content_hash": metadata["content_hash"],
    }


def validate_release(root: Path, *, expected_end: str | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    panel = root / "panel_shards"
    warehouse = root / "warehouse_rqdata"
    panel_meta = json.loads((panel / "metadata.json").read_text(encoding="utf-8"))
    panel_dates = _dates(panel_meta["dates"])
    if expected_end and panel_dates[-1].date().isoformat() != expected_end:
        raise ValueError(f"panel ends at {panel_dates[-1].date()}, expected {expected_end}")
    release_end = expected_end or str(panel_dates[-1].date())

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

    raw_minbars = _validate_minbars(root / "5minbar_unadjusted", panel, panel_meta, release_end)
    post_minbars = _validate_minbars(root / "5minbar_post", panel, panel_meta, release_end)
    post_meta = json.loads(
        (root / "5minbar_post" / "metadata.json").read_text(encoding="utf-8")
    )
    if post_meta["source_dataset"]["content_hash"] != raw_minbars["content_hash"]:
        raise ValueError("post-adjusted 5-minute data was not built from this raw release")
    if post_meta["daily_adjustment_source"]["content_hash"] != panel_meta["content_hash"]:
        raise ValueError("post-adjusted 5-minute data was not built from this daily panel")

    return {
        "status": "valid",
        "date_min": str(panel_dates[0].date()),
        "date_max": str(panel_dates[-1].date()),
        "trading_days": len(panel_dates),
        "panel_content_hash": panel_meta["content_hash"],
        "warehouse_content_hash": warehouse_meta["warehouse_content_hash"],
        "benchmarks": benchmark_dates,
        "5minbar_unadjusted": raw_minbars,
        "5minbar_post": post_minbars,
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
