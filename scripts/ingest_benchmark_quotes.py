"""Normalize independent benchmark index quotes for report-time comparison."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from qbt.data.hashing import hash_file

SPECS = {
    "000300.SH": ("沪深300", "000300.SH行情.xlsx"),
    "000905.SH": ("中证500", "000905.SH行情.xlsx"),
    "000852.SH": ("中证1000", "000852.SH行情.xlsx"),
}


def _number(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values.astype(str).str.replace(",", "", regex=False), errors="coerce")


def ingest_benchmark_quotes(source_dir: Path, output_dir: Path) -> dict:
    source_dir = Path(source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for benchmark_id, (name, filename) in SPECS.items():
        source = source_dir / filename
        if not source.is_file():
            raise FileNotFoundError(f"Benchmark quote file missing: {source}")
        raw = pd.read_excel(source)
        if not {"交易日期", "收盘价"}.issubset(raw.columns):
            raise ValueError(f"Benchmark quote schema invalid: {source}")
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(raw["交易日期"], errors="coerce"),
                "close": _number(raw["收盘价"]),
            }
        ).dropna()
        frame = frame[frame["close"] > 0].sort_values("date").drop_duplicates("date")
        if len(frame) < 2:
            raise ValueError(f"Benchmark quote history is too short: {source}")
        target = output_dir / f"{benchmark_id}.parquet"
        frame.to_parquet(target, index=False)
        items.append(
            {
                "benchmark_id": benchmark_id,
                "name": name,
                "file": target.name,
                "source_uri": str(source),
                "source_sha256": f"sha256:{hash_file(source)}",
                "content_sha256": f"sha256:{hash_file(target)}",
                "date_min": str(frame["date"].iloc[0].date()),
                "date_max": str(frame["date"].iloc[-1].date()),
                "rows": len(frame),
                "price_field": "close",
            }
        )
    manifest = {
        "schema_version": "qbt_benchmark_quotes/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "benchmarks": items,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(ingest_benchmark_quotes(args.source_dir, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
