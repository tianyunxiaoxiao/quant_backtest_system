"""Convert persisted qbt artifacts into frontend-friendly chart data."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def _to_series(df: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    dates = [str(d) for d in df.index]
    series = []
    for col in columns:
        if col in df.columns:
            series.append({"name": col, "values": df[col].tolist()})
    return {"dates": dates, "series": series}


def _read_json(run_dir: Path, name: str) -> dict[str, Any]:
    path = run_dir / f"{name}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_parquet(run_dir: Path, name: str) -> pd.DataFrame:
    path = run_dir / f"{name}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def nav_data(run_dir: Path) -> dict[str, Any]:
    df = _read_parquet(run_dir, "daily_returns")
    return _to_series(df, ["portfolio_nav", "benchmark_nav", "excess_nav"])


def drawdown_data(run_dir: Path) -> dict[str, Any]:
    df = _read_parquet(run_dir, "daily_returns")
    return _to_series(df, ["portfolio_drawdown", "excess_drawdown"])


def monthly_returns(run_dir: Path) -> dict[str, Any]:
    payload = _read_json(run_dir, "performance_report")
    monthly = payload.get("monthly", {})
    cols = monthly.get("columns", [])
    data = monthly.get("data", [])
    if not cols or not data:
        return {"categories": [], "series": []}
    df = pd.DataFrame(data, columns=cols)
    if "month" not in df.columns:
        return {"categories": [], "series": []}
    return {
        "categories": df["month"].tolist(),
        "series": [
            {"name": "组合", "values": df.get("portfolio_return", pd.Series(dtype=float)).tolist()},
            {"name": "基准", "values": df.get("benchmark_return", pd.Series(dtype=float)).tolist()},
            {"name": "超额", "values": df.get("excess_return_geometric", pd.Series(dtype=float)).tolist()},
        ],
    }


def annual_returns(run_dir: Path) -> dict[str, Any]:
    payload = _read_json(run_dir, "performance_report")
    yearly = payload.get("yearly", {})
    cols = yearly.get("columns", [])
    data = yearly.get("data", [])
    if not cols or not data:
        return {"categories": [], "series": []}
    df = pd.DataFrame(data, columns=cols)
    if "year" not in df.columns:
        return {"categories": [], "series": []}
    return {
        "categories": df["year"].astype(str).tolist(),
        "series": [
            {"name": "组合", "values": df.get("portfolio_return", pd.Series(dtype=float)).tolist()},
            {"name": "基准", "values": df.get("benchmark_return", pd.Series(dtype=float)).tolist()},
            {"name": "超额", "values": df.get("excess_return_geometric", pd.Series(dtype=float)).tolist()},
        ],
    }


def rolling_metrics(run_dir: Path) -> dict[str, Any]:
    payload = _read_json(run_dir, "performance_report")
    rolling = payload.get("rolling", {})
    cols = rolling.get("columns", [])
    data = rolling.get("data", [])
    if not cols or not data:
        return {"dates": [], "series": []}
    df = pd.DataFrame(data, columns=cols)
    df.index = pd.to_datetime(rolling.get("index", []))
    return _to_series(df, ["annual_return", "annual_volatility", "sharpe", "information_ratio"])


def alpha_beta_contrib(run_dir: Path) -> dict[str, Any]:
    payload = _read_json(run_dir, "alpha_beta")
    contrib = payload.get("contributions", {})
    cols = contrib.get("columns", [])
    data = contrib.get("data", [])
    if not cols or not data:
        return {"dates": [], "series": []}
    df = pd.DataFrame(data, columns=cols)
    df.index = pd.to_datetime(contrib.get("index", []))
    return _to_series(df, ["beta_contribution_cum", "alpha_contribution_cum"])


def alpha_beta_rolling(run_dir: Path) -> dict[str, Any]:
    payload = _read_json(run_dir, "alpha_beta")
    rolling = payload.get("rolling", {})
    cols = rolling.get("columns", [])
    data = rolling.get("data", [])
    if not cols or not data:
        return {"dates": [], "series": []}
    df = pd.DataFrame(data, columns=cols)
    df.index = pd.to_datetime(rolling.get("index", []))
    return _to_series(df, ["rolling_beta", "rolling_alpha_annual", "rolling_r_squared", "rolling_alpha_tstat_nw"])


def style_timeseries(run_dir: Path) -> dict[str, Any]:
    df = _read_parquet(run_dir, "style_exposures")
    if df.empty:
        return {"dates": [], "styles": [], "portfolio": {}, "index": {}, "active": {}}
    dates = [str(d) for d in df.index]
    styles = [str(s) for s in df.columns.get_level_values("style").unique()]
    out: dict[str, Any] = {"dates": dates, "styles": styles}
    for view in ("portfolio", "index", "active"):
        try:
            sub = df[view]
        except KeyError:
            sub = pd.DataFrame(index=df.index)
        out[view] = {s: sub[s].tolist() if s in sub.columns else [None] * len(dates) for s in styles}
    return out


def style_heatmap(run_dir: Path) -> dict[str, Any]:
    df = _read_parquet(run_dir, "style_exposures")
    if df.empty:
        return {"years": [], "styles": [], "values": []}
    try:
        active = df["active"]
    except KeyError:
        return {"years": [], "styles": [], "values": []}
    yearly = active.groupby(active.index.year).mean()
    years = [str(y) for y in yearly.index]
    styles = [str(c) for c in yearly.columns]
    values = yearly.to_numpy().tolist()
    return {"years": years, "styles": styles, "values": values}


def style_summary(run_dir: Path) -> dict[str, Any]:
    payload = _read_json(run_dir, "style_exposure_report")
    summary = payload.get("summary", {})
    cols = summary.get("columns", [])
    data = summary.get("data", [])
    if not cols or not data:
        return {"columns": [], "rows": []}
    return {"columns": cols, "rows": data}


def turnover_costs(run_dir: Path) -> dict[str, Any]:
    cash = _read_parquet(run_dir, "cash_ledger")
    costs = _read_parquet(run_dir, "costs")
    dates = [str(d) for d in cash.index]
    series: list[dict[str, Any]] = []
    if "turnover" in cash.columns:
        series.append({"name": "turnover", "values": cash["turnover"].tolist()})
    cost_cols = [c for c in ["commission", "stamp_duty", "transfer_fee", "slippage_cost"] if c in costs.columns]
    if cost_cols:
        for col in cost_cols:
            series.append({"name": col, "values": costs[col].reindex(cash.index).fillna(0.0).tolist()})
    return {"dates": dates, "series": series}


def coverage(run_dir: Path) -> dict[str, Any]:
    payload = _read_json(run_dir, "index_selection_report")
    daily = payload.get("daily", {})
    cols = daily.get("columns", [])
    data = daily.get("data", [])
    if not cols or not data:
        return {"dates": [], "series": []}
    df = pd.DataFrame(data, columns=cols)
    df.index = pd.to_datetime(daily.get("index", []))
    series_cols = [c for c in ["n_index_members", "n_selected", "n_holdings"] if c in df.columns]
    out = _to_series(df, series_cols)
    if "factor_coverage" in df.columns:
        out["series"].append({"name": "factor_coverage", "values": df["factor_coverage"].tolist()})
    return out


def constraint_reports(run_dir: Path) -> dict[str, Any]:
    payload = _read_json(run_dir, "constraint_reports")
    return {"reports": payload.get("constraint_reports", [])}


def performance_summary(run_dir: Path) -> dict[str, Any]:
    payload = _read_json(run_dir, "performance_report")
    return {
        "full_sample": payload.get("full_sample"),
        "in_sample": payload.get("in_sample"),
        "out_of_sample": payload.get("out_of_sample"),
        "definitions": payload.get("definitions", {}),
    }


def alpha_beta_summary(run_dir: Path) -> dict[str, Any]:
    return _read_json(run_dir, "alpha_beta")


def drawdown_table(run_dir: Path) -> dict[str, Any]:
    payload = _read_json(run_dir, "performance_report")
    table = payload.get("drawdown_table", {})
    return {"columns": table.get("columns", []), "rows": table.get("data", [])}


CHART_BUILDERS: dict[str, Any] = {
    "nav": nav_data,
    "drawdown": drawdown_data,
    "monthly": monthly_returns,
    "annual": annual_returns,
    "rolling": rolling_metrics,
    "alpha_beta_contrib": alpha_beta_contrib,
    "alpha_beta_rolling": alpha_beta_rolling,
    "style_timeseries": style_timeseries,
    "style_heatmap": style_heatmap,
    "style_summary": style_summary,
    "turnover_costs": turnover_costs,
    "coverage": coverage,
    "constraints": constraint_reports,
    "performance": performance_summary,
    "alpha_beta": alpha_beta_summary,
    "drawdown_table": drawdown_table,
}
