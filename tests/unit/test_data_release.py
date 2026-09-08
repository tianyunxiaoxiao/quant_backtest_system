from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from qbt.data.hashing import hash_file
from scripts.fetch_rqdata_benchmarks import BENCHMARKS, fetch_benchmarks
from scripts.validate_data_release import validate_release


class FakeRQData:
    dates = pd.date_range("2026-09-01", periods=3, freq="B")

    def get_trading_dates(self, *args, **kwargs):
        return self.dates

    def get_price(self, order_book_id, **kwargs):
        return pd.DataFrame({"close": [100.0, 101.0, 102.0]}, index=self.dates)


def test_fetch_benchmarks_uses_one_complete_calendar(tmp_path: Path) -> None:
    manifest = fetch_benchmarks(
        tmp_path / "benchmarks",
        start_date=FakeRQData.dates[0].date(),
        end_date=FakeRQData.dates[-1].date(),
        client=FakeRQData(),
    )
    assert {item["benchmark_id"] for item in manifest["benchmarks"]} == set(BENCHMARKS)
    assert all(item["date_max"] == "2026-09-03" for item in manifest["benchmarks"])
    assert (tmp_path / "benchmarks").stat().st_mode & 0o777 == 0o755
    assert all(path.stat().st_mode & 0o777 == 0o644 for path in (tmp_path / "benchmarks").iterdir())


def _release(root: Path) -> None:
    dates = pd.date_range("2026-09-01", periods=3, freq="B")
    panel = root / "panel_shards"
    field = panel / "fields" / "close"
    field.mkdir(parents=True)
    part = field / "year=2026.parquet"
    pd.DataFrame({"000001.SZ": [1.0, 2.0, 3.0]}, index=dates).to_parquet(part)
    panel_hash = "sha256:panel"
    (panel / "metadata.json").write_text(
        json.dumps(
            {
                "dates": [value.isoformat() for value in dates],
                "content_hash": panel_hash,
                "fields": {
                    "close": {
                        "partitions": [
                            {
                                "path": "fields/close/year=2026.parquet",
                                "end_date": "2026-09-03",
                                "sha256": f"sha256:{hash_file(part)}",
                            }
                        ]
                    }
                },
            }
        )
    )
    warehouse = root / "warehouse_rqdata"
    warehouse.mkdir()
    pd.DataFrame({"date": dates}).to_parquet(warehouse / "trading_calendar.parquet", index=False)
    (warehouse / "rqdata_warehouse_manifest.json").write_text(
        json.dumps(
            {
                "date_max": "2026-09-03",
                "source": {"content_hash": panel_hash},
                "warehouse_content_hash": "sha256:warehouse",
            }
        )
    )
    benchmarks = warehouse / "benchmarks"
    benchmarks.mkdir()
    items = []
    for benchmark_id in BENCHMARKS:
        path = benchmarks / f"{benchmark_id}.parquet"
        pd.DataFrame({"date": dates, "close": [100.0, 101.0, 102.0]}).to_parquet(path)
        items.append(
            {
                "benchmark_id": benchmark_id,
                "file": path.name,
                "content_sha256": f"sha256:{hash_file(path)}",
            }
        )
    (benchmarks / "manifest.json").write_text(json.dumps({"benchmarks": items}))
    data_dtype = np.dtype(
        [
            ("datetime", "<i8"), ("open", "<f8"), ("high", "<f8"),
            ("low", "<f8"), ("close", "<f8"), ("volume", "<f8"),
            ("total_turnover", "<f8"), ("num_trades", "<u8"),
        ]
    )
    index_dtype = np.dtype([("date", "<i4"), ("line_no", "<u4")])
    for name, basis in (("5minbar_unadjusted", "raw_unadjusted"), ("5minbar_post", "post_adjusted")):
        minute_root = root / name
        equities = minute_root / "equities"
        equities.mkdir(parents=True)
        minute_path = equities / "000001.XSHE.h5"
        values = np.zeros(48, dtype=data_dtype)
        hhmm = np.array(
            [
                *range(935, 960, 5), *range(1000, 1060, 5), *range(1100, 1131, 5),
                *range(1305, 1360, 5), *range(1400, 1460, 5), 1500,
            ]
        )
        values["datetime"] = 20260903000000 + hhmm * 100
        values["close"] = 3.0
        index = np.array([(20260903, 0)], dtype=index_dtype)
        with h5py.File(minute_path, "w") as handle:
            handle.create_dataset("data", data=values)
            handle.create_dataset("index", data=index)
        manifest = minute_root / "manifest.csv"
        manifest.write_text("filename\n000001.XSHE.h5\n")
        manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
        (minute_root / "metadata.json").write_text(
            json.dumps(
                {
                    "end_date": "2026-09-03",
                    "manifest": "manifest.csv",
                    "manifest_sha256": manifest_hash,
                    "content_hash": f"sha256:{manifest_hash}",
                    "file_count": 1,
                    "stored_price_basis": basis,
                    "source_dataset": {"content_hash": "placeholder"},
                    "daily_adjustment_source": {"content_hash": panel_hash},
                }
            )
        )
    raw_meta = json.loads((root / "5minbar_unadjusted/metadata.json").read_text())
    post_path = root / "5minbar_post/metadata.json"
    post_meta = json.loads(post_path.read_text())
    post_meta["source_dataset"]["content_hash"] = raw_meta["content_hash"]
    post_path.write_text(json.dumps(post_meta))


def test_validate_release_rejects_missing_benchmark_date(tmp_path: Path) -> None:
    _release(tmp_path)
    assert validate_release(tmp_path, expected_end="2026-09-03")["status"] == "valid"
    path = tmp_path / "warehouse_rqdata/benchmarks/000852.SH.parquet"
    pd.read_parquet(path).iloc[:-1].to_parquet(path, index=False)
    manifest_path = path.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for item in manifest["benchmarks"]:
        if item["benchmark_id"] == "000852.SH":
            item["content_sha256"] = f"sha256:{hash_file(path)}"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="000852.SH calendar mismatch"):
        validate_release(tmp_path)
