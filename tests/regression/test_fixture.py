"""回归测试: 小样本手算账本。"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from qbt.contracts import (
    CostConfig,
    CostRate,
    ExecutionConfig,
    FactorFrame,
    LongOnlyFactorBacktestConfig,
    LongOnlyFactorBacktestRequest,
    MarketPriceFrame,
    PortfolioLiquidityData,
    TradabilityFrame,
    WeightingConfig,
)
from qbt.engine.backtester import LongOnlyFactorBacktester
from qbt.engine.execution import ExecutionEngine


def _fixture():
    """2 只股票、5 个交易日; 第一天入选等权, 第二天开盘成交。"""
    dates = pd.date_range("2020-01-02", periods=5, freq="B")
    assets = pd.Index(["A", "B"])
    close = pd.DataFrame(
        {"A": [100.0, 102.0, 101.0, 103.0, 104.0],
         "B": [100.0,  99.0, 100.0, 101.0, 102.0]},
        index=dates,
    )
    open_p = close.shift(1).bfill() * 1.0
    open_p.iloc[1] = [102.0, 99.0]  # T+1 开盘价
    high = close * 1.02
    low = close * 0.98
    vwap = close * 1.0
    prev = close.shift(1)
    prev.iloc[0] = [100.0, 100.0]
    raw_close = close * 1.0
    raw_open = open_p * 1.0
    raw_vwap = vwap * 1.0
    adj_factor = pd.DataFrame(1.0, index=dates, columns=assets)
    volume = pd.DataFrame(1_000_000, index=dates, columns=assets)
    amount = volume * close

    prices = MarketPriceFrame(
        adj_open=open_p, adj_high=high, adj_low=low, adj_close=close,
        adj_vwap=vwap, adj_prev_close=prev, raw_close=raw_close,
        raw_open=raw_open, raw_vwap=raw_vwap, adj_factor=adj_factor,
        volume=volume, amount=amount, fill_price_field="adj_open",
    )
    false_mat = pd.DataFrame(False, index=dates, columns=assets)
    true_mat = pd.DataFrame(True, index=dates, columns=assets)
    tradability = TradabilityFrame(
        is_listed=true_mat, is_delisted=false_mat, is_st=false_mat,
        is_suspended=false_mat, limit_up_block_buy=false_mat,
        limit_down_block_sell=false_mat, allow_buy=true_mat, allow_sell=true_mat,
    )
    liquidity = PortfolioLiquidityData(
        adv=amount.rolling(3, min_periods=1).mean().shift(1), adv_window=3
    )
    universe = pd.DataFrame(True, index=dates, columns=assets)
    return prices, tradability, liquidity, universe


def test_fixture_accounting_identity():
    prices, tradability, liquidity, universe = _fixture()
    cfg = LongOnlyFactorBacktestConfig(
        rebalance_frequency="daily",
        initial_capital=1_000_000.0,
        execution=ExecutionConfig(fill_price_field="adj_open"),
        weighting=WeightingConfig(cash_buffer=0.0),
        costs=CostConfig(commission_rate=0.0, slippage_bps=0.0),
    )
    engine = ExecutionEngine(
        config=cfg, prices=prices, tradability=tradability,
        liquidity=liquidity, index_universe=universe,
    )
    tw = pd.DataFrame({"A": [0.5, 0.5, 0.5, 0.5, 0.5], "B": [0.5, 0.5, 0.5, 0.5, 0.5]}, index=prices.dates)
    out = engine.run(target_weights=tw, rebalance_dates=tuple(prices.dates), initial_capital=1_000_000.0)
    residual = out.accounting_identity["residual_bps_of_nav"].abs().max()
    assert residual < 1e-6


def test_fixture_first_day_pnl():
    """手算: T=2020-01-02 开盘买入 A/B 各 50%; 收盘 A=102, B=99。
    现金缓冲为 0、费用为 0, 买入金额各 500k, 持股数 = floor(500k / 开盘价 / 100) * 100。
    """
    prices, tradability, liquidity, universe = _fixture()
    cfg = LongOnlyFactorBacktestConfig(
        rebalance_frequency="daily",
        initial_capital=1_000_000.0,
        execution=ExecutionConfig(fill_price_field="adj_open"),
        weighting=WeightingConfig(cash_buffer=0.0),
        costs=CostConfig(commission_rate=0.0, slippage_bps=0.0),
    )
    engine = ExecutionEngine(
        config=cfg, prices=prices, tradability=tradability,
        liquidity=liquidity, index_universe=universe,
    )
    tw = pd.DataFrame({"A": [0.5, 0.0, 0.0, 0.0, 0.0], "B": [0.5, 0.0, 0.0, 0.0, 0.0]}, index=prices.dates)
    out = engine.run(target_weights=tw, rebalance_dates=(prices.dates[0],), initial_capital=1_000_000.0)
    # 成交发生在 T+1 (dates[1]); 股数按 T 日收盘价 sizing, 再受 T+1 现金约束
    nav1 = out.cash_ledger["net_assets"].iloc[1]
    expected_shares_a = (500_000 // 100 // 100) * 100  # 信号日收盘价 100
    cash_after_a = 1_000_000 - expected_shares_a * 102.0
    expected_shares_b = (int(cash_after_a) // 99 // 100) * 100
    expected_nav1 = expected_shares_a * 102.0 + expected_shares_b * 99.0 + (
        1_000_000 - expected_shares_a * 102.0 - expected_shares_b * 99.0
    )
    # 上面预期 NAV 恒等于 1M, 毫无意义; 改为直接断言实际持仓与手算股数一致
    actual_shares = out.holdings_shares.iloc[1]
    assert actual_shares["A"] == expected_shares_a
    assert actual_shares["B"] == expected_shares_b
    # 净资产 = 持仓市值 + 现金
    assert abs(nav1 - (actual_shares * pd.Series([102.0, 99.0], index=["A", "B"])).sum() - out.cash_ledger["cash"].iloc[1]) < 1e-6


@pytest.mark.regression
def test_fixture_matches_hardcoded_golden_ledger_and_holdings():
    prices, tradability, liquidity, universe = _fixture()
    zero_schedule = (CostRate(pd.Timestamp("1900-01-01").date(), 0.0),)
    cfg = LongOnlyFactorBacktestConfig(
        rebalance_frequency="daily",
        initial_capital=1_000_000.0,
        execution=ExecutionConfig(fill_price_field="adj_open"),
        weighting=WeightingConfig(cash_buffer=0.0),
        costs=CostConfig(
            commission_rate=0.0,
            transfer_fee_schedule=zero_schedule,
            stamp_duty_schedule=zero_schedule,
            slippage_bps=0.0,
        ),
    )
    out = ExecutionEngine(
        config=cfg,
        prices=prices,
        tradability=tradability,
        liquidity=liquidity,
        index_universe=universe,
    ).run(
        target_weights=pd.DataFrame(0.5, index=prices.dates, columns=prices.assets),
        rebalance_dates=tuple(prices.dates),
        initial_capital=1_000_000.0,
    )

    np.testing.assert_allclose(
        out.cash_ledger["cash"].to_numpy(),
        [1_000_000.0, 4_900.0, 4_900.0, 4_900.0, 4_900.0],
        rtol=0.0,
        atol=1e-9,
    )
    np.testing.assert_allclose(
        out.cash_ledger["net_assets"].to_numpy(),
        [1_000_000.0, 1_000_000.0, 999_900.0, 1_014_800.0, 1_024_700.0],
        rtol=0.0,
        atol=1e-9,
    )
    assert out.cash_ledger["turnover"].iloc[1] == pytest.approx(0.49755)
    assert (out.cash_ledger["turnover"].iloc[[0, 2, 3, 4]] == 0.0).all()
    np.testing.assert_allclose(out.holdings_shares.iloc[1:]["A"], 5_000.0)
    np.testing.assert_allclose(out.holdings_shares.iloc[1:]["B"], 4_900.0)


@pytest.mark.regression
def test_backtest_result_hash_stability():
    """相同输入跑两次, 结果哈希应一致 (排除随机性)。"""
    prices, tradability, liquidity, universe = _fixture()
    values = pd.DataFrame({"A": [1.0, 1.0, 1.0, 1.0, 1.0], "B": [2.0, 2.0, 2.0, 2.0, 2.0]}, index=prices.dates)
    factor = FactorFrame(values=values, factor_id="fixture_equal", direction=1)

    cfg = LongOnlyFactorBacktestConfig(
        start_date=prices.dates[0].date(),
        end_date=prices.dates[-1].date(),
        rebalance_frequency="daily",
        initial_capital=1_000_000.0,
        execution=ExecutionConfig(fill_price_field="adj_open"),
        weighting=WeightingConfig(cash_buffer=0.0),
        costs=CostConfig(commission_rate=0.0, slippage_bps=0.0),
    )

    class _FakePortal:
        def resolve(self, factor, index_id, config):
            from qbt.contracts import PortfolioInitialState, ResolvedLongOnlyBacktestData
            from qbt.data.benchmark import build_benchmark_returns
            from qbt.data.style import build_style_exposures

            weights = pd.DataFrame(0.5, index=prices.dates, columns=prices.assets)
            bench, _ = build_benchmark_returns(
                adj_close=prices.adj_close, index_weights=weights,
                index_member=universe, snapshot_dates=pd.DatetimeIndex([prices.dates[0]]),
            )
            styles, _ = build_style_exposures(
                adj_close=prices.adj_close, float_mktcap=prices.adj_close * 1e9,
                pb=pd.DataFrame(2.0, index=prices.dates, columns=prices.assets),
                turnover_rate=pd.DataFrame(0.02, index=prices.dates, columns=prices.assets),
                valid_mask=universe,
            )
            return ResolvedLongOnlyBacktestData(
                index_universe=universe,
                index_weights=pd.DataFrame(0.5, index=prices.dates, columns=prices.assets),
                benchmark_returns=bench,
                prices=prices,
                tradability=tradability,
                style_exposures={k.lower(): v for k, v in styles.items()},
                liquidity_data=liquidity,
                sample_masks={"full_sample": pd.Series(True, index=prices.dates)},
                rebalance_dates=tuple(prices.dates),
                initial_state=PortfolioInitialState(initial_capital=cfg.initial_capital),
            )

    backtester = LongOnlyFactorBacktester(_FakePortal())
    request = LongOnlyFactorBacktestRequest(factor=factor, index_id="FAKE", config=cfg)
    r1 = backtester.run(request)
    r2 = backtester.run(request)
    assert r1.run_manifest.result_hash == r2.run_manifest.result_hash
    assert r1.run_manifest.artifact_uri.endswith(r1.run_manifest.run_id)
    assert r1.run_manifest.code_version not in {"", "unversioned"}
    assert r1.run_manifest.factor_content_hash
    assert isinstance(r1.holdings.columns, pd.MultiIndex)
    assert set(r1.holdings.columns.get_level_values("field")) == {
        "quantity_raw", "quantity_adjusted", "cost_basis",
        "market_value", "unrealized_pnl", "weight",
    }
    assert {
        "available_cash", "frozen_cash", "total_assets", "net_assets",
        "explicit_cost", "cumulative_realized_pnl", "unrealized_pnl", "turnover",
    }.issubset(r1.cash_ledger.columns)
    assert not r1.diagnostics.exclusion_reasons.empty
    max_weight_report = next(
        report for report in r1.constraint_reports
        if report.constraint == "max_single_weight"
    )
    first_rebalance = r1.cash_ledger["is_rebalance"].to_numpy().argmax()
    expected_breaches = int(
        (
            r1.actual_weights.iloc[first_rebalance:]
            > cfg.constraints.max_single_weight + 1e-9
        ).to_numpy().sum()
    )
    assert max_weight_report.n_violations == expected_breaches
    assert len(max_weight_report.violations) == expected_breaches

    bad_factor = replace(factor, content_hash="0" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        backtester.run(replace(request, factor=bad_factor))
