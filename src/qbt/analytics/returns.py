"""日度收益、净值与回撤序列 (规范第 9 节)。

正式收益一律由实际成交后的账户净值推出; 目标权重收益只在诊断列出现,
永远不参与正式口径。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["build_return_frame", "drawdown_series", "drawdown_table"]


def _safe_pct_change(nav: pd.Series) -> pd.Series:
    prev = nav.shift(1)
    out = nav / prev.where(prev > 0) - 1.0
    return out.fillna(0.0)


def build_return_frame(
    cash_ledger: pd.DataFrame,
    benchmark_return: pd.Series,
    *,
    risk_free_daily: float = 0.0,
) -> pd.DataFrame:
    """把账户流水折成规范第 9 节要求的日度收益/净值表。

    参数
    ----
    cash_ledger : 引擎输出, index 为交易日, 需含 net_assets / open_net_assets /
        trade_cost 列。
    benchmark_return : 指数日收益, 会按 cash_ledger 的交易日对齐。
    risk_free_daily : 日度无风险利率 (导师 A5: v1 默认 0)。
    """
    if cash_ledger.empty:
        raise ValueError("cash_ledger 为空, 无法计算收益序列")

    idx = cash_ledger.index
    nav_abs = cash_ledger["net_assets"].astype("float64")
    base = float(nav_abs.iloc[0])
    if not np.isfinite(base) or base <= 0:
        raise ValueError(f"起始净资产非法: {base!r}")

    net_ret = _safe_pct_change(nav_abs)

    # 毛收益: 把当日交易成本加回当日净资产增量。
    # gross_t = (NAV_t + cost_t - NAV_{t-1}) / NAV_{t-1}
    cost = cash_ledger.get("trade_cost", pd.Series(0.0, index=idx)).astype("float64")
    prev_nav = nav_abs.shift(1)
    gross_ret = ((nav_abs + cost - prev_nav) / prev_nav.where(prev_nav > 0)).fillna(0.0)

    bench = benchmark_return.reindex(idx)
    bench_missing = bench.isna()
    bench = bench.fillna(0.0).astype("float64")

    excess = net_ret - bench

    nav = nav_abs / base
    bench_nav = (1.0 + bench).cumprod()
    # 确认清单 F2: 超额净值采用几何超额，即组合净值 / 基准净值。
    excess_nav = nav / bench_nav.where(bench_nav > 0)
    gross_nav = (1.0 + gross_ret).cumprod()

    out = pd.DataFrame(
        {
            "net_assets": nav_abs,
            "portfolio_gross_return": gross_ret,
            "portfolio_net_return": net_ret,
            "benchmark_return": bench,
            "excess_return": excess,
            "portfolio_excess_over_rf": net_ret - risk_free_daily,
            "benchmark_excess_over_rf": bench - risk_free_daily,
            "portfolio_nav": nav,
            "portfolio_gross_nav": gross_nav,
            "benchmark_nav": bench_nav,
            "excess_nav": excess_nav,
            "trade_cost": cost,
            "benchmark_is_missing": bench_missing.to_numpy(),
        },
        index=idx,
    )
    out["portfolio_drawdown"] = drawdown_series(out["portfolio_nav"])
    out["benchmark_drawdown"] = drawdown_series(out["benchmark_nav"])
    out["excess_drawdown"] = drawdown_series(out["excess_nav"])
    for col in ("cash_ratio", "n_holdings", "is_rebalance", "turnover",
                "sell_amount", "buy_amount"):
        if col in cash_ledger.columns:
            out[col] = cash_ledger[col]
    out.index.name = "date"
    return out


def drawdown_series(nav: pd.Series) -> pd.Series:
    """相对历史最高点的回撤 (<= 0)。"""
    nav = nav.astype("float64")
    peak = nav.cummax()
    return (nav / peak.where(peak > 0) - 1.0).fillna(0.0)


def drawdown_table(nav: pd.Series, *, top_n: int = 10) -> pd.DataFrame:
    """逐段回撤明细: 起点、谷底、修复日、持续与修复天数。

    未修复的段 recovery_date 为 NaT, recovery_days 为 -1, 便于报告区分
    "还在水下"和"已修复"。
    """
    nav = nav.astype("float64").dropna()
    if nav.empty:
        return pd.DataFrame()
    peak = nav.cummax()
    under = nav < peak * (1.0 - 1e-12)

    segments: list[dict] = []
    start_i: int | None = None
    for i, flag in enumerate(under.to_numpy()):
        if flag and start_i is None:
            start_i = i
        elif not flag and start_i is not None:
            segments.append({"s": start_i, "e": i - 1, "rec": i})
            start_i = None
    if start_i is not None:
        segments.append({"s": start_i, "e": len(nav) - 1, "rec": None})

    rows = []
    for seg in segments:
        s, e = seg["s"], seg["e"]
        window = nav.iloc[s : e + 1]
        trough_pos = int(np.argmin(window.to_numpy()))
        trough_date = window.index[trough_pos]
        peak_date = nav.index[s - 1] if s > 0 else nav.index[0]
        peak_val = float(peak.iloc[s])
        depth = float(window.iloc[trough_pos] / peak_val - 1.0)
        rec_idx = seg["rec"]
        rec_date = nav.index[rec_idx] if rec_idx is not None else pd.NaT
        rows.append(
            {
                "peak_date": peak_date,
                "trough_date": trough_date,
                "recovery_date": rec_date,
                "max_drawdown": depth,
                "duration_days": int(e - s + 1),
                "to_trough_days": int(trough_pos + 1),
                "recovery_days": int(rec_idx - trough_pos - s) if rec_idx is not None else -1,
                "is_recovered": rec_idx is not None,
            }
        )
    tbl = pd.DataFrame(rows)
    if tbl.empty:
        return tbl
    return tbl.sort_values("max_drawdown").head(top_n).reset_index(drop=True)
