"""风格暴露代理 (规范 6.6, 确认清单 A4 导师已确认口径)。

明确声明: 这不是 Barra, 是用现有价量与估值字段自建的简化代理。
    Size       = ln(A股流通市值)
    Value      = 1 / PB
    Momentum   = 过去 252 日收益, 剔除最近 21 日
    Volatility = 过去 252 日日收益标准差
    Liquidity  = 过去 21 日平均换手率
    Growth / Quality / Leverage = 缺财务数据, 按规范标记缺失

每日横截面 z-score, 先 ±3σ 缩尾再标准化。所有窗口只用 t 日及之前的数据。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["STYLE_NAMES", "MISSING_STYLES", "build_style_exposures", "cross_section_zscore"]

STYLE_NAMES = ("Size", "Value", "Momentum", "Volatility", "Liquidity")
MISSING_STYLES = ("Growth", "Quality", "Leverage")


def cross_section_zscore(df: pd.DataFrame, *, clip: float = 3.0) -> pd.DataFrame:
    """逐日横截面标准化: 先缩尾到 ±clip σ, 再重新标准化。"""
    x = df.astype("float64")
    mu = x.mean(axis=1)
    sd = x.std(axis=1, ddof=0)
    z = x.sub(mu, axis=0).div(sd.where(sd > 0), axis=0)
    z = z.clip(lower=-clip, upper=clip)
    mu2 = z.mean(axis=1)
    sd2 = z.std(axis=1, ddof=0)
    return z.sub(mu2, axis=0).div(sd2.where(sd2 > 0), axis=0)


def build_style_exposures(
    *,
    adj_close: pd.DataFrame,
    float_mktcap: pd.DataFrame,
    pb: pd.DataFrame,
    turnover_rate: pd.DataFrame,
    valid_mask: pd.DataFrame | None = None,
    momentum_window: int = 252,
    momentum_skip: int = 21,
    volatility_window: int = 252,
    liquidity_window: int = 21,
    min_periods_ratio: float = 0.6,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """返回 (风格暴露字典, 覆盖率表)。缺失风格不进字典, 由调用方标记。"""
    ret = adj_close.pct_change(fill_method=None)

    size_raw = np.log(float_mktcap.where(float_mktcap > 0))

    pb_pos = pb.where(pb > 0)
    value_raw = 1.0 / pb_pos

    mom_min = max(int(momentum_window * min_periods_ratio), 60)
    log_ret = np.log1p(ret.where(ret > -0.999))
    cum = log_ret.rolling(momentum_window - momentum_skip, min_periods=mom_min).sum()
    momentum_raw = cum.shift(momentum_skip)

    vol_min = max(int(volatility_window * min_periods_ratio), 60)
    volatility_raw = ret.rolling(volatility_window, min_periods=vol_min).std(ddof=1)

    liq_min = max(int(liquidity_window * min_periods_ratio), 5)
    liquidity_raw = turnover_rate.rolling(liquidity_window, min_periods=liq_min).mean()

    raw = {
        "Size": size_raw,
        "Value": value_raw,
        "Momentum": momentum_raw,
        "Volatility": volatility_raw,
        "Liquidity": liquidity_raw,
    }

    exposures: dict[str, pd.DataFrame] = {}
    coverage_rows = []
    for name, mat in raw.items():
        m = mat.replace([np.inf, -np.inf], np.nan)
        if valid_mask is not None:
            m = m.where(valid_mask)
        z = cross_section_zscore(m)
        exposures[name] = z.astype("float32")
        denom = valid_mask.sum(axis=1) if valid_mask is not None else pd.Series(
            m.shape[1], index=m.index
        )
        coverage_rows.append(
            pd.DataFrame(
                {
                    "style": name,
                    "n_valid": z.notna().sum(axis=1),
                    "n_universe": denom,
                }
            )
        )
    coverage = pd.concat(coverage_rows)
    coverage["coverage"] = coverage["n_valid"] / coverage["n_universe"].where(
        coverage["n_universe"] > 0
    )
    coverage = coverage.reset_index().rename(columns={"index": "date"})
    return exposures, coverage
