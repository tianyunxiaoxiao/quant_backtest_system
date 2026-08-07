"""测试共享 fixture 与辅助函数。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def small_prices():
    """3 只股票、10 个交易日的微型价格面板。"""
    dates = pd.date_range("2020-01-02", periods=10, freq="B")
    assets = ["000001.SZ", "000002.SZ", "600000.SH"]
    base = np.array(
        [
            [10.0, 20.0, 30.0],
            [10.2, 19.8, 30.5],
            [10.1, 20.1, 30.2],
            [10.5, 20.0, 30.8],
            [10.4, 20.3, 30.6],
            [10.6, 20.2, 31.0],
            [10.7, 20.4, 31.2],
            [10.6, 20.5, 31.1],
            [10.8, 20.3, 31.5],
            [10.9, 20.6, 31.4],
        ]
    )
    close = pd.DataFrame(base, index=dates, columns=assets)
    open_p = close.shift(1).bfill() * 1.0
    high = close * 1.02
    low = close * 0.98
    vwap = close * 1.0
    prev_close = close.shift(1)
    raw_close = close * 1.0
    raw_open = open_p * 1.0
    raw_vwap = vwap * 1.0
    adj_factor = pd.DataFrame(1.0, index=dates, columns=assets)
    volume = pd.DataFrame(1_000_000, index=dates, columns=assets)
    amount = volume * close
    return {
        "adj_open": open_p,
        "adj_high": high,
        "adj_low": low,
        "adj_close": close,
        "adj_vwap": vwap,
        "adj_prev_close": prev_close,
        "raw_close": raw_close,
        "raw_open": raw_open,
        "raw_vwap": raw_vwap,
        "adj_factor": adj_factor,
        "volume": volume,
        "amount": amount,
    }


@pytest.fixture
def small_factor(small_prices):
    """方向 +1、随机得分的因子。"""
    np.random.seed(42)
    close = small_prices["adj_close"]
    values = pd.DataFrame(
        np.random.randn(*close.shape), index=close.index, columns=close.columns
    )
    from qbt.contracts import FactorFrame

    return FactorFrame(values=values, factor_id="test_random", direction=1)


@pytest.fixture
def small_universe(small_prices):
    """指数成分矩阵: 前两天 3 只, 之后去掉一只。"""
    dates = small_prices["adj_close"].index
    assets = small_prices["adj_close"].columns
    member = pd.DataFrame(True, index=dates, columns=assets)
    member.loc[member.index[2]:, "600000.SH"] = False
    return member


@pytest.fixture
def small_tradability(small_prices):
    """全部可交易 (无停牌、无涨跌停)。"""
    shape = small_prices["adj_close"].shape
    false_mat = pd.DataFrame(False, index=small_prices["adj_close"].index, columns=small_prices["adj_close"].columns)
    true_mat = pd.DataFrame(True, index=small_prices["adj_close"].index, columns=small_prices["adj_close"].columns)
    from qbt.contracts import TradabilityFrame

    return TradabilityFrame(
        is_listed=true_mat,
        is_delisted=false_mat,
        is_st=false_mat,
        is_suspended=false_mat,
        limit_up_block_buy=false_mat,
        limit_down_block_sell=false_mat,
        allow_buy=true_mat,
        allow_sell=true_mat,
    )


@pytest.fixture
def small_price_frame(small_prices):
    from qbt.contracts import MarketPriceFrame

    return MarketPriceFrame(
        adj_open=small_prices["adj_open"],
        adj_high=small_prices["adj_high"],
        adj_low=small_prices["adj_low"],
        adj_close=small_prices["adj_close"],
        adj_vwap=small_prices["adj_vwap"],
        adj_prev_close=small_prices["adj_prev_close"],
        raw_close=small_prices["raw_close"],
        raw_open=small_prices["raw_open"],
        raw_vwap=small_prices["raw_vwap"],
        adj_factor=small_prices["adj_factor"],
        volume=small_prices["volume"],
        amount=small_prices["amount"],
        fill_price_field="adj_open",
    )


@pytest.fixture
def small_liquidity(small_prices):
    from qbt.contracts import PortfolioLiquidityData

    amount = small_prices["amount"]
    adv = amount.rolling(3, min_periods=1).mean().shift(1)
    return PortfolioLiquidityData(adv=adv, adv_window=3)
