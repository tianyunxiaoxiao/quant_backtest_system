"""Attribute benchmark-relative returns to Barra styles and residual alpha."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qbt.data.barra import load_barra_factor_returns

from .benchmark_comparison import _benchmark_returns, _finite_json
from .style_comparison import compare_style_run


@lru_cache(maxsize=64)
def barra_style_attribution(
    run_dir: Path,
    benchmark_id: str,
    warehouse_dir: Path,
    *,
    barra_dir: Path | None,
    index_weights_dir: Path | None,
    index_source_dir: Path,
) -> dict[str, Any]:
    """Build additive daily attribution using lagged active style exposure."""
    if barra_dir is None:
        raise ValueError("未配置 Barra 数据目录，无法计算风格收益归因")

    return_path = Path(run_dir) / "daily_returns.parquet"
    if not return_path.is_file():
        raise FileNotFoundError(f"回测日收益产物不存在: {return_path}")
    returns = pd.read_parquet(return_path).sort_index()
    returns.index = pd.DatetimeIndex(returns.index).normalize()
    benchmark, benchmark_meta = _benchmark_returns(returns, benchmark_id, warehouse_dir)
    arithmetic_excess = returns["portfolio_net_return"].astype("float64") - benchmark

    style_payload = compare_style_run(
        Path(run_dir),
        benchmark_id,
        Path(warehouse_dir),
        barra_dir=Path(barra_dir),
        index_weights_dir=Path(index_weights_dir) if index_weights_dir is not None else None,
        index_source_dir=Path(index_source_dir),
    )
    timeseries = style_payload["timeseries"]
    dates = pd.DatetimeIndex(pd.to_datetime(timeseries["dates"])).normalize()
    active = pd.DataFrame(timeseries["active"], index=dates).astype("float64")
    factor_returns, factor_meta = load_barra_factor_returns(Path(barra_dir), dates=dates)
    styles = [
        style
        for style in active.columns
        if style in factor_returns.columns and active[style].notna().any()
    ]
    if not styles:
        raise ValueError("回测风格暴露与 Barra 因子收益没有共同字段")

    lagged_active = active[styles].shift(1)
    aligned_factor_returns = factor_returns[styles].reindex(dates)
    contributions = lagged_active * aligned_factor_returns
    complete = lagged_active.notna().all(axis=1) & aligned_factor_returns.notna().all(axis=1)
    style_return = contributions.sum(axis=1, min_count=len(styles)).where(complete)
    excess = arithmetic_excess.reindex(dates).where(complete)
    pure_alpha = excess - style_return

    daily = pd.DataFrame(
        {
            "actual_excess_return": excess,
            "barra_style_return": style_return,
            "pure_alpha_return": pure_alpha,
        },
        index=dates,
    )
    cumulative = daily.cumsum()
    identity_error = (daily["actual_excess_return"] - daily["barra_style_return"] - daily["pure_alpha_return"]).abs()
    valid_identity = identity_error.dropna()

    return _finite_json(
        {
            "benchmark": benchmark_meta,
            "factor_returns": factor_meta,
            "method": {
                "exposure_lag_days": 1,
                "styles": styles,
                "aggregation": "arithmetic_additive_cumulative_sum",
                "unavailable_styles": [
                    style for style in factor_returns.columns if style not in styles
                ],
                "alpha_definition": (
                    f"benchmark-relative return minus {len(styles)} available Barra style contributions"
                ),
            },
            "coverage_ratio": float(complete.mean()) if len(complete) else np.nan,
            "identity_max_abs_error": float(valid_identity.max()) if len(valid_identity) else np.nan,
            "chart": {
                "dates": [str(value) for value in dates],
                "series": [
                    {"name": "实际超额收益", "values": cumulative["actual_excess_return"].tolist()},
                    {"name": "Barra风格收益贡献", "values": cumulative["barra_style_return"].tolist()},
                    {"name": "纯Alpha收益", "values": cumulative["pure_alpha_return"].tolist()},
                ],
            },
        }
    )
