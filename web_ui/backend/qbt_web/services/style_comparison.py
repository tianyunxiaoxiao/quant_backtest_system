"""Recalculate active style exposure against a selectable benchmark."""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qbt.analytics.style import weighted_exposure
from qbt.data.barra import load_barra_style_exposures
from qbt.data.ingest_index import INDEX_SPECS, expand_monthly_to_daily, ingest_index_membership

from .benchmark_comparison import RUN_BENCHMARK_ID, RUN_BENCHMARK_NAME, _manifest


def _finite(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    return value


def _benchmark_meta(benchmark_id: str, warehouse_dir: Path) -> dict[str, Any]:
    if benchmark_id == RUN_BENCHMARK_ID:
        return {
            "benchmark_id": benchmark_id,
            "name": RUN_BENCHMARK_NAME,
            "source": "run:style_exposures.index",
        }
    entries = {
        str(item["benchmark_id"]): item
        for item in _manifest(warehouse_dir).get("benchmarks", [])
    }
    if benchmark_id not in entries:
        raise KeyError(f"未知对比基准: {benchmark_id}")
    item = entries[benchmark_id]
    return {
        "benchmark_id": benchmark_id,
        "name": str(item["name"]),
        "source": item.get("source_uri"),
    }


def _load_monthly_weights(
    benchmark_id: str,
    *,
    index_weights_dir: Path | None,
    index_source_dir: Path,
) -> pd.DataFrame:
    if benchmark_id not in INDEX_SPECS:
        raise KeyError(f"基准没有可用的 PIT 成分权重: {benchmark_id}")
    if index_weights_dir is not None:
        path = Path(index_weights_dir) / f"{benchmark_id}_monthly.parquet"
        if path.is_file():
            frame = pd.read_parquet(path)
            frame["snapshot_date"] = pd.to_datetime(frame["snapshot_date"]).dt.normalize()
            return frame
    monthly, _ = ingest_index_membership(Path(index_source_dir), INDEX_SPECS[benchmark_id])
    return monthly


def _summary(portfolio: pd.DataFrame, index: pd.DataFrame, active: pd.DataFrame) -> dict[str, Any]:
    rows = []
    for style in portfolio.columns:
        series = active[style]
        rows.append(
            [
                str(style),
                portfolio[style].mean(),
                index[style].mean(),
                series.mean(),
                series.std(ddof=1),
                series.abs().max(),
                series.dropna().iloc[-1] if series.notna().any() else np.nan,
                series.isna().mean(),
            ]
        )
    return {
        "columns": [
            "style",
            "portfolio_mean",
            "index_mean",
            "active_mean",
            "active_std",
            "active_max_abs",
            "active_latest",
            "missing_ratio",
        ],
        "rows": rows,
    }


@lru_cache(maxsize=64)
def compare_style_run(
    run_dir: Path,
    benchmark_id: str,
    warehouse_dir: Path,
    *,
    barra_dir: Path | None,
    index_weights_dir: Path | None,
    index_source_dir: Path,
) -> dict[str, Any]:
    """Return portfolio/index/active style series for a report benchmark."""
    path = Path(run_dir) / "style_exposures.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"风格暴露产物不存在: {path}")
    stored = pd.read_parquet(path).sort_index()
    stored.index = pd.DatetimeIndex(stored.index).normalize()
    if stored.empty or "portfolio" not in stored.columns.get_level_values(0):
        raise ValueError("风格暴露产物为空或缺少组合暴露")

    portfolio = stored["portfolio"].astype("float64")
    dates = portfolio.index
    benchmark_meta = _benchmark_meta(benchmark_id, Path(warehouse_dir))
    coverage: dict[str, float | None] = {}

    if benchmark_id == RUN_BENCHMARK_ID:
        index = stored["index"].reindex(index=dates, columns=portfolio.columns).astype("float64")
    else:
        if barra_dir is None:
            raise ValueError("未配置 Barra 暴露目录，无法切换风格基准")
        monthly = _load_monthly_weights(
            benchmark_id,
            index_weights_dir=index_weights_dir,
            index_source_dir=index_source_dir,
        )
        assets = pd.Index(sorted(monthly["asset_id"].astype(str).unique()), name="asset_id")
        _, weights = expand_monthly_to_daily(monthly, dates, assets=assets)
        panels, _, barra_meta = load_barra_style_exposures(
            barra_dir,
            dates=dates,
            assets=assets,
        )
        by_name = {name.lower(): panel for name, panel in panels.items()}
        index_columns: dict[str, pd.Series] = {}
        for style in portfolio.columns:
            panel = by_name.get(str(style).lower())
            if panel is None:
                index_columns[str(style)] = pd.Series(np.nan, index=dates)
                coverage[str(style)] = None
                continue
            exposure, style_coverage = weighted_exposure(weights.fillna(0.0), panel)
            index_columns[str(style)] = exposure
            coverage[str(style)] = (
                float(style_coverage.mean()) if style_coverage.notna().any() else None
            )
        index = pd.DataFrame(index_columns, index=dates).reindex(columns=portfolio.columns)
        benchmark_meta.update(
            {
                "weight_source": "pit_monthly_index_weights",
                "weight_snapshot_date_max": str(pd.Timestamp(monthly["snapshot_date"].max()).date()),
                "style_source": barra_meta["data_source"],
            }
        )

    active = portfolio - index
    yearly = active.groupby(active.index.year).mean()
    timeseries = {
        "dates": [str(value) for value in dates],
        "styles": [str(value) for value in portfolio.columns],
        "portfolio": {str(c): portfolio[c].tolist() for c in portfolio.columns},
        "index": {str(c): index[c].tolist() for c in index.columns},
        "active": {str(c): active[c].tolist() for c in active.columns},
    }
    return _finite(
        {
            "benchmark": benchmark_meta,
            "timeseries": timeseries,
            "heatmap": {
                "years": [str(value) for value in yearly.index],
                "styles": [str(value) for value in yearly.columns],
                "values": yearly.to_numpy().tolist(),
            },
            "summary": _summary(portfolio, index, active),
            "index_weight_coverage_mean": coverage,
        }
    )
