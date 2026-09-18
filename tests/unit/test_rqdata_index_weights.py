from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd

from qbt.data.ingest_index import IndexSpec, ingest_index_membership
from scripts.fetch_rqdata_index_weights import _fetch_one, publish


class FakeClient:
    def index_weights(self, *_args, **_kwargs) -> pd.DataFrame:
        index = pd.MultiIndex.from_tuples(
            [
                ("2026-08-03", "000001.XSHE"),
                ("2026-08-03", "600000.XSHG"),
                ("2026-08-04", "000001.XSHE"),
                ("2026-08-04", "600000.XSHG"),
                ("2026-08-31", "000001.XSHE"),
                ("2026-08-31", "600000.XSHG"),
            ],
            names=["date", "order_book_id"],
        )
        return pd.DataFrame({"weight": [0.4, 0.6, 0.4, 0.6, 0.45, 0.55]}, index=index)


def test_fetch_one_keeps_only_effective_weight_changes() -> None:
    frame, stats = _fetch_one(
        FakeClient(),
        "000300.XSHG",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 9, 1),
        expected_size=2,
    )

    assert frame["snapshot_date"].drop_duplicates().dt.strftime("%Y-%m-%d").tolist() == [
        "2026-08-03",
        "2026-08-31",
    ]
    assert sorted(frame["asset_id"].unique()) == ["000001.SZ", "600000.SH"]
    assert stats["snapshots"] == 2


def test_ingest_prefers_standard_parquet(tmp_path: Path) -> None:
    frame, _ = _fetch_one(
        FakeClient(),
        "000300.XSHG",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 9, 1),
        expected_size=2,
    )
    frame.to_parquet(tmp_path / "TEST_monthly.parquet", index=False)
    spec = IndexSpec("TEST", "测试指数", ("missing_*.xlsx",), 2)

    loaded, stats = ingest_index_membership(tmp_path, spec)

    assert len(loaded) == 4
    assert stats["snapshot_last"] == "2026-08-31"
    assert stats["source_files"] == ["TEST_monthly.parquet"]


def test_publish_switches_symlink_without_removing_releases(tmp_path: Path) -> None:
    first = tmp_path / "releases" / "first"
    second = tmp_path / "releases" / "second"
    first.mkdir(parents=True)
    second.mkdir()
    os.symlink(first, tmp_path / "current")

    publish(tmp_path, second)

    assert (tmp_path / "current").resolve() == second
    assert first.exists()
    assert second.exists()
