"""Parquet 仓库 -> 宽表面板 (规范 17-P0)。

只加载目标指数在样本区间内出现过的股票, 避免把 5,494 只票全量摊平。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

__all__ = ["PricePanel", "load_price_panel", "build_trading_calendar"]

_WIDE_FIELDS = (
    "adj_open", "adj_high", "adj_low", "adj_close", "adj_prev_close", "adj_vwap",
    "raw_open", "raw_close", "raw_vwap", "adj_factor", "volume", "amount",
    "turnover_rate", "float_mktcap", "total_mktcap", "pb", "pe", "ps",
)


@dataclass(frozen=True)
class PricePanel:
    wide: dict[str, pd.DataFrame]
    listed_first: pd.Series
    listed_last: pd.Series
    raw_high: pd.DataFrame
    raw_low: pd.DataFrame
    trading_days: pd.DatetimeIndex
    assets: pd.Index
    source_files: tuple[str, ...]
    n_source_rows: int


def build_trading_calendar(
    warehouse: Path, start: pd.Timestamp, end: pd.Timestamp, *, min_active: int = 200
) -> pd.DatetimeIndex:
    """从全市场行情推导交易日历: 当日有成交的股票数达到阈值即为交易日。"""
    days: list[pd.Series] = []
    for path in sorted((Path(warehouse) / "daily_prices").glob("*.parquet")):
        df = pd.read_parquet(path, columns=["date", "volume"])
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        if df.empty:
            continue
        days.append(df[df["volume"].fillna(0) > 0].groupby("date").size())
    if not days:
        raise ValueError("交易日历为空: 检查仓库路径与日期区间")
    counts = pd.concat(days).groupby(level=0).sum().sort_index()
    return pd.DatetimeIndex(counts[counts >= min_active].index, name="date")


def load_price_panel(
    warehouse: Path,
    assets: list[str] | pd.Index,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    trading_days: pd.DatetimeIndex | None = None,
    fields: tuple[str, ...] = _WIDE_FIELDS,
) -> PricePanel:
    """把指定股票池的日频长表转成宽表矩阵。"""
    assets = sorted(set(map(str, assets)))
    want = set(assets)
    cols = ["asset_id", "date", *dict.fromkeys(fields), "raw_close"]
    long_parts: list[pd.DataFrame] = []
    life_parts: list[pd.DataFrame] = []
    source_files: list[str] = []
    n_rows = 0

    for path in sorted((Path(warehouse) / "daily_prices").glob("*.parquet")):
        available = pd.read_parquet(path, columns=["asset_id"]).head(0)
        use_cols = list(dict.fromkeys(cols + ["listed_first_date", "listed_last_date"]))
        df = pd.read_parquet(path, columns=[c for c in use_cols if c or available is not None])
        df["asset_id"] = df["asset_id"].astype(str)
        df = df[df["asset_id"].isin(want)]
        if df.empty:
            continue
        source_files.append(path.name)
        n_rows += len(df)
        life_parts.append(
            df.groupby("asset_id", observed=True)[["listed_first_date", "listed_last_date"]].agg(
                {"listed_first_date": "min", "listed_last_date": "max"}
            )
        )
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        if not df.empty:
            long_parts.append(df.drop(columns=["listed_first_date", "listed_last_date"]))

    if not long_parts:
        raise ValueError("面板为空: 股票池与日期区间没有交集")

    long = pd.concat(long_parts, ignore_index=True)
    life = pd.concat(life_parts).groupby(level=0).agg(
        {"listed_first_date": "min", "listed_last_date": "max"}
    )

    if trading_days is None:
        trading_days = pd.DatetimeIndex(sorted(long["date"].unique()), name="date")
    else:
        trading_days = trading_days[(trading_days >= start) & (trading_days <= end)]

    asset_index = pd.Index(assets, name="asset_id")
    wide: dict[str, pd.DataFrame] = {}
    for field in fields:
        if field not in long.columns:
            continue
        mat = long.pivot_table(index="date", columns="asset_id", values=field, aggfunc="last")
        wide[field] = mat.reindex(index=trading_days, columns=asset_index).astype("float64")

    raw_ratio = wide["raw_close"] / wide["adj_close"].replace(0.0, np.nan)
    raw_high = wide["adj_high"] * raw_ratio
    raw_low = wide["adj_low"] * raw_ratio

    return PricePanel(
        wide=wide,
        listed_first=pd.to_datetime(life["listed_first_date"]).reindex(asset_index),
        listed_last=pd.to_datetime(life["listed_last_date"]).reindex(asset_index),
        raw_high=raw_high,
        raw_low=raw_low,
        trading_days=trading_days,
        assets=asset_index,
        source_files=tuple(source_files),
        n_source_rows=n_rows,
    )
