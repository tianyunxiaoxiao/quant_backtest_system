"""交易日历与可交易性推导 (规范 6.5, 确认清单 B5 / B6 / A3)。

涨跌停无官方标志数据, 按板块与制度日期推导:
    涨停价 = round(前收盘原始价 * (1 + limit), 2)
导师口径 (B5): 距涨跌停 0.5 个百分点以内即视为不可买 / 不可卖,
即触及 limit * (1 - buffer_ratio) 就拦单, 比"必须封板"更保守。

停牌 (B6): 零成交量行 + 上市区间内的缺行, 双保险。
ST 与退市状态无历史数据 (A3), 字段全为 False 并在披露清单中标记。
"""

from __future__ import annotations

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
        n_days = (day - listed_first).days
        if board in ("star", "chinext") and n_days <= 7:
            return float("nan")
        if board in ("main", "bse") and n_days == 0:
            return float("nan")
    if board == "bse":
        return 0.30
    if board == "star":
        return 0.20
    if board == "chinext":
        return 0.20 if day >= pd.Timestamp("2020-08-24") else 0.10
    return 0.05 if is_st else 0.10


def _limit_ratio_matrix(
    assets: pd.Index, dates: pd.DatetimeIndex, listed_first: pd.Series
) -> pd.DataFrame:
    """逐资产 x 日期的限幅矩阵。板块固定, 只有创业板与新股窗口随日期变化。"""
    out = pd.DataFrame(0.10, index=dates, columns=assets, dtype="float32")
    chinext_switch = pd.Timestamp("2020-08-24")
    for asset in assets:
        board = _board(asset)
        if board == "bse":
            col = pd.Series(0.30, index=dates, dtype="float64")
        elif board == "star":
            col = pd.Series(0.20, index=dates, dtype="float64")
        elif board == "chinext":
            col = pd.Series(0.10, index=dates, dtype="float64")
            col[dates >= chinext_switch] = 0.20
        else:
            col = pd.Series(0.10, index=dates, dtype="float64")
        first = listed_first.get(asset, pd.NaT)
        if pd.notna(first):
            if board in ("star", "chinext"):
                col[dates <= first + pd.Timedelta(days=7)] = float("nan")
            else:
                col[dates == first] = float("nan")
        out[asset] = col.astype("float32")
    return out


def build_limit_matrices(
    raw_prev_close: pd.DataFrame,
    raw_high: pd.DataFrame,
    raw_low: pd.DataFrame,
    raw_open: pd.DataFrame,
    listed_first: pd.Series,
    *,
    raw_fill_price: pd.DataFrame | None = None,
    buffer_ratio: float = 0.005,
) -> dict[str, pd.DataFrame]:
    """推导涨跌停不可交易矩阵。

    buffer_ratio 是导师 B5 口径的绝对幅度缓冲: 10% 限幅下涨到 9.5% 即视为不可买。

    判定必须和成交价口径一致 (导师 B1 定的是 T+1 开盘价成交), 所以传进来的
    raw_fill_price 就是实际成交参考价。满足其一即拦买单:
      - 成交参考价 >= 买入拦截价: 那一刻的价格本身在拦截区, 这个价拿不到;
      - 全天最低价 >= 买入拦截价: 一字板, 全天没有低于拦截价的成交 (兜底,
        成交价缺失时仍能判定)。
    卖出侧对称。开盘价成交下第一条即"开盘封板不可买", 与直觉一致。
    """
    dates, assets = raw_prev_close.index, raw_prev_close.columns
    ratio = _limit_ratio_matrix(assets, dates, listed_first)
    prev = raw_prev_close.astype("float64")

    up_price = (prev * (1.0 + ratio)).round(2)
    down_price = (prev * (1.0 - ratio)).round(2)
    buy_block_price = (prev * (1.0 + ratio - buffer_ratio)).round(4)
    sell_block_price = (prev * (1.0 - ratio + buffer_ratio)).round(4)

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
    # 数据集内所有股票都活到样本末端 (审计发现 2), 退市矩阵在样本末端之前恒为 False;
    # 这里仍按"最后一条行情之后视为退市"实现, 供未来补数据后自动生效。
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
