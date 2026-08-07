"""执行与成本单元测试。"""

import numpy as np
import pandas as pd
import pytest

from qbt.contracts import (
    CostConfig,
    CostRate,
    ConstraintConfig,
    ExecutionConfig,
    LongOnlyFactorBacktestConfig,
    MarketPriceFrame,
    PortfolioLiquidityData,
    TradabilityFrame,
    WeightingConfig,
)
from qbt.engine.costs import CostModel
from qbt.engine.execution import ExecutionEngine


def _single_asset_execution(
    *, adjusted_price: float, raw_price: float, slippage_bps: float,
    adv: float = 100_000_000.0, max_adv_participation: float = 1.0,
    initial_capital: float = 10_000.0,
):
    dates = pd.date_range("2020-01-02", periods=3, freq="B")
    columns = pd.Index(["A"])

    def matrix(value):
        return pd.DataFrame(value, index=dates, columns=columns, dtype="float64")

    adjusted = matrix(adjusted_price)
    raw = matrix(raw_price)
    prices = MarketPriceFrame(
        adj_open=adjusted,
        adj_high=adjusted,
        adj_low=adjusted,
        adj_close=adjusted,
        adj_vwap=adjusted,
        adj_prev_close=adjusted,
        raw_close=raw,
        raw_open=raw,
        raw_vwap=raw,
        adj_factor=matrix(adjusted_price / raw_price),
        volume=matrix(10_000_000),
        amount=matrix(100_000_000),
        fill_price_field="adj_open",
    )
    tradable = matrix(True).astype(bool)
    blocked = matrix(False).astype(bool)
    tradability = TradabilityFrame(
        is_listed=tradable,
        is_delisted=blocked,
        is_st=blocked,
        is_suspended=blocked,
        limit_up_block_buy=blocked,
        limit_down_block_sell=blocked,
        allow_buy=tradable,
        allow_sell=tradable,
    )
    liquidity = PortfolioLiquidityData(adv=matrix(adv))
    zero_schedule = (CostRate(pd.Timestamp("1900-01-01").date(), 0.0),)
    config = LongOnlyFactorBacktestConfig(
        rebalance_frequency="daily",
        weighting=WeightingConfig(cash_buffer=0.0),
        execution=ExecutionConfig(
            fill_price_field="adj_open", max_adv_participation=max_adv_participation
        ),
        constraints=ConstraintConfig(
            max_adv_participation=max_adv_participation,
            min_holdings=1,
            max_single_weight=1.0,
        ),
        costs=CostConfig(
            commission_rate=0.0,
            min_commission=0.0,
            transfer_fee_schedule=zero_schedule,
            stamp_duty_schedule=zero_schedule,
            slippage_bps=slippage_bps,
        ),
    )
    engine = ExecutionEngine(
        config=config,
        prices=prices,
        tradability=tradability,
        liquidity=liquidity,
        index_universe=tradable,
    )
    target = matrix([1.0, 0.0, 0.0])
    return engine.run(
        target_weights=target,
        rebalance_dates=(dates[0],),
        initial_capital=initial_capital,
    )


def test_cost_model_buy_no_stamp_duty():
    cfg = LongOnlyFactorBacktestConfig().costs
    model = CostModel(cfg)
    fc = model.compute(
        side="buy", filled_quantity=1000, fill_price=10.0,
        reference_price=10.0, fill_date=pd.Timestamp("2020-01-02"),
    )
    assert fc.stamp_duty == 0.0
    assert fc.commission > 0.0
    assert fc.transfer_fee > 0.0
    assert fc.total > 0.0


def test_cost_model_sell_has_stamp_duty():
    cfg = LongOnlyFactorBacktestConfig().costs
    model = CostModel(cfg)
    fc = model.compute(
        side="sell", filled_quantity=1000, fill_price=10.0,
        reference_price=10.0, fill_date=pd.Timestamp("2023-09-01"),
    )
    assert fc.stamp_duty > 0.0  # 2023-08-28 后 0.05%
    assert fc.commission > 0.0


def test_cost_model_stamp_duty_rate_change():
    cfg = LongOnlyFactorBacktestConfig().costs
    model = CostModel(cfg)
    fc1 = model.compute(
        side="sell", filled_quantity=10000, fill_price=10.0,
        reference_price=10.0, fill_date=pd.Timestamp("2023-08-25"),
    )
    fc2 = model.compute(
        side="sell", filled_quantity=10000, fill_price=10.0,
        reference_price=10.0, fill_date=pd.Timestamp("2023-08-29"),
    )
    assert fc1.stamp_duty == 100.0  # 0.1%
    assert fc2.stamp_duty == 50.0   # 0.05%


def test_execution_no_rebalance_no_trade(small_price_frame, small_tradability, small_liquidity, small_universe):
    from qbt.contracts import ExecutionConfig
    cfg = LongOnlyFactorBacktestConfig(
        rebalance_frequency="daily",
        execution=ExecutionConfig(fill_price_field="adj_open"),
    )
    engine = ExecutionEngine(
        config=cfg,
        prices=small_price_frame,
        tradability=small_tradability,
        liquidity=small_liquidity,
        index_universe=small_universe,
    )
    # 目标权重全 0
    tw = pd.DataFrame(0.0, index=small_price_frame.dates, columns=small_price_frame.assets)
    out = engine.run(target_weights=tw, rebalance_dates=(), initial_capital=1_000_000.0)
    assert len(out.orders) == 0
    assert len(out.fills) == 0
    assert out.cash_ledger["net_assets"].iloc[0] == 1_000_000.0


def test_cash_ledger_contract_and_turnover_ignore_passive_price_drift(
    small_price_frame, small_tradability, small_liquidity, small_universe
):
    cfg = LongOnlyFactorBacktestConfig(
        execution=ExecutionConfig(fill_price_field="adj_open", max_adv_participation=1.0),
        weighting=WeightingConfig(cash_buffer=0.0),
        costs=CostConfig(commission_rate=0.0, slippage_bps=0.0),
    )
    engine = ExecutionEngine(
        config=cfg,
        prices=small_price_frame,
        tradability=small_tradability,
        liquidity=small_liquidity,
        index_universe=pd.DataFrame(
            True, index=small_price_frame.dates, columns=small_price_frame.assets
        ),
    )
    target = pd.DataFrame(0.0, index=small_price_frame.dates, columns=small_price_frame.assets)
    target.iloc[0, 0] = 1.0
    out = engine.run(
        target_weights=target,
        rebalance_dates=(small_price_frame.dates[0],),
        initial_capital=1_000_000.0,
    )

    required = {
        "available_cash", "frozen_cash", "total_assets", "net_assets",
        "explicit_cost", "cumulative_realized_pnl", "unrealized_pnl", "turnover",
    }
    assert required.issubset(out.cash_ledger.columns)
    assert out.cash_ledger["turnover"].iloc[1] > 0
    assert (out.cash_ledger["turnover"].iloc[2:] == 0.0).all()


def test_execution_enforces_max_turnover_on_actual_fills(
    small_price_frame, small_tradability, small_liquidity, small_universe
):
    max_turnover = 0.05
    cfg = LongOnlyFactorBacktestConfig(
        execution=ExecutionConfig(fill_price_field="adj_open"),
        weighting=WeightingConfig(cash_buffer=0.0),
        constraints=ConstraintConfig(
            max_turnover=max_turnover,
            max_adv_participation=1.0,
            min_holdings=1,
            max_single_weight=1.0,
        ),
        costs=CostConfig(commission_rate=0.0, slippage_bps=12.0),
    )
    engine = ExecutionEngine(
        config=cfg,
        prices=small_price_frame,
        tradability=small_tradability,
        liquidity=small_liquidity,
        index_universe=pd.DataFrame(
            True, index=small_price_frame.dates, columns=small_price_frame.assets
        ),
    )
    target = pd.DataFrame(0.0, index=small_price_frame.dates, columns=small_price_frame.assets)
    target.iloc[0, 0] = 1.0
    out = engine.run(
        target_weights=target,
        rebalance_dates=(small_price_frame.dates[0],),
        initial_capital=1_000_000.0,
    )

    assert out.cash_ledger["turnover"].max() <= max_turnover + 1e-12
    assert "turnover_cap" in set(out.unfilled_summary["reason"])


def test_execution_accounting_identity(small_price_frame, small_tradability, small_liquidity, small_universe):
    from qbt.contracts import ExecutionConfig
    cfg = LongOnlyFactorBacktestConfig(
        rebalance_frequency="daily",
        execution=ExecutionConfig(fill_price_field="adj_open"),
    )
    engine = ExecutionEngine(
        config=cfg,
        prices=small_price_frame,
        tradability=small_tradability,
        liquidity=small_liquidity,
        index_universe=small_universe,
    )
    tw = pd.DataFrame(0.0, index=small_price_frame.dates, columns=small_price_frame.assets)
    # 第一天买入第一只票
    tw.iloc[0, 0] = 1.0
    out = engine.run(
        target_weights=tw,
        rebalance_dates=tuple(small_price_frame.dates),
        initial_capital=1_000_000.0,
    )
    identity = out.accounting_identity
    max_residual_bps = identity["residual_bps_of_nav"].abs().max()
    assert max_residual_bps < 1e-6


def test_execution_lot_rounding(small_price_frame, small_tradability, small_liquidity, small_universe):
    from qbt.contracts import ExecutionConfig
    cfg = LongOnlyFactorBacktestConfig(
        rebalance_frequency="daily",
        execution=ExecutionConfig(fill_price_field="adj_open"),
    )
    engine = ExecutionEngine(
        config=cfg,
        prices=small_price_frame,
        tradability=small_tradability,
        liquidity=small_liquidity,
        index_universe=small_universe,
    )
    tw = pd.DataFrame(0.0, index=small_price_frame.dates, columns=small_price_frame.assets)
    tw.iloc[0, 0] = 1.0
    out = engine.run(
        target_weights=tw,
        rebalance_dates=tuple(small_price_frame.dates),
        initial_capital=1_000_000.0,
    )
    buy_fills = [f for f in out.fills if f.side == "buy" and f.filled_quantity > 0]
    assert len(buy_fills) > 0
    # 主板买入数量应为 100 的整数倍
    assert all(f.filled_quantity % 100 == 0 for f in buy_fills)


def test_execution_converts_raw_shares_to_adjusted_shares_without_nav_jump():
    out = _single_asset_execution(adjusted_price=5.0, raw_price=10.0, slippage_bps=0.0)
    fill = out.fills[0]
    assert fill.filled_quantity == 900.0
    assert out.holdings_shares.iloc[1, 0] == 1_800.0
    assert out.cash_ledger["net_assets"].iloc[1] == pytest.approx(10_000.0)
    assert out.accounting_identity["residual"].abs().max() < 1e-9


def test_embedded_slippage_is_not_deducted_twice_from_cash():
    out = _single_asset_execution(adjusted_price=10.0, raw_price=10.0, slippage_bps=100.0)
    fill = out.fills[0]
    assert fill.filled_quantity == 900.0
    assert fill.slippage_cost == pytest.approx(90.0)
    assert out.cash_ledger["net_assets"].iloc[1] == pytest.approx(9_910.0)
    assert out.cash_ledger["trade_cost"].iloc[1] == pytest.approx(90.0)
    assert out.accounting_identity["residual"].abs().max() < 1e-9


def test_missing_adv_rejects_instead_of_disabling_liquidity_cap(
    small_price_frame, small_tradability, small_universe
):
    missing = pd.DataFrame(
        np.nan, index=small_price_frame.dates, columns=small_price_frame.assets
    )
    cfg = LongOnlyFactorBacktestConfig(
        execution=ExecutionConfig(fill_price_field="adj_open"),
        weighting=WeightingConfig(cash_buffer=0.0),
    )
    engine = ExecutionEngine(
        config=cfg,
        prices=small_price_frame,
        tradability=small_tradability,
        liquidity=PortfolioLiquidityData(adv=missing),
        index_universe=small_universe,
    )
    target = pd.DataFrame(
        0.0, index=small_price_frame.dates, columns=small_price_frame.assets
    )
    target.iloc[0, 0] = 1.0
    out = engine.run(
        target_weights=target,
        rebalance_dates=(small_price_frame.dates[0],),
        initial_capital=1_000_000.0,
    )
    assert not any(fill.filled_quantity > 0 for fill in out.fills)
    assert {fill.reject_reason for fill in out.fills} == {"adv_missing"}
    assert set(out.unfilled_summary["reason"]) == {"adv_missing"}


def test_adv_cap_uses_slipped_execution_notional():
    max_participation = 0.10
    out = _single_asset_execution(
        adjusted_price=10.0,
        raw_price=10.0,
        slippage_bps=100.0,
        adv=100_000.0,
        max_adv_participation=max_participation,
        initial_capital=1_000_000.0,
    )
    filled = [fill for fill in out.fills if fill.filled_quantity > 0]
    assert filled
    assert max(fill.adv_participation for fill in filled) <= max_participation + 1e-12


def test_forced_index_exit_is_executed_and_tagged(
    small_price_frame, small_tradability, small_liquidity
):
    universe = pd.DataFrame(
        True, index=small_price_frame.dates, columns=small_price_frame.assets
    )
    universe.loc[small_price_frame.dates[2]:, small_price_frame.assets[0]] = False
    cfg = LongOnlyFactorBacktestConfig(
        execution=ExecutionConfig(fill_price_field="adj_open", max_adv_participation=1.0),
        constraints=ConstraintConfig(
            force_sell_index_exits=True,
            max_adv_participation=1.0,
            min_holdings=1,
            max_single_weight=1.0,
        ),
        weighting=WeightingConfig(cash_buffer=0.0),
        costs=CostConfig(commission_rate=0.0, slippage_bps=0.0),
    )
    engine = ExecutionEngine(
        config=cfg,
        prices=small_price_frame,
        tradability=small_tradability,
        liquidity=small_liquidity,
        index_universe=universe,
    )
    target = pd.DataFrame(
        0.0, index=small_price_frame.dates, columns=small_price_frame.assets
    )
    target.iloc[0, 0] = 1.0
    out = engine.run(
        target_weights=target,
        rebalance_dates=(small_price_frame.dates[0], small_price_frame.dates[1]),
        initial_capital=1_000_000.0,
    )
    forced_orders = [order for order in out.orders if order.reason == "index_exit_forced"]
    assert len(forced_orders) == 1
    forced_fill = next(fill for fill in out.fills if fill.order_id == forced_orders[0].order_id)
    assert forced_fill.status in {"filled", "partial"}
    assert forced_fill.filled_quantity > 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"allow_odd_lot_sell": False},
        {"sell_before_buy": False},
        {"sell_proceeds_available_same_day": False},
        {"split_large_orders": True},
        {"max_split_days": 2},
    ],
)
def test_unsupported_execution_controls_fail_explicitly(kwargs):
    with pytest.raises(ValueError, match="v1"):
        ExecutionConfig(**kwargs)
