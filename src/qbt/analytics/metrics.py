"""绩效指标 (规范第 13 节)。

IS / OOS / 全样本用同一套函数算, 避免两处口径漂移。导师 A5: rf 默认 0,
年化基数默认 252。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from qbt.contracts.reports import PerformanceStats

from .returns import drawdown_series, drawdown_table

__all__ = ["compute_performance_stats", "yearly_table", "monthly_table"]

_NA_DATE = ""


def _ann_return(nav_first: float, nav_last: float, n_days: int, ppy: int) -> float:
    """按交易日数几何年化。n_days 用区间内的观测日数, 不用日历天。"""
    if n_days <= 1 or nav_first <= 0 or nav_last <= 0:
        return float("nan")
    years = (n_days - 1) / float(ppy)
    if years <= 0:
        return float("nan")
    return float((nav_last / nav_first) ** (1.0 / years) - 1.0)


def _sortino(excess: pd.Series, ppy: int) -> float:
    downside = excess[excess < 0]
    if downside.empty:
        return float("inf") if excess.mean() > 0 else float("nan")
    dd = float(np.sqrt((downside.astype("float64") ** 2).mean()))
    if dd <= 0:
        return float("nan")
    return float(excess.mean() / dd * np.sqrt(ppy))


def _period_win_rate(portfolio: pd.Series, benchmark: pd.Series, freq: str) -> float:
    if portfolio.empty:
        return float("nan")
    key = portfolio.index.to_period(freq)
    port = (1.0 + portfolio.astype("float64")).groupby(key).prod()
    bench = (1.0 + benchmark.astype("float64")).groupby(key).prod()
    relative = port / bench.where(bench > 0) - 1.0
    if relative.empty:
        return float("nan")
    return float((relative > 0).mean())


def compute_performance_stats(
    frame: pd.DataFrame,
    *,
    label: str,
    trading_days_per_year: int = 252,
    risk_free_daily: float = 0.0,
    turnover_oneway: pd.Series | None = None,
    top10_concentration: pd.Series | None = None,
    hhi: pd.Series | None = None,
) -> PerformanceStats | None:
    """对 build_return_frame 的输出切片算一组指标。空切片返回 None。"""
    if frame is None or frame.empty or len(frame) < 2:
        return None

    ppy = int(trading_days_per_year)
    net = frame["portfolio_net_return"].astype("float64")
    gross = frame["portfolio_gross_return"].astype("float64")
    bench = frame["benchmark_return"].astype("float64")
    excess = frame["excess_return"].astype("float64")

    # 切片内重新以 1.0 起算, 保证 IS/OOS 各自独立复利
    nav = (1.0 + net).cumprod()
    bnav = (1.0 + bench).cumprod()
    enav = nav / bnav.where(bnav > 0)
    gnav = (1.0 + gross).cumprod()
    n = len(frame)

    total_ret = float(nav.iloc[-1] - 1.0)
    ann_ret = _ann_return(1.0, float(nav.iloc[-1]), n, ppy)
    ann_vol = float(net.std(ddof=1) * np.sqrt(ppy))
    rf_excess = net - risk_free_daily
    sharpe = (
        float(rf_excess.mean() / net.std(ddof=1) * np.sqrt(ppy))
        if net.std(ddof=1) > 0
        else float("nan")
    )

    dd = drawdown_series(nav)
    mdd = float(dd.min())
    dtbl = drawdown_table(nav, top_n=1)
    if not dtbl.empty:
        r0 = dtbl.iloc[0]
        mdd_start = str(pd.Timestamp(r0["peak_date"]).date())
        mdd_trough = str(pd.Timestamp(r0["trough_date"]).date())
        rec = r0["recovery_date"]
        mdd_rec = _NA_DATE if pd.isna(rec) else str(pd.Timestamp(rec).date())
        mdd_dur = int(r0["duration_days"])
        mdd_recd = int(r0["recovery_days"])
    else:
        mdd_start = mdd_trough = mdd_rec = _NA_DATE
        mdd_dur = mdd_recd = 0

    calmar = float(ann_ret / abs(mdd)) if mdd < 0 and np.isfinite(ann_ret) else float("nan")

    bench_total = float(bnav.iloc[-1] - 1.0)
    bench_ann = _ann_return(1.0, float(bnav.iloc[-1]), n, ppy)
    # 几何超额 = 组合累计 / 指数累计 - 1; 算术超额 = 日差均值年化
    exc_total_geo = float(nav.iloc[-1] / bnav.iloc[-1] - 1.0) if bnav.iloc[-1] > 0 else float("nan")
    exc_ann_geo = (
        float((1.0 + ann_ret) / (1.0 + bench_ann) - 1.0)
        if np.isfinite(ann_ret) and np.isfinite(bench_ann) and bench_ann > -1
        else float("nan")
    )
    exc_ann_arith = float(excess.mean() * ppy)
    te = float(excess.std(ddof=1) * np.sqrt(ppy))
    ir = float(exc_ann_arith / te) if te > 0 else float("nan")

    cost = frame.get("trade_cost", pd.Series(0.0, index=frame.index)).astype("float64")
    total_cost = float(cost.sum())
    gross_ann = _ann_return(1.0, float(gnav.iloc[-1]), n, ppy)
    # 成本侵蚀 = 成本拖累的年化收益 / 毛组合相对基准的年化超额
    gross_excess_ann = (
        (1.0 + gross_ann) / (1.0 + bench_ann) - 1.0
        if np.isfinite(gross_ann) and np.isfinite(bench_ann) and bench_ann > -1
        else float("nan")
    )
    erosion = (
        float((gross_ann - ann_ret) / abs(gross_excess_ann))
        if np.isfinite(gross_excess_ann) and abs(gross_excess_ann) > 1e-12
        else float("nan")
    )

    def _mean(s: pd.Series | None) -> float:
        if s is None:
            return float("nan")
        v = s.reindex(frame.index).astype("float64").dropna()
        return float(v.mean()) if not v.empty else float("nan")

    to_ann = float("nan")
    if turnover_oneway is not None:
        tv = turnover_oneway.reindex(frame.index).astype("float64").dropna()
        if not tv.empty:
            to_ann = float(tv.sum() / ((n - 1) / ppy)) if n > 1 else float("nan")

    return PerformanceStats(
        label=label,
        start_date=str(frame.index[0].date()),
        end_date=str(frame.index[-1].date()),
        n_days=n,
        total_return=total_ret,
        annual_return=ann_ret,
        annual_volatility=ann_vol,
        sharpe=sharpe,
        sortino=_sortino(rf_excess, ppy),
        max_drawdown=mdd,
        max_drawdown_start=mdd_start,
        max_drawdown_trough=mdd_trough,
        max_drawdown_recovery=mdd_rec,
        max_drawdown_duration_days=mdd_dur,
        max_drawdown_recovery_days=mdd_recd,
        calmar=calmar,
        benchmark_total_return=bench_total,
        benchmark_annual_return=bench_ann,
        excess_total_return_geometric=exc_total_geo,
        excess_annual_return_geometric=exc_ann_geo,
        excess_annual_return_arithmetic=exc_ann_arith,
        tracking_error=te,
        information_ratio=ir,
        excess_max_drawdown=float(drawdown_series(enav).min()),
        win_rate_daily=float((excess > 0).mean()),
        win_rate_monthly=_period_win_rate(net, bench, "M"),
        win_rate_yearly=_period_win_rate(net, bench, "Y"),
        gross_annual_return=gross_ann,
        turnover_annual_oneway=to_ann,
        total_cost=total_cost,
        cost_erosion_ratio=erosion,
        avg_holdings=_mean(frame.get("n_holdings")),
        avg_top10_concentration=_mean(top10_concentration),
        avg_cash_ratio=_mean(frame.get("cash_ratio")),
        hhi=_mean(hhi),
    )


def _agg_table(frame: pd.DataFrame, freq: str, ppy: int) -> pd.DataFrame:
    """按 freq 分组的收益表 (规范 13: 分年度/分月超额与胜率)。"""
    if frame.empty:
        return pd.DataFrame()
    net = frame["portfolio_net_return"].astype("float64")
    bench = frame["benchmark_return"].astype("float64")
    excess = frame["excess_return"].astype("float64")
    cost = frame.get("trade_cost", pd.Series(0.0, index=frame.index)).astype("float64")
    key = frame.index.to_period(freq)

    def _cum(s: pd.Series) -> pd.Series:
        return (1.0 + s).groupby(key).prod() - 1.0

    p, b = _cum(net), _cum(bench)
    out = pd.DataFrame(
        {
            "portfolio_return": p,
            "benchmark_return": b,
            # 分区间几何超额, 与全样本口径一致
            "excess_return_geometric": (1.0 + p) / (1.0 + b) - 1.0,
            "excess_return_arithmetic": excess.groupby(key).sum(),
            "n_days": net.groupby(key).size(),
            "volatility_annual": net.groupby(key).std(ddof=1) * np.sqrt(ppy),
            "tracking_error_annual": excess.groupby(key).std(ddof=1) * np.sqrt(ppy),
            "win_rate_daily": (excess > 0).groupby(key).mean(),
            "max_drawdown": net.groupby(key).apply(
                lambda s: float(drawdown_series((1.0 + s).cumprod()).min())
            ),
            "trade_cost": cost.groupby(key).sum(),
        }
    )
    out.index = out.index.astype(str)
    out.index.name = {"Y": "year", "M": "month"}.get(freq, freq)
    return out.reset_index()


def yearly_table(frame: pd.DataFrame, *, trading_days_per_year: int = 252) -> pd.DataFrame:
    return _agg_table(frame, "Y", int(trading_days_per_year))


def monthly_table(frame: pd.DataFrame, *, trading_days_per_year: int = 252) -> pd.DataFrame:
    return _agg_table(frame, "M", int(trading_days_per_year))
