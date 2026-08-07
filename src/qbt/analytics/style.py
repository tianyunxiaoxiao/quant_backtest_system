"""风格暴露分析 (规范第 11 节)。

组合暴露 = sum(实际权重_i * 暴露_i)
指数暴露 = sum(指数权重_i * 暴露_i)
主动暴露 = 组合暴露 - 指数暴露

导师 A4: v1 用价格/估值数据自建简化代理 (Size/Value/Momentum/Volatility/
Liquidity), Growth/Quality/Leverage 缺财务数据, 按规范标记缺失, 不硬凑。
没有 PIT 风格数据时标记缺失, 绝不用最新暴露回填历史。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from qbt.contracts.reports import StyleExposureReport

__all__ = ["compute_style_exposure", "REQUIRED_STYLES"]

# 规范要求的完整风格集; 缺的显式标记, 不静默省略
REQUIRED_STYLES = (
    "size", "value", "momentum", "volatility", "liquidity",
    "growth", "quality", "leverage",
)


def _weighted_exposure(
    weights: pd.DataFrame, exposure: pd.DataFrame
) -> tuple[pd.Series, pd.Series]:
    """按行做加权平均, 同时返回权重覆盖率。

    只在暴露非缺失的股票上归一化: 覆盖率低时暴露仍可比, 但覆盖率必须报出去,
    否则"用 60% 权重算出来的暴露"会被当成全组合暴露读。
    """
    w = weights.to_numpy(dtype="float64")
    e = exposure.to_numpy(dtype="float64")
    valid = np.isfinite(e) & np.isfinite(w) & (w != 0.0)
    w_valid = np.where(valid, w, 0.0)
    denom = w_valid.sum(axis=1)
    num = np.where(valid, w_valid * np.nan_to_num(e), 0.0).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        expo = np.where(denom > 0, num / denom, np.nan)
    total_w = np.where(np.isfinite(w), np.abs(w), 0.0).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = np.where(total_w > 0, denom / total_w, np.nan)
    return (
        pd.Series(expo, index=weights.index),
        pd.Series(cov, index=weights.index),
    )


def compute_style_exposure(
    actual_weights: pd.DataFrame,
    index_weights: pd.DataFrame,
    style_panels: dict[str, pd.DataFrame],
    *,
    excess_returns: pd.Series | None = None,
    data_source: str = "proxy_from_price_and_valuation",
) -> StyleExposureReport:
    """逐日计算组合/指数/主动风格暴露。

    参数
    ----
    actual_weights : 实际成交后的组合权重 (date x asset)。规范要求用实际权重,
        不是目标权重。
    index_weights : 指数成分权重 (date x asset)。
    style_panels : {风格名: (date x asset) 暴露面板}。
    excess_returns : 组合超额收益, 用于算暴露与超额的关系。
    """
    dates = actual_weights.index
    present = [s for s in REQUIRED_STYLES if s in style_panels]
    missing = tuple(s for s in REQUIRED_STYLES if s not in style_panels)

    pf_cols: dict[str, pd.Series] = {}
    ix_cols: dict[str, pd.Series] = {}
    cov_rows: list[dict] = []

    for style in present:
        panel = style_panels[style].reindex(index=dates, columns=actual_weights.columns)
        pf_e, pf_c = _weighted_exposure(actual_weights, panel)
        ix_panel = panel.reindex(index=dates, columns=index_weights.columns)
        ix_e, ix_c = _weighted_exposure(index_weights.reindex(index=dates), ix_panel)
        pf_cols[style] = pf_e
        ix_cols[style] = ix_e
        cov_rows.append(
            {
                "style": style,
                "portfolio_weight_coverage_mean": float(np.nanmean(pf_c.to_numpy()))
                if pf_c.notna().any() else np.nan,
                "portfolio_weight_coverage_min": float(np.nanmin(pf_c.to_numpy()))
                if pf_c.notna().any() else np.nan,
                "index_weight_coverage_mean": float(np.nanmean(ix_c.to_numpy())),
                "exposure_missing_ratio": float(pf_e.isna().mean()),
                "is_available": True,
            }
        )

    for style in missing:
        # 规范 11: 缺失必须标记, 不能回填
        pf_cols[style] = pd.Series(np.nan, index=dates)
        ix_cols[style] = pd.Series(np.nan, index=dates)
        cov_rows.append(
            {
                "style": style,
                "portfolio_weight_coverage_mean": np.nan,
                "portfolio_weight_coverage_min": np.nan,
                "index_weight_coverage_mean": np.nan,
                "exposure_missing_ratio": 1.0,
                "is_available": False,
            }
        )

    order = list(REQUIRED_STYLES)
    pf = pd.DataFrame(pf_cols).reindex(columns=order)
    ix = pd.DataFrame(ix_cols).reindex(columns=order)
    active = pf - ix
    for df in (pf, ix, active):
        df.index.name = "date"

    summary = pd.DataFrame(
        {
            "style": order,
            "portfolio_mean": [pf[s].mean() for s in order],
            "index_mean": [ix[s].mean() for s in order],
            "active_mean": [active[s].mean() for s in order],
            "active_std": [active[s].std(ddof=1) for s in order],
            "active_max_abs": [active[s].abs().max() for s in order],
            "active_latest": [
                active[s].dropna().iloc[-1] if active[s].notna().any() else np.nan
                for s in order
            ],
            "missing_ratio": [active[s].isna().mean() for s in order],
        }
    )

    rel_rows: list[dict] = []
    if excess_returns is not None and not excess_returns.empty:
        ex = excess_returns.reindex(dates).astype("float64")
        for s in order:
            a = active[s]
            both = a.notna() & ex.notna()
            n = int(both.sum())
            if n < 30:
                rel_rows.append({"style": s, "n_obs": n, "corr_active_vs_excess": np.nan,
                                 "corr_lag1_active_vs_excess": np.nan,
                                 "mean_excess_high_exposure": np.nan,
                                 "mean_excess_low_exposure": np.nan})
                continue
            av, ev = a[both], ex[both]
            if float(av.std(ddof=1) or 0.0) <= 0 or float(ev.std(ddof=1) or 0.0) <= 0:
                # 暴露或收益方差为 0 时相关系数无定义, 明确留 NaN 而不是报 0
                rel_rows.append({"style": s, "n_obs": n,
                                 "corr_active_vs_excess": np.nan,
                                 "corr_lag1_active_vs_excess": np.nan,
                                 "mean_excess_high_exposure": float(ev.mean()),
                                 "mean_excess_low_exposure": np.nan})
                continue
            # 同期相关 + 滞后一期 (暴露在前, 收益在后), 后者更接近"暴露解释收益"
            lag = a.shift(1)[both].astype("float64")
            lag_ok = lag.notna()
            hi = av >= av.median()
            rel_rows.append(
                {
                    "style": s,
                    "n_obs": n,
                    "corr_active_vs_excess": float(np.corrcoef(av, ev)[0, 1]),
                    "corr_lag1_active_vs_excess": float(
                        np.corrcoef(lag[lag_ok], ev[lag_ok])[0, 1]
                    ) if int(lag_ok.sum()) >= 30 else np.nan,
                    "mean_excess_high_exposure": float(ev[hi].mean()),
                    "mean_excess_low_exposure": float(ev[~hi].mean()),
                }
            )
    relation = pd.DataFrame(rel_rows)

    return StyleExposureReport(
        portfolio_exposure=pf,
        index_exposure=ix,
        active_exposure=active,
        summary=summary,
        coverage=pd.DataFrame(cov_rows),
        excess_return_relation=relation,
        missing_styles=missing,
        data_source=data_source,
    )
