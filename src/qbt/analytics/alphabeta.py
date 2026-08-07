"""Alpha/Beta 拆分 (规范第 10 节)。

R_p,t - rf = alpha + beta * (R_index,t - rf) + eps_t

t 值同时给 OLS 和 Newey-West 两个口径 (确认清单 F1): 日频残差有自相关,
只报 OLS t 值会高估显著性。
"""
from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pandas as pd
from scipy import stats

from qbt.contracts.config import RegressionConfig
from qbt.contracts.reports import AlphaBetaReport

__all__ = ["OLSResult", "ols_with_newey_west", "compute_alpha_beta"]


class OLSResult(NamedTuple):
    alpha: float
    beta: float
    se_ols: tuple[float, float]
    se_nw: tuple[float, float]
    r_squared: float
    residual_std: float
    n: int
    residuals: np.ndarray


def ols_with_newey_west(y: np.ndarray, x: np.ndarray, *, lags: int = 5) -> OLSResult:
    """一元 OLS + Newey-West (Bartlett 核) 异方差自相关稳健标准误。"""
    y = np.asarray(y, dtype="float64")
    x = np.asarray(x, dtype="float64")
    ok = np.isfinite(y) & np.isfinite(x)
    y, x = y[ok], x[ok]
    n = y.size
    if n < 3:
        nan = float("nan")
        return OLSResult(nan, nan, (nan, nan), (nan, nan), nan, nan, n, np.array([]))

    X = np.column_stack([np.ones(n), x])
    XtX_inv = np.linalg.pinv(X.T @ X)
    coef = XtX_inv @ (X.T @ y)
    resid = y - X @ coef
    dof = max(n - 2, 1)
    sigma2 = float(resid @ resid) / dof

    # 经典 OLS 标准误
    cov_ols = sigma2 * XtX_inv
    se_ols = np.sqrt(np.maximum(np.diag(cov_ols), 0.0))

    # Newey-West: S = S_0 + sum_{l=1..L} w_l (S_l + S_l')
    u = X * resid[:, None]
    S = u.T @ u
    L = max(int(lags), 0)
    for lag in range(1, min(L, n - 1) + 1):
        w = 1.0 - lag / (L + 1.0)
        G = u[lag:].T @ u[:-lag]
        S += w * (G + G.T)
    cov_nw = XtX_inv @ S @ XtX_inv * (n / dof)
    se_nw = np.sqrt(np.maximum(np.diag(cov_nw), 0.0))

    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = float(1.0 - (resid @ resid) / ss_tot) if ss_tot > 0 else float("nan")
    return OLSResult(
        alpha=float(coef[0]),
        beta=float(coef[1]),
        se_ols=(float(se_ols[0]), float(se_ols[1])),
        se_nw=(float(se_nw[0]), float(se_nw[1])),
        r_squared=r2,
        residual_std=float(np.sqrt(sigma2)),
        n=n,
        residuals=resid,
    )


def _t_and_p(coef: float, se: float, dof: int) -> tuple[float, float]:
    if not np.isfinite(se) or se <= 0 or dof <= 0:
        return float("nan"), float("nan")
    t = coef / se
    p = float(2.0 * stats.t.sf(abs(t), dof))
    return float(t), p


def _rolling(
    y: pd.Series, x: pd.Series, window: int, min_obs: int, lags: int, ppy: int
) -> pd.DataFrame:
    """滚动 alpha/beta。窗口内有效观测不足 min_obs 时留 NaN, 不缩窗硬凑。"""
    idx = y.index
    cols = {k: np.full(len(idx), np.nan) for k in
            ("rolling_beta", "rolling_alpha_daily", "rolling_alpha_annual",
             "rolling_r_squared", "rolling_alpha_tstat_nw", "rolling_n_obs")}
    yv, xv = y.to_numpy("float64"), x.to_numpy("float64")
    for i in range(len(idx)):
        s = i - window + 1
        if s < 0:
            continue
        wy, wx = yv[s : i + 1], xv[s : i + 1]
        if int((np.isfinite(wy) & np.isfinite(wx)).sum()) < min_obs:
            continue
        r = ols_with_newey_west(wy, wx, lags=lags)
        cols["rolling_beta"][i] = r.beta
        cols["rolling_alpha_daily"][i] = r.alpha
        cols["rolling_alpha_annual"][i] = (1.0 + r.alpha) ** ppy - 1.0
        cols["rolling_r_squared"][i] = r.r_squared
        cols["rolling_alpha_tstat_nw"][i] = _t_and_p(r.alpha, r.se_nw[0], r.n - 2)[0]
        cols["rolling_n_obs"][i] = r.n
    out = pd.DataFrame(cols, index=idx)
    out.index.name = "date"
    return out


def compute_alpha_beta(
    frame: pd.DataFrame,
    *,
    config: RegressionConfig | None = None,
    samples: dict[str, pd.DataFrame] | None = None,
) -> AlphaBetaReport:
    """对 build_return_frame 的输出做 Alpha/Beta 回归与收益拆分。"""
    cfg = config or RegressionConfig()
    ppy = int(cfg.trading_days_per_year)
    rf_daily = float(cfg.risk_free_annual) / ppy

    y = (frame["portfolio_net_return"].astype("float64") - rf_daily).rename("y")
    x = (frame["benchmark_return"].astype("float64") - rf_daily).rename("x")

    r = ols_with_newey_west(y.to_numpy(), x.to_numpy(), lags=cfg.newey_west_lags)
    dof = max(r.n - 2, 1)
    a_t_ols, a_p_ols = _t_and_p(r.alpha, r.se_ols[0], dof)
    a_t_nw, a_p_nw = _t_and_p(r.alpha, r.se_nw[0], dof)
    b_t_ols, _ = _t_and_p(r.beta, r.se_ols[1], dof)
    b_t_nw, _ = _t_and_p(r.beta, r.se_nw[1], dof)

    # 收益拆分 (规范 10)
    beta_contrib = (r.beta * x).rename("beta_contribution")
    alpha_contrib = (y - beta_contrib).rename("alpha_residual_contribution")
    contributions = pd.DataFrame(
        {
            "portfolio_excess_over_rf": y,
            "benchmark_excess_over_rf": x,
            "beta_contribution": beta_contrib,
            "alpha_residual_contribution": alpha_contrib,
            "beta_contribution_cum": (1.0 + beta_contrib).cumprod() - 1.0,
            "alpha_contribution_cum": (1.0 + alpha_contrib).cumprod() - 1.0,
        }
    )
    contributions.index.name = "date"

    by_sample: dict[str, dict[str, float]] = {}
    for name, sub in (samples or {}).items():
        if sub is None or len(sub) < max(3, cfg.min_observations // 4):
            continue
        sy = sub["portfolio_net_return"].astype("float64") - rf_daily
        sx = sub["benchmark_return"].astype("float64") - rf_daily
        sr = ols_with_newey_west(sy.to_numpy(), sx.to_numpy(), lags=cfg.newey_west_lags)
        sdof = max(sr.n - 2, 1)
        by_sample[name] = {
            "alpha_daily": sr.alpha,
            "alpha_annual": (1.0 + sr.alpha) ** ppy - 1.0,
            "beta": sr.beta,
            "alpha_tstat_nw": _t_and_p(sr.alpha, sr.se_nw[0], sdof)[0],
            "alpha_tstat_ols": _t_and_p(sr.alpha, sr.se_ols[0], sdof)[0],
            "r_squared": sr.r_squared,
            "residual_volatility_annual": sr.residual_std * np.sqrt(ppy),
            "n_observations": float(sr.n),
        }

    return AlphaBetaReport(
        alpha_daily=r.alpha,
        alpha_annual=float((1.0 + r.alpha) ** ppy - 1.0),
        beta=r.beta,
        alpha_tstat_ols=a_t_ols,
        alpha_tstat_nw=a_t_nw,
        alpha_pvalue_ols=a_p_ols,
        alpha_pvalue_nw=a_p_nw,
        beta_tstat_ols=b_t_ols,
        beta_tstat_nw=b_t_nw,
        r_squared=r.r_squared,
        residual_volatility_annual=float(r.residual_std * np.sqrt(ppy)),
        n_observations=int(r.n),
        rolling=_rolling(y, x, int(cfg.rolling_window), int(cfg.min_observations),
                         int(cfg.newey_west_lags), ppy),
        contributions=contributions,
        beta_contribution_total=float((1.0 + beta_contrib).prod() - 1.0),
        alpha_contribution_total=float((1.0 + alpha_contrib).prod() - 1.0),
        by_sample=by_sample,
        config={
            "risk_free_annual": cfg.risk_free_annual,
            "trading_days_per_year": ppy,
            "rolling_window": cfg.rolling_window,
            "min_observations": cfg.min_observations,
            "newey_west_lags": cfg.newey_west_lags,
        },
    )
