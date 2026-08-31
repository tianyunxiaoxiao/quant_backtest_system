"""Rebase immutable portfolio results against a selectable report benchmark."""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qbt.analytics.alphabeta import compute_alpha_beta
from qbt.analytics.metrics import compute_performance_stats
from qbt.analytics.returns import drawdown_series
from qbt.contracts import RegressionConfig

RUN_BENCHMARK_ID = "ALL_A_EQ"
RUN_BENCHMARK_NAME = "流动性过滤后的非 ST A 股"
_BENCHMARK_INDEPENDENT_METRICS = (
    "turnover_annual_oneway",
    "total_cost",
    "avg_holdings",
    "avg_top10_concentration",
    "avg_cash_ratio",
    "hhi",
)


def _manifest(warehouse_dir: Path) -> dict[str, Any]:
    path = Path(warehouse_dir) / "benchmarks" / "manifest.json"
    if not path.is_file():
        return {"benchmarks": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "qbt_benchmark_quotes/v1":
        raise ValueError(f"不支持的基准行情清单版本: {payload.get('schema_version')}")
    return payload


def list_benchmarks(warehouse_dir: Path) -> list[dict[str, Any]]:
    items = [
        {
            "benchmark_id": RUN_BENCHMARK_ID,
            "name": RUN_BENCHMARK_NAME,
            "date_min": None,
            "date_max": None,
            "source": "回测产物内置基准",
        }
    ]
    for item in _manifest(warehouse_dir).get("benchmarks", []):
        items.append(
            {
                "benchmark_id": str(item["benchmark_id"]),
                "name": str(item["name"]),
                "date_min": item.get("date_min"),
                "date_max": item.get("date_max"),
                "source": item.get("source_uri"),
            }
        )
    return items


def _benchmark_returns(
    run_frame: pd.DataFrame,
    benchmark_id: str,
    warehouse_dir: Path,
) -> tuple[pd.Series, dict[str, Any]]:
    if benchmark_id == RUN_BENCHMARK_ID:
        values = run_frame["benchmark_return"].astype("float64").copy()
        return values, {
            "benchmark_id": benchmark_id,
            "name": RUN_BENCHMARK_NAME,
            "source": "run:daily_returns.benchmark_return",
        }

    entries = {
        str(item["benchmark_id"]): item for item in _manifest(warehouse_dir).get("benchmarks", [])
    }
    if benchmark_id not in entries:
        raise KeyError(f"未知对比基准: {benchmark_id}")
    item = entries[benchmark_id]
    path = Path(warehouse_dir) / "benchmarks" / str(item["file"])
    quotes = pd.read_parquet(path)
    quotes["date"] = pd.to_datetime(quotes["date"])
    close = quotes.set_index("date")["close"].sort_index().astype("float64")
    returns = close.pct_change(fill_method=None).reindex(run_frame.index)
    missing = returns.iloc[1:].isna()
    if missing.any():
        dates = [str(value.date()) for value in returns.index[1:][missing][:5]]
        raise ValueError(f"基准 {benchmark_id} 在回测区间缺少交易日: {dates}")
    returns.iloc[0] = 0.0
    return returns, {
        "benchmark_id": benchmark_id,
        "name": str(item["name"]),
        "source": item.get("source_uri"),
        "source_sha256": item.get("source_sha256"),
        "date_min": item.get("date_min"),
        "date_max": item.get("date_max"),
    }


def _finite_json(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _finite_json(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): _finite_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_json(item) for item in value]
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    return value


def _read_full_sample_metrics(run_dir: Path) -> dict[str, Any]:
    """Read authoritative metrics saved with the immutable original run."""
    path = Path(run_dir) / "performance_report.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    full_sample = payload.get("full_sample")
    return full_sample if isinstance(full_sample, dict) else {}


def _enrich_legacy_return_frame(run_dir: Path, frame: pd.DataFrame) -> pd.DataFrame:
    """Restore analytics columns omitted by historical daily_returns artifacts."""
    enriched = frame.copy()
    ledger_path = Path(run_dir) / "cash_ledger.parquet"
    if ledger_path.is_file():
        ledger = pd.read_parquet(ledger_path)
        ledger.index = pd.DatetimeIndex(ledger.index)
        for column in (
            "trade_cost",
            "cash_ratio",
            "n_holdings",
            "is_rebalance",
            "turnover",
            "sell_amount",
            "buy_amount",
        ):
            if column not in enriched and column in ledger:
                enriched[column] = ledger[column].reindex(enriched.index)

    need_weights = "top10_concentration" not in enriched or "hhi" not in enriched
    weights_path = Path(run_dir) / "actual_weights.parquet"
    if need_weights and weights_path.is_file():
        weights = pd.read_parquet(weights_path)
        weights.index = pd.DatetimeIndex(weights.index)
        values = weights.reindex(index=enriched.index).fillna(0.0).to_numpy(dtype="float64")
        if "top10_concentration" not in enriched:
            sorted_values = np.sort(values, axis=1)[:, ::-1]
            enriched["top10_concentration"] = sorted_values[:, :10].sum(axis=1)
        if "hhi" not in enriched:
            enriched["hhi"] = np.square(values).sum(axis=1)
    return enriched


def _line_chart(frame: pd.DataFrame, columns: tuple[str, ...]) -> dict[str, Any]:
    return {
        "dates": [str(value) for value in frame.index],
        "series": [
            {"name": column, "values": frame[column].tolist()}
            for column in columns
            if column in frame
        ],
    }


def _period_return_chart(frame: pd.DataFrame, frequency: str) -> dict[str, Any]:
    periods = frame.index.to_period(frequency)
    categories: list[str] = []
    portfolio: list[float] = []
    benchmark: list[float] = []
    excess: list[float] = []
    for period in periods.unique():
        sub = frame.loc[periods == period]
        portfolio_return = float((1.0 + sub["portfolio_net_return"]).prod() - 1.0)
        benchmark_return = float((1.0 + sub["benchmark_return"]).prod() - 1.0)
        excess_return = (
            (1.0 + portfolio_return) / (1.0 + benchmark_return) - 1.0
            if benchmark_return != -1.0
            else np.nan
        )
        categories.append(str(period))
        portfolio.append(portfolio_return)
        benchmark.append(benchmark_return)
        excess.append(excess_return)
    return {
        "categories": categories,
        "series": [
            {"name": "组合", "values": portfolio},
            {"name": "基准", "values": benchmark},
            {"name": "超额", "values": excess},
        ],
    }


def _rolling_chart(frame: pd.DataFrame, trading_days_per_year: int = 252) -> dict[str, Any]:
    window = 252
    minimum = 120
    net = frame["portfolio_net_return"].astype("float64")
    excess = frame["excess_return"].astype("float64")
    rolling = pd.DataFrame(index=frame.index)
    rolling["annual_return"] = net.rolling(window, min_periods=minimum).mean() * trading_days_per_year
    rolling["annual_volatility"] = (
        net.rolling(window, min_periods=minimum).std(ddof=1)
        * np.sqrt(trading_days_per_year)
    )
    rolling["sharpe"] = rolling["annual_return"] / rolling["annual_volatility"].where(
        rolling["annual_volatility"] > 0
    )
    tracking_error = (
        excess.rolling(window, min_periods=minimum).std(ddof=1)
        * np.sqrt(trading_days_per_year)
    )
    rolling["information_ratio"] = (
        excess.rolling(window, min_periods=minimum).mean() * trading_days_per_year
    ) / tracking_error.where(tracking_error > 0)
    return _line_chart(
        rolling,
        ("annual_return", "annual_volatility", "sharpe", "information_ratio"),
    )


def _returns_charts(frame: pd.DataFrame) -> dict[str, Any]:
    drawdown = pd.DataFrame(
        {
            "portfolio_drawdown": frame["portfolio_drawdown"],
            "excess_drawdown": frame["excess_drawdown"],
        },
        index=frame.index,
    )
    return {
        "drawdown": _line_chart(drawdown, ("portfolio_drawdown", "excess_drawdown")),
        "monthly": _period_return_chart(frame, "M"),
        "annual": _period_return_chart(frame, "Y"),
        "rolling": _rolling_chart(frame),
    }


def compare_run(run_dir: Path, benchmark_id: str, warehouse_dir: Path) -> dict[str, Any]:
    path = Path(run_dir) / "daily_returns.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"回测日收益产物不存在: {path}")
    frame = pd.read_parquet(path).sort_index()
    frame.index = pd.DatetimeIndex(frame.index)
    frame = _enrich_legacy_return_frame(run_dir, frame)
    if len(frame) < 2:
        raise ValueError("回测交易日不足，无法切换基准")
    benchmark, benchmark_meta = _benchmark_returns(frame, benchmark_id, warehouse_dir)
    frame = frame.copy()
    frame["benchmark_return"] = benchmark
    frame["excess_return"] = frame["portfolio_net_return"] - benchmark
    frame["benchmark_nav"] = (1.0 + benchmark).cumprod()
    frame["excess_nav"] = frame["portfolio_nav"] / frame["benchmark_nav"]
    frame["portfolio_drawdown"] = drawdown_series(frame["portfolio_nav"])
    frame["benchmark_drawdown"] = drawdown_series(frame["benchmark_nav"])
    frame["excess_drawdown"] = drawdown_series(frame["excess_nav"])

    stats = compute_performance_stats(
        frame,
        label="full_sample",
        turnover_oneway=frame.get("turnover"),
        top10_concentration=frame.get("top10_concentration"),
        hhi=frame.get("hhi"),
    )
    if stats is None:
        raise ValueError("无法计算切换基准后的绩效")
    alpha_beta = compute_alpha_beta(frame, config=RegressionConfig())
    performance = _finite_json(stats)
    original_metrics = _read_full_sample_metrics(run_dir)
    for key in _BENCHMARK_INDEPENDENT_METRICS:
        if original_metrics.get(key) is not None:
            performance[key] = _finite_json(original_metrics[key])
    summary = dict(performance)
    summary.update(
        {
            "alpha_annual": _finite_json(alpha_beta.alpha_annual),
            "beta": _finite_json(alpha_beta.beta),
            "alpha_tstat_nw": _finite_json(alpha_beta.alpha_tstat_nw),
            "r_squared": _finite_json(alpha_beta.r_squared),
        }
    )
    nav = pd.DataFrame(
        {
            "组合收益率": frame["portfolio_nav"] - 1.0,
            "基准收益率": frame["benchmark_nav"] - 1.0,
            "超额收益率": frame["excess_nav"] - 1.0,
        },
        index=frame.index,
    )
    return _finite_json(
        {
            "benchmark": benchmark_meta,
            "summary": summary,
            "performance": performance,
            "nav": {
                "dates": [str(value) for value in nav.index],
                "series": [
                    {"name": column, "values": nav[column].tolist()} for column in nav.columns
                ],
            },
            "charts": _returns_charts(frame),
        }
    )
