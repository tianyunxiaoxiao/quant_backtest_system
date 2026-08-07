"""指数内多头选股表现 (规范第 12 节)。

核心要求: 诊断收益与实际可交易收益必须分开展示。
- 诊断收益: 入选股票等权/目标权重的无摩擦收益 (无成本、无整手、无涨跌停),
  衡量的是选股信号本身的强弱。
- 实际收益: 走完下单、整手、ADV、涨跌停、成本之后的净值收益。
两者之差就是实现损耗 (implementation shortfall), 这是规范要求单独暴露的量。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from qbt.contracts.reports import IndexSelectionReport

__all__ = ["build_selection_report"]


def _simulate_frictionless(
    weights: pd.DataFrame,
    *,
    rebalance_dates: tuple[pd.Timestamp, ...],
    adj_close: pd.DataFrame,
    adj_fill_price: pd.DataFrame,
    order_lag_days: int,
    fill_lag_days: int,
) -> tuple[pd.Series, pd.DataFrame]:
    """Run a no-cost fractional-share portfolio on the configured execution clock.

    Existing holdings move from the prior close to the fill price before a rebalance;
    the new holdings then move from fill to close. Between rebalances quantities stay
    fixed, so weights drift naturally. Missing fill prices use the latest valid close;
    an asset with no usable price remains cash.
    """
    dates = adj_close.index
    assets = adj_close.columns
    close = adj_close.astype("float64").to_numpy()
    fill = adj_fill_price.reindex(index=dates, columns=assets).astype("float64").to_numpy()
    target = weights.reindex(index=dates, columns=assets).fillna(0.0).to_numpy(dtype="float64")

    positions = np.zeros(len(assets), dtype="float64")
    cash = 1.0
    previous_nav = 1.0
    last_valid_close = np.full(len(assets), np.nan, dtype="float64")
    returns = np.zeros(len(dates), dtype="float64")
    close_weights = np.zeros((len(dates), len(assets)), dtype="float64")

    date_pos = {date: i for i, date in enumerate(dates)}
    execution_plan: dict[int, int] = {}
    lag = int(order_lag_days) + int(fill_lag_days)
    for signal_date in rebalance_dates:
        signal_i = date_pos.get(pd.Timestamp(signal_date))
        if signal_i is not None and signal_i + lag < len(dates):
            execution_plan[signal_i + lag] = signal_i

    for i in range(len(dates)):
        close_i = close[i]
        close_valid = np.isfinite(close_i) & (close_i > 0)
        valuation_close = np.where(close_valid, close_i, last_valid_close)

        signal_i = execution_plan.get(i)
        if signal_i is not None:
            fill_i = fill[i]
            fill_valid = np.isfinite(fill_i) & (fill_i > 0)
            valuation_fill = np.where(fill_valid, fill_i, last_valid_close)
            executable = np.isfinite(valuation_fill) & (valuation_fill > 0)
            equity_at_fill = cash + float(
                np.nansum(positions * np.nan_to_num(valuation_fill))
            )
            desired = np.clip(target[signal_i], 0.0, np.inf)
            positions = np.divide(
                desired * equity_at_fill,
                valuation_fill,
                out=np.zeros_like(positions),
                where=executable,
            )
            cash = equity_at_fill - float(
                np.nansum(positions * np.nan_to_num(valuation_fill))
            )

        fallback = np.where(np.isfinite(valuation_close), valuation_close, 0.0)
        market_value = positions * fallback
        nav = cash + float(market_value.sum())
        returns[i] = nav / previous_nav - 1.0 if previous_nav > 0 else np.nan
        if nav > 0:
            close_weights[i] = market_value / nav
        previous_nav = nav
        last_valid_close = np.where(close_valid, close_i, last_valid_close)

    return (
        pd.Series(returns, index=dates, name="diagnostic_return"),
        pd.DataFrame(close_weights, index=dates, columns=assets),
    )


def _agg(sub: pd.DataFrame) -> dict:
    """一个样本区间的选股表现汇总。用几何累乘, 不用日均加总。"""
    if sub.empty:
        return {}
    def geo(col: str) -> float:
        s = sub[col].dropna().astype("float64")
        return float((1.0 + s).prod() - 1.0) if len(s) else np.nan

    port, bench = geo("portfolio_net_return"), geo("benchmark_return")
    eq_w = geo("equal_weight_diagnostic_return")
    tgt_w = geo("target_weight_diagnostic_return")
    ex = sub["excess_return"].dropna() if "excess_return" in sub else pd.Series(dtype="float64")
    gross = geo("portfolio_gross_return")
    return {
        "n_days": int(len(sub)),
        "portfolio_net_return": port,
        "portfolio_gross_return": gross,
        "benchmark_return": bench,
        "excess_return_geometric": (1.0 + port) / (1.0 + bench) - 1.0
        if np.isfinite(port) and np.isfinite(bench) and bench != -1 else np.nan,
        "equal_weight_diagnostic_return": eq_w,
        "target_weight_diagnostic_return": tgt_w,
        # 实现损耗: 诊断组合跑赢实际组合多少, 正数表示摩擦吃掉了收益
        "implementation_shortfall": (tgt_w - port)
        if np.isfinite(tgt_w) and np.isfinite(port) else np.nan,
        "excess_win_rate_daily": float((ex > 0).mean()) if len(ex) else np.nan,
        "mean_n_index_members": float(sub["n_index_members"].mean())
        if "n_index_members" in sub else np.nan,
        "mean_n_selected": float(sub["n_selected"].mean())
        if "n_selected" in sub else np.nan,
        "mean_n_holdings": float(sub["n_holdings"].mean())
        if "n_holdings" in sub else np.nan,
        "mean_factor_coverage": float(sub["factor_coverage"].mean())
        if "factor_coverage" in sub else np.nan,
        "total_trade_cost": float(sub["trade_cost"].sum())
        if "trade_cost" in sub else np.nan,
        "cost_erosion_ratio": float(sub["cost_erosion_ratio"].dropna().iloc[-1])
        if "cost_erosion_ratio" in sub and sub["cost_erosion_ratio"].notna().any()
        else np.nan,
        "total_unfilled_orders": float(sub["n_unfilled"].sum())
        if "n_unfilled" in sub else np.nan,
        "total_unfilled_amount": float(sub["unfilled_amount"].sum())
        if "unfilled_amount" in sub else np.nan,
    }


def build_selection_report(
    *,
    return_frame: pd.DataFrame,
    selection_diagnostics: pd.DataFrame,
    selected: pd.DataFrame,
    target_weights: pd.DataFrame,
    rebalance_dates: tuple[pd.Timestamp, ...],
    adj_close: pd.DataFrame,
    adj_fill_price: pd.DataFrame,
    order_lag_days: int = 1,
    fill_lag_days: int = 0,
    fill_price_field: str = "adj_vwap",
    fills: pd.DataFrame | None = None,
    factor_coverage: pd.Series | None = None,
    unfilled_summary: pd.DataFrame | None = None,
    oos_start: pd.Timestamp | None = None,
) -> IndexSelectionReport:
    """组装规范 12 要求的逐日/年度/样本内外选股表现表。"""
    dates = return_frame.index

    # 诊断收益: 等权 与 目标权重, 都无摩擦
    eq_w = selected.astype("float64")
    row_n = eq_w.to_numpy().sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        eq_norm = np.where(row_n[:, None] > 0, eq_w.to_numpy() / row_n[:, None], 0.0)
    eq_w = pd.DataFrame(eq_norm, index=selected.index, columns=selected.columns)

    eq_ret, _ = _simulate_frictionless(
        eq_w,
        rebalance_dates=rebalance_dates,
        adj_close=adj_close,
        adj_fill_price=adj_fill_price,
        order_lag_days=order_lag_days,
        fill_lag_days=fill_lag_days,
    )
    tgt_ret, _ = _simulate_frictionless(
        target_weights,
        rebalance_dates=rebalance_dates,
        adj_close=adj_close,
        adj_fill_price=adj_fill_price,
        order_lag_days=order_lag_days,
        fill_lag_days=fill_lag_days,
    )
    eq_ret = eq_ret.reindex(dates).fillna(0.0)
    tgt_ret = tgt_ret.reindex(dates).fillna(0.0)

    daily = pd.DataFrame(index=dates)
    daily.index.name = "date"
    for col in ("portfolio_net_return", "portfolio_gross_return", "benchmark_return",
                "excess_return", "trade_cost", "n_holdings",
                "cash_ratio", "turnover", "is_rebalance"):
        if col in return_frame.columns:
            daily[col] = return_frame[col]

    sd = selection_diagnostics.reindex(dates)
    for col in ("n_index_members", "n_eligible", "n_selected", "n_target",
                "eligible_ratio"):
        if col in sd.columns:
            daily[col] = sd[col]

    daily["equal_weight_diagnostic_return"] = eq_ret
    daily["target_weight_diagnostic_return"] = tgt_ret
    daily["diagnostic_minus_actual"] = tgt_ret - daily["portfolio_net_return"]

    if factor_coverage is not None:
        daily["factor_coverage"] = factor_coverage.reindex(dates)
    elif "eligible_ratio" in daily.columns:
        daily["factor_coverage"] = daily["eligible_ratio"]

    if unfilled_summary is not None and not unfilled_summary.empty and "date" in unfilled_summary.columns:
        us = unfilled_summary.copy().set_index("date")
        agg = us.groupby(level=0).agg(
            n_unfilled=("asset_id", "size"),
            unfilled_amount=("unfilled_amount", "sum"),
        )
        daily["n_unfilled"] = agg["n_unfilled"].reindex(dates).fillna(0.0)
        daily["unfilled_amount"] = agg["unfilled_amount"].reindex(dates).fillna(0.0)
    else:
        daily["n_unfilled"] = 0.0
        daily["unfilled_amount"] = 0.0

    if fills is not None and not fills.empty:
        executed = fills[
            (fills["filled_quantity"] > 0) & fills["fill_date"].notna()
        ].copy()
        if not executed.empty:
            fill_daily = executed.groupby("fill_date").agg(
                adv_participation_mean=("adv_participation", "mean"),
                adv_participation_max=("adv_participation", "max"),
                filled_amount=("filled_amount", "sum"),
            )
            for column in fill_daily.columns:
                daily[column] = fill_daily[column].reindex(dates).fillna(0.0)
    for column in ("adv_participation_mean", "adv_participation_max", "filled_amount"):
        if column not in daily:
            daily[column] = 0.0
    attempted_amount = daily["filled_amount"] + daily["unfilled_amount"]
    daily["unfilled_ratio"] = np.where(
        attempted_amount > 0,
        daily["unfilled_amount"] / attempted_amount,
        0.0,
    )

    # 成本侵蚀比例 = 累计成本 / 累计毛收益规模, 用累计口径避免单日除零
    if "trade_cost" in daily.columns and "portfolio_gross_return" in daily.columns:
        cum_cost = daily["trade_cost"].cumsum()
        gross_eq = (1.0 + daily["portfolio_gross_return"].fillna(0.0)).cumprod()
        net_eq = (1.0 + daily["portfolio_net_return"].fillna(0.0)).cumprod()
        benchmark_eq = (1.0 + daily["benchmark_return"].fillna(0.0)).cumprod()
        gap = gross_eq - net_eq
        gross_excess = gross_eq / benchmark_eq.where(benchmark_eq > 0) - 1.0
        with np.errstate(invalid="ignore", divide="ignore"):
            daily["cost_erosion_ratio"] = np.where(
                gross_excess.abs() > 1e-12, gap / gross_excess.abs(), np.nan
            )
        daily["cumulative_trade_cost"] = cum_cost

    # 年度表
    years = daily.index.year
    yearly = pd.DataFrame(
        [{"year": int(y), **_agg(daily[years == y])} for y in sorted(set(years))]
    )

    # IS / OOS
    rows: list[dict] = []
    if oos_start is not None:
        cut = pd.Timestamp(oos_start)
        parts = {"in_sample": daily[daily.index < cut], "out_of_sample": daily[daily.index >= cut]}
    else:
        parts = {"full_sample": daily}
    parts["full_sample"] = daily
    for name, sub in parts.items():
        if sub.empty:
            rows.append({"sample": name, "n_days": 0})
            continue
        rows.append({"sample": name, **_agg(sub)})
    by_sample = pd.DataFrame(rows)

    notes = {
        "diagnostic_definition": "等权/目标权重诊断收益不含交易成本、整手约束、涨跌停与 ADV 限制,"
                                 "仅衡量选股信号强度, 不可作为可实现收益。",
        "actual_definition": "portfolio_net_return 为扣费后实际净值收益, 含全部执行摩擦。",
        "shortfall_definition": "implementation_shortfall = 目标权重诊断收益 - 实际净收益, "
                                "正数表示执行摩擦侵蚀了信号收益。",
        "timing": f"T 日收盘定权重, T+{order_lag_days + fill_lag_days} "
                  f"按 {fill_price_field} 无摩擦成交; 成交日计入成交价到收盘的收益, "
                  "非调仓日持仓数量不变、权重自然漂移。",
    }

    return IndexSelectionReport(
        daily=daily,
        yearly=yearly,
        by_sample=by_sample,
        diagnostic_equal_weight_returns=eq_ret.rename("equal_weight_diagnostic_return"),
        diagnostic_target_weight_returns=tgt_ret.rename("target_weight_diagnostic_return"),
        notes=notes,
    )
