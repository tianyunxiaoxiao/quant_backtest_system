"""交易日历与可交易性推导 (规范 6.5, 确认清单 B5 / B6 / A3)。

涨跌停无官方标志数据, 按板块与制度日期推导:
    涨停价 = round(前收盘原始价 * (1 + limit), 2)
导师口径 (B5): 距涨跌停 0.5 个百分点以内即视为不可买 / 不可卖,
即触及 limit * (1 - buffer_ratio) 就拦单, 比"必须封板"更保守。

停牌 (B6): 零成交量行 + 上市区间内的缺行, 双保险。
ST 状态优先使用仓库逐日快照；缺少交易所涨跌停价时，主板 ST 按 5% 兜底。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["price_limit_ratio", "build_limit_matrices", "build_suspension"]


def _board(asset_id: str) -> str:
    code = asset_id.split(".")[0]
    if asset_id.endswith(".BJ") or code.startswith(("43", "83", "87", "88", "92")):
        return "bse"
    if code.startswith("688") or code.startswith("689"):
        return "star"
    if code.startswith("300") or code.startswith("301"):
        return "chinext"
    return "main"


def price_limit_ratio(asset_id: str, day: pd.Timestamp, *, listed_first: pd.Timestamp | None = None,
                      is_st: bool = False) -> float:
    """单只股票在某日的涨跌幅限制。返回 nan 表示不设限 (新股首日等)。"""
    board = _board(asset_id)
    if listed_first is not None and pd.notna(listed_first):
        # 新股上市初期不设限: 主板首日, 创业板/科创板前 5 日, 北交所首日
        n_trading_days = len(pd.bdate_range(listed_first.normalize(), day.normalize()))
        if board in ("star", "chinext") and n_trading_days <= 5:
            return float("nan")
        if board in ("main", "bse") and n_trading_days == 1:
            return float("nan")
    if board == "bse":
        return 0.30
    if board == "star":
        return 0.20
    if board == "chinext":
        return 0.20 if day >= pd.Timestamp("2020-08-24") else 0.10
    return 0.05 if is_st else 0.10


def _limit_ratio_matrix(
    assets: pd.Index,
    dates: pd.DatetimeIndex,
    listed_first: pd.Series,
    is_st: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """逐资产 x 日期的限幅矩阵。板块固定, 只有创业板与新股窗口随日期变化。"""
    boards = np.asarray([_board(str(asset)) for asset in assets], dtype=object)
    values = np.full((len(dates), len(assets)), 0.10, dtype="float32")
    chinext_switch = pd.Timestamp("2020-08-24")
    values[:, boards == "bse"] = 0.30
    values[:, boards == "star"] = 0.20
    chinext = boards == "chinext"
    values[np.ix_(dates >= chinext_switch, chinext)] = 0.20

    main = boards == "main"
    if is_st is not None and main.any():
        st_values = (
            is_st.reindex(index=dates, columns=assets)
            .fillna(False)
            .to_numpy(dtype=bool)
        )
        values[:, main] = np.where(st_values[:, main], 0.05, 0.10)

    first = pd.to_datetime(listed_first.reindex(assets)).to_numpy(dtype="datetime64[ns]")
    date_values = dates.to_numpy(dtype="datetime64[ns]")
    in_window = (~np.isnat(first)) & (first >= date_values[0]) & (first <= date_values[-1])
    first_pos = np.searchsorted(date_values, first, side="left")
    extended = in_window & np.isin(boards, ("star", "chinext"))
    extended_cols = np.flatnonzero(extended)
    for offset in range(5):
        rows = first_pos[extended_cols] + offset
        valid = rows < len(dates)
        values[rows[valid], extended_cols[valid]] = np.nan
    first_day_cols = np.flatnonzero(in_window & ~np.isin(boards, ("star", "chinext")))
    values[first_pos[first_day_cols], first_day_cols] = np.nan
    return pd.DataFrame(values, index=dates, columns=assets)


def build_limit_matrices(
    raw_prev_close: pd.DataFrame,
    raw_high: pd.DataFrame,
    raw_low: pd.DataFrame,
    raw_open: pd.DataFrame,
    listed_first: pd.Series,
    *,
    raw_fill_price: pd.DataFrame | None = None,
    raw_limit_up: pd.DataFrame | None = None,
    raw_limit_down: pd.DataFrame | None = None,
    is_st: pd.DataFrame | None = None,
    buffer_ratio: float = 0.005,
) -> dict[str, pd.DataFrame]:
    """推导涨跌停不可交易矩阵。

    buffer_ratio 是导师 B5 口径的绝对幅度缓冲: 10% 限幅下涨到 9.5% 即视为不可买。

    判定必须和成交价口径一致 (导师 B1 默认 T+1 VWAP), 所以传进来的
    raw_fill_price 就是实际成交参考价。满足其一即拦买单:
      - 成交参考价 >= 买入拦截价: 那一刻的价格本身在拦截区, 这个价拿不到;
      - 全天最低价 >= 买入拦截价: 一字板, 全天没有低于拦截价的成交 (兜底,
        成交价缺失时仍能判定)。
    卖出侧对称；开盘价敏感性配置下第一条即"开盘封板不可买"。
    """
    dates, assets = raw_prev_close.index, raw_prev_close.columns
    ratio = _limit_ratio_matrix(assets, dates, listed_first, is_st=is_st)
    prev = raw_prev_close.astype("float64")

    up_price = (prev * (1.0 + ratio)).round(2)
    down_price = (prev * (1.0 - ratio)).round(2)
    if raw_limit_up is not None and raw_limit_down is not None:
        actual_up = raw_limit_up.astype("float64")
        actual_down = raw_limit_down.astype("float64")
        actual_valid = (
            actual_up.notna()
            & actual_down.notna()
            & (actual_up > 0)
            & (actual_down > 0)
        )
        up_price = actual_up.where(actual_valid, up_price)
        down_price = actual_down.where(actual_valid, down_price)
        ratio = (up_price / prev.replace(0.0, float("nan")) - 1.0).where(
            actual_valid, ratio
        )
    buy_block_price = (up_price - prev * buffer_ratio).round(4)
    sell_block_price = (down_price + prev * buffer_ratio).round(4)

    lo = raw_low.astype("float64")
    hi = raw_high.astype("float64")
    fp = None if raw_fill_price is None else raw_fill_price.astype("float64")

    # 有限幅数据 (ratio 非 nan) 且价格有效才判定
    valid = ratio.notna() & prev.notna() & (prev > 0)
    buy_block = lo >= buy_block_price
    sell_block = hi <= sell_block_price
    if fp is not None:
        buy_block = buy_block | (fp >= buy_block_price)
        sell_block = sell_block | (fp <= sell_block_price)
    limit_up_block_buy = (valid & buy_block).fillna(False)
    limit_down_block_sell = (valid & sell_block).fillna(False)

    return {
        "limit_up_block_buy": limit_up_block_buy,
        "limit_down_block_sell": limit_down_block_sell,
        "limit_up_price": up_price,
        "limit_down_price": down_price,
        "limit_ratio": ratio,
    }


def build_suspension(
    volume: pd.DataFrame,
    close: pd.DataFrame,
    listed_first: pd.Series,
    listed_last: pd.Series,
    dates: pd.DatetimeIndex,
) -> dict[str, pd.DataFrame]:
    """停牌 / 上市 / 退市矩阵 (B6 双保险口径)。"""
    date_arr = dates.to_numpy()
    first = pd.to_datetime(listed_first.reindex(volume.columns)).to_numpy()
    last = pd.to_datetime(listed_last.reindex(volume.columns)).to_numpy()

    is_listed = pd.DataFrame(
        (date_arr[:, None] >= first[None, :]), index=dates, columns=volume.columns
    ).fillna(False)
    # de_listed_date 是最后上市日期；从下一交易日起进入退市状态。
    is_delisted = pd.DataFrame(
        (date_arr[:, None] > last[None, :]), index=dates, columns=volume.columns
    ).fillna(False)

    has_row = close.notna()
    zero_volume = volume.fillna(0.0) <= 0
    in_life = is_listed & (~is_delisted)
    is_suspended = (in_life & (zero_volume | (~has_row))).fillna(False)
    return {
        "is_listed": is_listed,
        "is_delisted": is_delisted,
        "is_suspended": is_suspended,
    }
