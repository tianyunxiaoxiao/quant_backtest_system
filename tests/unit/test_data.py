"""数据层单元测试。"""

import os

import numpy as np
import pandas as pd
import pytest
from types import SimpleNamespace

from qbt.data.ingest_index import IndexSpec, expand_monthly_to_daily
from qbt.data.benchmark import build_benchmark_returns, build_equal_weight_all_a_returns
from qbt.data.panel import load_price_panel
from qbt.data.portal import PortfolioDataPortal, PortalConfig
from qbt.data.tradability import build_limit_matrices, build_suspension, price_limit_ratio


def test_price_limit_ratio_main():
    assert price_limit_ratio("000001.SZ", pd.Timestamp("2020-01-02")) == 0.10
    assert price_limit_ratio("688001.SH", pd.Timestamp("2020-01-02")) == 0.20
    assert price_limit_ratio("300001.SZ", pd.Timestamp("2020-08-24")) == 0.20
    assert price_limit_ratio("300001.SZ", pd.Timestamp("2020-08-20")) == 0.10


def test_build_limit_matrices_blocks_limit_up():
    dates = pd.date_range("2020-01-02", periods=3, freq="B")
    assets = pd.Index(["000001.SZ"])
    prev = pd.DataFrame({"000001.SZ": [10.0, 10.0, 10.0]}, index=dates)
    high = pd.DataFrame({"000001.SZ": [10.2, 11.0, 10.2]}, index=dates)
    low = pd.DataFrame({"000001.SZ": [9.8, 10.0, 9.8]}, index=dates)
    open_p = pd.DataFrame({"000001.SZ": [10.05, 10.95, 10.05]}, index=dates)
    listed_first = pd.Series([pd.Timestamp("2019-01-01")], index=assets)
    limits = build_limit_matrices(
        raw_prev_close=prev, raw_high=high, raw_low=low, raw_open=open_p,
        raw_fill_price=open_p,
        listed_first=listed_first, buffer_ratio=0.005,
    )
    # 第二天开盘 10.95 接近涨停价 11.0 (10 * 1.10), 触发不可买
    assert limits["limit_up_block_buy"].iloc[1, 0]
    assert not limits["limit_up_block_buy"].iloc[0, 0]


def test_build_limit_matrices_uses_five_percent_fallback_for_main_board_st():
    dates = pd.date_range("2020-01-02", periods=2, freq="B")
    assets = pd.Index(["000001.SZ"])
    prev = pd.DataFrame(10.0, index=dates, columns=assets)
    high = pd.DataFrame(10.5, index=dates, columns=assets)
    low = pd.DataFrame(10.0, index=dates, columns=assets)
    is_st = pd.DataFrame([False, True], index=dates, columns=assets)
    limits = build_limit_matrices(
        raw_prev_close=prev,
        raw_high=high,
        raw_low=low,
        raw_open=high,
        raw_fill_price=high,
        listed_first=pd.Series(pd.Timestamp("2019-01-01"), index=assets),
        is_st=is_st,
        buffer_ratio=0.005,
    )
    assert limits["limit_ratio"].iloc[0, 0] == pytest.approx(0.10)
    assert limits["limit_ratio"].iloc[1, 0] == pytest.approx(0.05)
    assert limits["limit_up_block_buy"].iloc[1, 0]


def test_limit_ratio_matrix_preserves_board_st_and_listing_rules():
    dates = pd.bdate_range("2020-08-24", periods=6)
    assets = pd.Index(["000001.SZ", "300001.SZ", "688001.SH", "830001.BJ"])
    shape = (len(dates), len(assets))
    prev = pd.DataFrame(10.0, index=dates, columns=assets)
    neutral = pd.DataFrame(np.full(shape, 10.0), index=dates, columns=assets)
    is_st = pd.DataFrame(False, index=dates, columns=assets)
    is_st.loc[dates[1], "000001.SZ"] = True
    listed_first = pd.Series(
        {
            "000001.SZ": pd.Timestamp("2010-01-01"),
            "300001.SZ": pd.Timestamp("2010-01-01"),
            "688001.SH": dates[0],
            "830001.BJ": pd.Timestamp("2010-01-01"),
        }
    )
    ratio = build_limit_matrices(
        raw_prev_close=prev,
        raw_high=neutral,
        raw_low=neutral,
        raw_open=neutral,
        raw_fill_price=neutral,
        listed_first=listed_first,
        is_st=is_st,
    )["limit_ratio"]
    assert ratio.loc[dates[1], "000001.SZ"] == pytest.approx(0.05)
    assert np.allclose(ratio["300001.SZ"], 0.20)
    assert ratio.loc[dates[:5], "688001.SH"].isna().all()
    assert ratio.loc[dates[5], "688001.SH"] == pytest.approx(0.20)
    assert np.allclose(ratio["830001.BJ"], 0.30)


def test_load_price_panel_keeps_last_duplicate_and_missing_cells(tmp_path):
    price_dir = tmp_path / "daily_prices"
    price_dir.mkdir()
    dates = pd.DatetimeIndex(["2023-01-03", "2023-01-04"], name="date")
    rows = pd.DataFrame(
        {
            "date": [dates[0], dates[0], dates[0], dates[1]],
            "asset_id": ["A", "A", "B", "A"],
            "adj_close": [10.0, 10.5, 20.0, 11.0],
            "raw_close": [10.0, 10.5, 20.0, 11.0],
            "adj_high": [10.1, 10.6, 20.1, 11.1],
            "adj_low": [9.9, 10.4, 19.9, 10.9],
            "listed_first_date": pd.Timestamp("2020-01-01"),
            "listed_last_date": pd.Timestamp("2099-01-01"),
        }
    )
    rows.to_parquet(price_dir / "daily_prices_2023.parquet", index=False)
    panel = load_price_panel(
        tmp_path,
        ["A", "B"],
        dates[0],
        dates[-1],
        trading_days=dates,
        fields=("adj_close", "raw_close", "adj_high", "adj_low"),
    )
    assert panel.wide["adj_close"].loc[dates[0], "A"] == pytest.approx(10.5)
    assert panel.wide["adj_close"].loc[dates[0], "B"] == pytest.approx(20.0)
    assert np.isnan(panel.wide["adj_close"].loc[dates[1], "B"])


def test_build_suspension_zero_volume():
    dates = pd.date_range("2020-01-02", periods=3, freq="B")
    assets = pd.Index(["000001.SZ"])
    volume = pd.DataFrame({"000001.SZ": [1000, 0, 1000]}, index=dates)
    close = pd.DataFrame({"000001.SZ": [10.0, 10.0, 10.1]}, index=dates)
    listed_first = pd.Series([pd.Timestamp("2019-01-01")], index=assets)
    listed_last = pd.Series([pd.Timestamp("2099-01-01")], index=assets)
    susp = build_suspension(volume, close, listed_first, listed_last, dates)
    assert not susp["is_suspended"].iloc[0, 0]
    assert susp["is_suspended"].iloc[1, 0]
    assert not susp["is_suspended"].iloc[2, 0]


def test_expand_monthly_to_daily():
    monthly = pd.DataFrame(
        {
            "snapshot_date": pd.to_datetime(["2020-01-01", "2020-01-01", "2020-02-01"]),
            "asset_id": ["A", "B", "A"],
            "weight": [0.6, 0.4, 0.5],
        }
    )
    trading_days = pd.date_range("2020-01-02", periods=40, freq="B")
    member, weight = expand_monthly_to_daily(monthly, trading_days)
    assert member.loc["2020-01-02", "A"]
    assert member.loc["2020-01-02", "B"]
    # 2 月 1 日是非交易日, 生效日为下一个交易日 2 月 3 日
    assert not member.loc["2020-02-03", "B"]
    assert member.loc["2020-02-03", "A"]
    # 权重按行归一化
    assert abs(weight.loc["2020-01-02"].sum() - 1.0) < 1e-9


@pytest.mark.parametrize("weight", [-0.1, np.nan, np.inf])
def test_expand_monthly_rejects_invalid_weights(weight):
    monthly = pd.DataFrame(
        {"snapshot_date": pd.to_datetime(["2020-01-01"]), "asset_id": ["A"], "weight": [weight]}
    )
    with pytest.raises(ValueError, match="权重"):
        expand_monthly_to_daily(monthly, pd.DatetimeIndex(["2020-01-02"]))


@pytest.mark.parametrize("index_id", ["../escape", "a/b", "/absolute", "a\\b"])
def test_index_spec_rejects_unsafe_identifier(index_id):
    with pytest.raises(ValueError, match="index_id"):
        IndexSpec(index_id, "unsafe", ("*.xlsx",), 1)


def test_benchmark_resets_weekend_snapshot_on_next_trading_day():
    dates = pd.DatetimeIndex(["2020-01-31", "2020-02-03"])
    prices = pd.DataFrame(
        [[100.0, 100.0, 100.0], [101.0, 100.0, 110.0]],
        index=dates,
        columns=["A", "B", "C"],
    )
    weights = pd.DataFrame(
        [[0.5, 0.5, 0.0], [0.5, 0.0, 0.5]],
        index=dates,
        columns=prices.columns,
    )
    returns, stats = build_benchmark_returns(
        adj_close=prices,
        index_weights=weights,
        index_member=weights.gt(0),
        snapshot_dates=pd.DatetimeIndex(["2020-01-01", "2020-02-01"]),
    )
    # Feb-03 close-to-close return still belongs to the Jan-31 close basket.
    assert returns.iloc[1] == pytest.approx(0.005)
    assert stats["n_reset_dates"] == 2


def test_equal_weight_benchmark_uses_prior_close_eligibility():
    dates = pd.DatetimeIndex(["2020-01-02", "2020-01-03"])
    prices = pd.DataFrame(
        {"A": [100.0, 120.0], "B": [100.0, 100.0]}, index=dates
    )
    member = pd.DataFrame(
        {"A": [True, True], "B": [False, True]}, index=dates
    )

    returns, _ = build_equal_weight_all_a_returns(
        adj_close=prices, member=member
    )

    assert returns.iloc[1] == pytest.approx(0.20)


def test_drop_incomplete_excludes_terminal_signal_dates(tmp_path):
    from qbt.contracts import LongOnlyFactorBacktestConfig

    dates = pd.date_range("2020-01-02", periods=5, freq="B")
    portal = PortfolioDataPortal(PortalConfig(warehouse_dir=tmp_path, index_source_dir=tmp_path))
    config = LongOnlyFactorBacktestConfig(rebalance_frequency="daily")
    rebalance_dates = portal._rebalance_dates(dates, config, pd.DataFrame())
    # order lag 1 + return lag 1 means the final two dates cannot be signal dates.
    assert rebalance_dates == list(dates[:-2])


def test_calendar_cache_is_bound_to_source_and_cache_hash(tmp_path):
    price_dir = tmp_path / "daily_prices"
    price_dir.mkdir()
    source = pd.DataFrame(
        {"date": pd.to_datetime(["2020-01-02", "2020-01-03"]), "volume": [100.0, 100.0]}
    )
    source.to_parquet(price_dir / "daily_prices_2020.parquet", index=False)
    cfg = PortalConfig(warehouse_dir=tmp_path, index_source_dir=tmp_path, calendar_min_active=1)
    first = PortfolioDataPortal(cfg).trading_calendar()
    assert (tmp_path / "trading_calendar.meta.json").exists()

    pd.DataFrame({"date": pd.to_datetime(["1999-01-01"])}).to_parquet(
        tmp_path / "trading_calendar.parquet", index=False
    )
    rebuilt = PortfolioDataPortal(cfg).trading_calendar()
    pd.testing.assert_index_equal(first, rebuilt)


def test_calendar_source_signature_is_content_bound_even_if_metadata_is_restored(tmp_path):
    price_dir = tmp_path / "daily_prices"
    price_dir.mkdir()
    path = price_dir / "daily_prices_2020.parquet"
    pd.DataFrame(
        {"date": pd.to_datetime(["2020-01-02"]), "volume": [100.0]}
    ).to_parquet(path, index=False)
    cfg = PortalConfig(warehouse_dir=tmp_path, index_source_dir=tmp_path, calendar_min_active=1)
    portal = PortfolioDataPortal(cfg)
    first = portal._calendar_source_signature()
    stat = path.stat()
    pd.DataFrame(
        {"date": pd.to_datetime(["2020-01-03"]), "volume": [100.0]}
    ).to_parquet(path, index=False)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert portal._calendar_source_signature() != first


def test_execution_fill_price_override_controls_portal_tradability(tmp_path):
    dates = pd.DatetimeIndex(["2020-01-02"])
    assets = pd.Index(["000001.SZ"])

    def matrix(value):
        return pd.DataFrame(value, index=dates, columns=assets, dtype="float64")

    wide = {
        "adj_open": matrix(np.nan), "adj_high": matrix(10.2), "adj_low": matrix(9.8),
        "adj_close": matrix(10.0), "adj_prev_close": matrix(10.0), "adj_vwap": matrix(10.0),
        "raw_open": matrix(np.nan), "raw_close": matrix(10.0), "raw_vwap": matrix(10.0),
        "adj_factor": matrix(1.0), "volume": matrix(1000.0), "amount": matrix(10_000.0),
    }
    panel = SimpleNamespace(
        wide=wide,
        raw_high=matrix(10.2),
        raw_low=matrix(9.8),
        listed_first=pd.Series(pd.Timestamp("2019-01-01"), index=assets),
        listed_last=pd.Series(pd.Timestamp("2099-01-01"), index=assets),
        trading_days=dates,
        assets=assets,
    )
    portal = PortfolioDataPortal(
        PortalConfig(warehouse_dir=tmp_path, index_source_dir=tmp_path, fill_price_field="adj_vwap")
    )
    prices, raw_prev = portal._build_price_frame(panel, "adj_open")
    tradability = portal._build_tradability(panel, raw_prev, "adj_open")
    assert prices.fill_price_field == "adj_open"
    assert not tradability.allow_buy.iloc[0, 0]
