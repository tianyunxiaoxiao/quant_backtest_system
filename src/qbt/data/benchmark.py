"""指数基准收益构建 (规范 6.3, 确认清单 A2 - 待补官方序列, 当前用代理)。

指定指数没有官方点位时, 用 PIT 成分与月初权重合成基准; 未指定指数时,
使用每日再平衡的全A等权基准 (`ALL_A_EQ`)。
口径声明 (必须进披露清单):
- 用月初 PIT 权重按日漂移 (buy-and-hold within month), 月初快照日重置权重,
  与真实指数的日度再平衡口径存在跟踪误差。
- 复权价空间计算, 隐含分红再投资, 接近全收益口径; 与官方价格指数存在
  约 1.5-2%/年 的口径差 (A2)。
- 拿到官方 000905.SH / H00905.CSI 序列后, 只需替换本模块即可, 下游不变。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .ingest_index import ALL_A_INDEX_ID, ALL_A_INDEX_NAME

__all__ = ["build_benchmark_returns", "build_equal_weight_all_a_returns", "load_official_benchmark"]


def build_equal_weight_all_a_returns(
    *, adj_close: pd.DataFrame, member: pd.DataFrame
) -> tuple[pd.Series, dict]:
    """Build the default daily-rebalanced equal-weighted All-A benchmark."""
    dates = adj_close.index
    member = member.reindex(index=dates, columns=adj_close.columns).fillna(False).astype(bool)
    # A listed stock remains in an equal-weight basket during a suspension.
    # Forward-filled valuation yields zero while suspended and correctly captures
    # the move from the last valid close when trading resumes. cummax prevents
    # future price availability from admitting a security before its first quote.
    observed_by_date = adj_close.notna().cummax()
    valid = member & observed_by_date
    returns = adj_close.ffill().pct_change(fill_method=None)
    returns = returns.where(np.isfinite(returns)).fillna(0.0)
    weights = valid.astype("float64")
    weights = weights.div(weights.sum(axis=1).replace(0.0, np.nan), axis=0).fillna(0.0)
    series = (weights * returns).sum(axis=1).astype("float64").rename("benchmark_return")
    if len(series):
        series.iloc[0] = 0.0
    n_members = valid.sum(axis=1)
    stats = {
        "method": "all_a_equal_weight_daily",
        "source": "synthetic:all_a_equal_weight_daily",
        "index_id": ALL_A_INDEX_ID,
        "index_name": ALL_A_INDEX_NAME,
        "drift_within_period": False,
        "n_reset_dates": int(len(dates)),
        "mean_n_members": float(n_members.mean()) if len(n_members) else 0.0,
        "min_n_members": int(n_members.min()) if len(n_members) else 0,
        "mean_weight_coverage": 1.0 if len(series) else float("nan"),
        "min_weight_coverage": 1.0 if len(series) else float("nan"),
        "annualized_return": float((1.0 + series).prod() ** (252.0 / max(len(series), 1)) - 1.0),
        "annualized_volatility": float(series.std(ddof=1) * np.sqrt(252.0)),
    }
    return series, stats


def build_benchmark_returns(
    *,
    adj_close: pd.DataFrame,
    index_weights: pd.DataFrame,
    index_member: pd.DataFrame,
    snapshot_dates: pd.DatetimeIndex,
    drift_within_period: bool = True,
) -> tuple[pd.Series, dict]:
    """合成指数日收益。

    drift_within_period=True: 权重在快照期内按持有收益漂移 (更接近真实指数);
    False: 每日按最新快照权重重置 (日度再平衡, 作为敏感性对照)。
    """
    dates = adj_close.index
    # 停牌日按最后有效收盘估值；复牌收益从最后有效收盘起算。
    ret = adj_close.ffill().pct_change(fill_method=None)
    ret_filled = ret.where(np.isfinite(ret)).fillna(0.0)

    w0 = index_weights.where(index_member).astype("float64")
    # 月度快照常落在周末/节假日；其权重在快照日后的首个交易日生效。
    reset_pos = {
        int(dates.searchsorted(pd.Timestamp(d), side="left"))
        for d in snapshot_dates
        if int(dates.searchsorted(pd.Timestamp(d), side="left")) < len(dates)
    }
    resets = pd.DatetimeIndex([dates[i] for i in sorted(reset_pos)])

    n = len(dates)
    out = np.zeros(n, dtype="float64")
    active = np.zeros(adj_close.shape[1], dtype="float64")
    coverage = np.zeros(n, dtype="float64")
    w0_arr = w0.to_numpy()
    ret_arr = ret_filled.to_numpy()
    member_arr = index_member.to_numpy()
    price_ok = adj_close.notna().to_numpy()

    for i in range(n):
        snap = w0_arr[i]
        if i in reset_pos or not np.isfinite(active).any() or active.sum() <= 0:
            active = np.where(np.isfinite(snap), snap, 0.0)
        elif not drift_within_period:
            active = np.where(np.isfinite(snap), snap, 0.0)
        else:
            # 成分调整日之外, 只在权重快照变化时重置
            active = np.where(np.isfinite(snap) & (snap > 0), active, 0.0)
            if active.sum() <= 0:
                active = np.where(np.isfinite(snap), snap, 0.0)
        tot = active.sum()
        if tot <= 0:
            out[i] = 0.0
            continue
        w = active / tot
        r = ret_arr[i]
        out[i] = float(np.dot(w, r))
        coverage[i] = float(w[member_arr[i] & price_ok[i]].sum())
        if drift_within_period:
            active = active * (1.0 + r)

    series = pd.Series(out, index=dates, name="benchmark_return")
    series.iloc[0] = 0.0
    stats = {
        "method": "pit_monthly_weight_synthetic",
        "source": "synthetic:pit_monthly_weights",
        "drift_within_period": bool(drift_within_period),
        "n_reset_dates": int(len(resets)),
        "mean_weight_coverage": float(np.nanmean(coverage[1:])) if n > 1 else float("nan"),
        "min_weight_coverage": float(np.nanmin(coverage[1:])) if n > 1 else float("nan"),
        "annualized_return": float((1.0 + series).prod() ** (252.0 / max(len(series), 1)) - 1.0),
        "annualized_volatility": float(series.std(ddof=1) * np.sqrt(252.0)),
    }
    return series, stats


def load_official_benchmark(path, dates: pd.DatetimeIndex) -> tuple[pd.Series, dict]:
    """预留接口: 拿到官方点位序列后替换合成基准 (A2)。

    期望文件含 date 与 close 两列 (或中文 日期/收盘)。
    """
    import pathlib

    p = pathlib.Path(path)
    df = pd.read_csv(p) if p.suffix.lower() == ".csv" else pd.read_excel(p)
    cols = {c.strip(): c for c in df.columns}
    date_col = next((cols[c] for c in cols if c in ("date", "日期")), None)
    close_col = next((cols[c] for c in cols if c in ("close", "收盘", "收盘价", "收盘点位")), None)
    if date_col is None or close_col is None:
        raise ValueError(f"官方基准文件缺少日期或收盘列: {list(df.columns)}")
    s = pd.Series(
        pd.to_numeric(df[close_col], errors="coerce").to_numpy(),
        index=pd.to_datetime(df[date_col]),
    ).sort_index()
    s = s.reindex(dates).ffill()
    ret = s.pct_change(fill_method=None).fillna(0.0)
    ret.name = "benchmark_return"
    return ret, {"method": "official_index_level", "source": str(p), "n_points": int(s.notna().sum())}
