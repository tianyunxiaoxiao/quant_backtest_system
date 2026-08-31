"""目标权重层 (规范 7.2 / 7.3, 确认清单 C2 / C4 / C5)。

强度加权:
    strength_i = max(score_i - cutoff, 0)
    target_weight_i = strength_i / sum(strength) * (1 - cash_buffer)

cutoff 取"第一只落选股"的分数 (最高的未入选分, 导师 C2 确认)。
这样所有入选股强度都 > 0, 不会出现边界那只票权重恒为 0 的问题。
若当日全部入选股都在成分内且无落选股 (fraction=1), cutoff 退回入选股最小分再减一个极小量。

单票上限用迭代再分配: 超限票钉在上限, 剩余权重在未超限票间按强度重新归一, 直到收敛。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["build_target_weights", "WeightingResult"]

_EPS = 1e-12


class WeightingResult:
    __slots__ = ("target_weights", "diagnostics")

    def __init__(self, target_weights: pd.DataFrame, diagnostics: pd.DataFrame) -> None:
        self.target_weights = target_weights
        self.diagnostics = diagnostics


def _cap_redistribute(w: np.ndarray, cap: float, budget: float) -> tuple[np.ndarray, int]:
    """把权重向量按单票上限迭代再分配, 总和收敛到 budget。返回 (权重, 触顶只数)。"""
    n = len(w)
    if n == 0:
        return w, 0
    if cap * n < budget - 1e-12:
        # 上限乘持股数撑不到目标总额: 全部钉在上限, 余下留现金 (报告里会体现)
        return np.full(n, cap), n
    w = w.astype("float64", copy=True)
    total = w.sum()
    if total <= _EPS:
        return w, 0
    w *= budget / total
    free = np.ones(n, dtype=bool)
    for _ in range(64):
        over = free & (w > cap + 1e-15)
        if not over.any():
            break
        w[over] = cap
        free &= ~over
        if not free.any():
            break
        remaining = budget - cap * (~free).sum()
        pool = w[free].sum()
        if remaining <= 0:
            w[free] = 0.0
            break
        if pool <= _EPS:
            w[free] = remaining / free.sum()
        else:
            w[free] *= remaining / pool
    return w, int((w >= cap - 1e-12).sum())


def build_target_weights(
    *,
    scores: pd.DataFrame,
    selected: pd.DataFrame,
    rank: pd.DataFrame,
    eligible_scores: pd.DataFrame | None = None,
    index_weights: pd.DataFrame | None = None,
    method: str = "factor_strength",
    max_weight: float = 0.05,
    cash_buffer: float = 0.01,
    allow_equal_weight_fallback: bool = True,
    min_holdings: int = 20,
) -> WeightingResult:
    """逐日构造目标权重。

    scores 必须是"方向已修正"的分数 (越大越好), 与 selection 层同一口径。
    eligible_scores 为合格但未入选股的分数矩阵 (用于取 cutoff); 传 None 时
    从 rank 推断: rank 非 nan 即合格。
    """
    if method not in ("factor_strength", "equal_weight", "index_weight"):
        raise ValueError(f"未知 weighting method: {method}")
    if not 0.0 <= cash_buffer < 1.0:
        raise ValueError(f"cash_buffer 必须在 [0,1): {cash_buffer}")
    if max_weight <= 0:
        raise ValueError(f"max_weight 必须 > 0: {max_weight}")

    dates, assets = selected.index, selected.columns
    sc = scores.reindex(index=dates, columns=assets).to_numpy(dtype="float64")
    sel = selected.to_numpy(dtype=bool)
    rk = rank.reindex(index=dates, columns=assets).to_numpy(dtype="float64")
    budget = 1.0 - cash_buffer
    iw_values = (
        index_weights.reindex(index=dates, columns=assets).to_numpy(dtype="float64")
        if method == "index_weight" and index_weights is not None
        else None
    )

    out = np.zeros_like(sc)
    rows = []
    for i in range(len(dates)):
        sel_i = np.flatnonzero(sel[i])
        n_sel = len(sel_i)
        if n_sel == 0:
            rows.append(
                {"date": dates[i], "n_holdings": 0, "cutoff": np.nan, "sum_strength": 0.0,
                 "used_equal_weight": False, "n_at_cap": 0, "max_weight": 0.0,
                 "weight_sum": 0.0, "cash_target": 1.0, "capacity_shortfall": True}
            )
            continue
        # cutoff = 第一只落选股的分数 (合格但 rank 超出入选数)
        elig_mask = np.isfinite(rk[i])
        rejected = elig_mask & ~sel[i]
        if rejected.any():
            cutoff = float(np.nanmax(sc[i][rejected]))
        else:
            lo = float(np.nanmin(sc[i][sel_i]))
            span = float(np.nanmax(sc[i][sel_i])) - lo
            cutoff = lo - (abs(span) * 1e-6 if span > 0 else max(abs(lo), 1.0) * 1e-6)

        if method == "index_weight":
            if iw_values is None:
                raise ValueError("index_weight 方法需要 index_weights")
            iw = iw_values[i, sel_i]
            strength = np.where(np.isfinite(iw) & (iw > 0), iw, 0.0)
            used_eq = False
            if strength.sum() <= _EPS:
                if not allow_equal_weight_fallback:
                    raise ValueError(
                        f"{dates[i].date()} 入选股票无有效指数权重且未允许等权兜底"
                    )
                strength = np.ones(n_sel)
                used_eq = True
        elif method == "equal_weight":
            strength = np.ones(n_sel)
            used_eq = True
        else:
            strength = np.maximum(sc[i][sel_i] - cutoff, 0.0)
            used_eq = False
            if strength.sum() <= _EPS:
                if not allow_equal_weight_fallback:
                    raise ValueError(
                        f"{dates[i].date()} 强度总和为 0 且未允许等权兜底"
                    )
                strength = np.ones(n_sel)
                used_eq = True

        w, n_at_cap = _cap_redistribute(strength, max_weight, budget)
        out[i, sel_i] = w
        wsum = float(w.sum())
        rows.append(
            {
                "date": dates[i],
                "n_holdings": n_sel,
                "cutoff": cutoff,
                "sum_strength": float(strength.sum()),
                "used_equal_weight": used_eq,
                "n_at_cap": n_at_cap,
                "max_weight": float(w.max()) if n_sel else 0.0,
                "weight_sum": wsum,
                "cash_target": 1.0 - wsum,
                "capacity_shortfall": bool(wsum < budget - 1e-9),
                "below_min_holdings": bool(n_sel < min_holdings),
            }
        )

    return WeightingResult(
        target_weights=pd.DataFrame(
            out,
            index=dates.copy().rename("date"),
            columns=assets.copy().rename("asset_id"),
        ),
        diagnostics=pd.DataFrame(rows).set_index("date"),
    )
