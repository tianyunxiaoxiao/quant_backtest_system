from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from qbt.data.ingest_rq_snapshot import (
    _SOURCE_FIELDS,
    RQSnapshotIngestConfig,
    build_rq_snapshot_warehouse,
)
from qbt.data.portal import PortalConfig, PortfolioDataPortal
from qbt.data.tradability import build_limit_matrices


def _write_snapshot(root) -> None:
    dates = pd.DatetimeIndex(["2019-01-02", "2019-01-03"])
    tickers = ["000001.SZ", "000002.SZ"]
    base = pd.DataFrame([[20.0, np.nan], [20.0, 40.0]], index=dates, columns=tickers)
    values = {field: base.copy() for field in _SOURCE_FIELDS}
    values.update(
        {
            "volume": pd.DataFrame([[100.0, np.nan], [100.0, 200.0]], index=dates, columns=tickers),
            "amount": pd.DataFrame(
                [[1000.0, np.nan], [1000.0, 4000.0]], index=dates, columns=tickers
            ),
            "total_shares": pd.DataFrame(
                [[10.0, np.nan], [10.0, 20.0]], index=dates, columns=tickers
            ),
            "market_cap": pd.DataFrame(
                [[100.0, np.nan], [100.0, 400.0]], index=dates, columns=tickers
            ),
            "float_shares": pd.DataFrame(
                [[8.0, np.nan], [8.0, 16.0]], index=dates, columns=tickers
            ),
            "float_market_cap": pd.DataFrame(
                [[80.0, np.nan], [80.0, 320.0]], index=dates, columns=tickers
            ),
            "limit_up": base * 1.1,
            "limit_down": base * 0.9,
            "is_st": pd.DataFrame([[0.0, np.nan], [1.0, 0.0]], index=dates, columns=tickers),
            "listed_days": pd.DataFrame(
                [[100.0, np.nan], [101.0, 1.0]], index=dates, columns=tickers
            ),
            "turnover": pd.DataFrame([[1.0, np.nan], [1.1, 2.0]], index=dates, columns=tickers),
        }
    )
    for field, frame in values.items():
        path = root / "fields" / field / "year=2019.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path)
    metadata = {
        "format_version": "qpf_panel_parquet/v2",
        "provider": {"vendor": "Ricequant RQData", "client": "rqdatac"},
        "price_adjustment": "post",
        "content_hash": "sha256:fixture",
        "dates": [value.isoformat() for value in dates],
        "tickers": tickers,
        "fields": {field: {} for field in _SOURCE_FIELDS},
        "instruments": {"path": "instruments.parquet", "rows": len(tickers)},
    }
    (root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    pd.DataFrame(
        {
            "asset_id": tickers,
            "listed_date": [pd.Timestamp("2000-01-01"), pd.Timestamp("2019-01-03")],
            "de_listed_date": [pd.NaT, pd.NaT],
        }
    ).to_parquet(root / "instruments.parquet", index=False)


def test_build_rq_snapshot_warehouse_reconstructs_prices(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    _write_snapshot(snapshot)
    output = tmp_path / "warehouse"

    manifest = build_rq_snapshot_warehouse(RQSnapshotIngestConfig(snapshot, output))
    frame = pd.read_parquet(output / "daily_prices" / "daily_prices_2019.parquet")
    first = frame[
        (frame["asset_id"] == "000001.SZ") & (frame["date"] == pd.Timestamp("2019-01-02"))
    ].iloc[0]
    newcomer = frame[frame["asset_id"] == "000002.SZ"].iloc[0]

    assert len(frame) == 3
    assert first["raw_close"] == 10.0
    assert first["adj_factor"] == 2.0
    assert first["raw_vwap"] == 10.0
    assert first["adj_vwap"] == 20.0
    assert first["raw_limit_up"] == 11.0
    assert first["raw_limit_down"] == 9.0
    assert newcomer["listed_first_date"] == pd.Timestamp("2019-01-03")
    assert manifest["source"]["provider"]["vendor"] == "Ricequant RQData"
    assert manifest["rows"] == 3
    assert manifest["supported_indexes"] == [
        {
            "index_id": "ALL_A_EQ",
            "name": "流动性过滤后的非 ST A 股",
            "source": "derived_from_rqdata_daily_panel",
        }
    ]
    pd.testing.assert_frame_equal(
        pd.read_parquet(output / "trading_calendar.parquet"),
        pd.DataFrame({"date": pd.DatetimeIndex(["2019-01-02", "2019-01-03"])}),
    )
    assert (output / "asset_master.parquet").is_file()
    assert manifest["delist_data_available"] is True
    assert manifest["limitations"] == []


def test_rq_snapshot_warehouse_preserves_official_delisting_date(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    _write_snapshot(snapshot)
    instruments = pd.read_parquet(snapshot / "instruments.parquet")
    instruments.loc[instruments["asset_id"] == "000001.SZ", "de_listed_date"] = pd.Timestamp(
        "2019-01-02"
    )
    instruments.to_parquet(snapshot / "instruments.parquet", index=False)
    output = tmp_path / "warehouse"

    manifest = build_rq_snapshot_warehouse(RQSnapshotIngestConfig(snapshot, output))
    master = pd.read_parquet(output / "asset_master.parquet").set_index("asset_id")

    assert master.loc["000001.SZ", "de_listed_date"] == pd.Timestamp("2019-01-02")
    assert master.loc["000001.SZ", "listed_last_date"] == pd.Timestamp("2019-01-02")
    assert manifest["delisted_assets"] == 1


def test_rq_snapshot_overwrite_removes_foreign_index_membership(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    _write_snapshot(snapshot)
    output = tmp_path / "warehouse"
    foreign = output / "index_membership"
    foreign.mkdir(parents=True)
    (foreign / "000300.SH_monthly.parquet").write_bytes(b"foreign")

    build_rq_snapshot_warehouse(RQSnapshotIngestConfig(snapshot, output, overwrite=True))

    assert not foreign.exists()


def test_rq_snapshot_warehouse_rejects_foreign_index(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    _write_snapshot(snapshot)
    output = tmp_path / "warehouse"
    build_rq_snapshot_warehouse(RQSnapshotIngestConfig(snapshot, output))
    portal = PortfolioDataPortal(
        PortalConfig(warehouse_dir=output, index_source_dir=tmp_path, calendar_min_active=1)
    )

    with pytest.raises(ValueError, match="禁止回退"):
        portal.resolve(SimpleNamespace(), "000300.SH", SimpleNamespace())


def test_research_eligibility_matches_factor_platform_policy():
    dates = pd.bdate_range("2024-01-02", periods=21)
    assets = pd.Index(["A", "B"])
    amount = pd.DataFrame(30_000_000.0, index=dates, columns=assets)
    is_st = pd.DataFrame(0.0, index=dates, columns=assets)
    is_st.loc[dates[-1], "B"] = 1.0
    panel = SimpleNamespace(
        trading_days=dates,
        assets=assets,
        wide={
            "listed_days": pd.DataFrame(100.0, index=dates, columns=assets),
            "is_st": is_st,
            "amount": amount,
            "adj_close": pd.DataFrame(10.0, index=dates, columns=assets),
        },
    )

    eligible, stats = PortfolioDataPortal._research_eligibility(panel)

    assert not eligible.iloc[18].any()
    assert eligible.loc[dates[-1], "A"]
    assert not eligible.loc[dates[-1], "B"]
    assert stats["method"] == "qpf_research_eligibility_v1"


def test_actual_rqdata_limit_prices_override_board_inference():
    dates = pd.DatetimeIndex(["2024-01-02"])
    columns = pd.Index(["000001.SZ"])

    def matrix(value):
        return pd.DataFrame(value, index=dates, columns=columns)

    limits = build_limit_matrices(
        raw_prev_close=matrix(10.0),
        raw_high=matrix(11.46),
        raw_low=matrix(10.0),
        raw_open=matrix(10.0),
        listed_first=pd.Series(pd.Timestamp("2000-01-01"), index=columns),
        raw_fill_price=matrix(11.46),
        raw_limit_up=matrix(11.5),
        raw_limit_down=matrix(8.5),
        buffer_ratio=0.005,
    )

    assert limits["limit_up_price"].iloc[0, 0] == 11.5
    assert limits["limit_up_block_buy"].iloc[0, 0]
