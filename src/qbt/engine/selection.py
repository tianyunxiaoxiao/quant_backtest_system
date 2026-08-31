"""选股层 (规范 6.4, 确认清单 B1 / B2 / B7)。

口径:
- 只在 T 日指数成分内选股 (PIT), 严禁全市场选股再回填成分。
- 排序用 T 日收盘已知的因子值; 因子缺失按 missing_policy 剔除, 不填 0 不填均值。
- 资格过滤只用 T 日收盘可知的状态 (已上市/未退市/未停牌), 涨跌停留到成交层 (B7)。
- 取前 selection_fraction, 数量 = ceil(合格数 * fraction), 与导师 B1 口径一致。
- 并列用 asset_id 升序打破, 保证可复现 (B2)。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

__all__ = ["select_daily", "SelectionResult"]


class SelectionResult:
    """选股结果: 布尔选中矩阵 + 排名 + 逐日诊断。"""

    __slots__ = ("selected", "rank", "diagnostics", "exclusion_reasons")

    def __init__(
        self,
        selected: pd.DataFrame,
        rank: pd.DataFrame,
        diagnostics: pd.DataFrame,
        exclusion_reasons: pd.DataFrame,
    ) -> None:
        self.selected = selected
        self.rank = rank
        self.diagnostics = diagnostics
        self.exclusion_reasons = exclusion_reasons


def select_daily(
    *,
    factor_values: pd.DataFrame,
    direction: int,
    index_universe: pd.DataFrame,
    ex_ante_tradable: pd.DataFrame,
    selection_fraction: float,
    min_holdings: int = 20,
    fail_on_insufficient_universe: bool = False,
    requires_tradable: bool = True,
    requires_valid_factor: bool = True,
) -> SelectionResult:
    """逐日横截面选股。返回选中矩阵与诊断。

    direction=+1 表示因子值越大越好, -1 表示越小越好。
    """
    if not 0.0 < selection_fraction <= 1.0:
        raise ValueError(f"selection_fraction 必须在 (0,1]: {selection_fraction}")

    dates = index_universe.index
    assets = index_universe.columns
    fv = factor_values.reindex(index=dates, columns=assets).astype("float64")
    if direction not in (1, -1):
        raise ValueError(f"direction 只能是 +1/-1: {direction}")
    score = fv * float(direction)

    in_index = index_universe.to_numpy(dtype=bool)
    tradable = ex_ante_tradable.reindex(index=dates, columns=assets).to_numpy(dtype=bool)
    valid_factor = np.isfinite(score.to_numpy())

    eligible = in_index.copy()
    if requires_tradable:
        eligible &= tradable
    if requires_valid_factor:
        eligible &= valid_factor

    score_arr = score.to_numpy()
    n_dates, n_assets = score_arr.shape
    selected = np.zeros((n_dates, n_assets), dtype=bool)
    rank_arr = np.full((n_dates, n_assets), np.nan, dtype="float64")

    # 并列打破: asset_id 升序 -> 列序即字典序 (assets 已排序)
    asset_order = np.arange(n_assets, dtype="float64")

    rows = []
    for i in range(n_dates):
        elig_i = eligible[i]
        n_elig = int(elig_i.sum())
        n_index = int(in_index[i].sum())
        n_target = math.ceil(n_elig * selection_fraction) if n_elig > 0 else 0
        if n_target > 0:
            idx = np.flatnonzero(elig_i)
            # 主键 -score 升序 (score 大在前), 次键 asset 序号升序
            order = np.lexsort((asset_order[idx], -score_arr[i, idx]))
            ranked = idx[order]
            rank_arr[i, ranked] = np.arange(1, len(ranked) + 1, dtype="float64")
            take = ranked[:n_target]
            selected[i, take] = True
        n_sel = int(selected[i].sum())
        insufficient = n_sel < min_holdings
        if insufficient and fail_on_insufficient_universe:
            raise ValueError(
                f"{dates[i].date()} 选中 {n_sel} 只, 低于 min_holdings={min_holdings}"
            )
        rows.append(
            {
                "date": dates[i],
                "n_index_members": n_index,
                "n_eligible": n_elig,
                "n_selected": n_sel,
                "n_target": n_target,
                "excluded_not_tradable": int((in_index[i] & ~tradable[i]).sum()),
                "excluded_invalid_factor": int((in_index[i] & ~valid_factor[i]).sum()),
                "excluded_both": int((in_index[i] & ~tradable[i] & ~valid_factor[i]).sum()),
                "eligible_ratio": (n_elig / n_index) if n_index else np.nan,
                "below_min_holdings": bool(insufficient),
            }
        )

    diagnostics = pd.DataFrame(rows).set_index("date")
    # 规范 7.1 要求未入选、因子缺失和不可交易原因逐资产可追溯。
    # 用分类列保存长表，避免真实数据下重复字符串造成不必要的内存膨胀。
    excluded = in_index & (~selected)
    row_pos, col_pos = np.nonzero(excluded)
    reason_names = (
        "not_tradable_and_invalid_factor",
        "not_tradable",
        "invalid_factor",
        "below_selection_cutoff",
    )
    if len(row_pos):
        not_tradable = requires_tradable & (~tradable[row_pos, col_pos])
        invalid = requires_valid_factor & (~valid_factor[row_pos, col_pos])
        reason_code = np.select(
            [not_tradable & invalid, not_tradable, invalid],
            [0, 1, 2],
            default=3,
        ).astype("int8")
        exclusion_reasons = pd.DataFrame(
            {
                "date": dates.take(row_pos),
                "asset_id": pd.Categorical.from_codes(col_pos, categories=assets),
                "reason": pd.Categorical.from_codes(reason_code, categories=reason_names),
            }
        )
    else:
        exclusion_reasons = pd.DataFrame(
            {
                "date": pd.Series(dtype="datetime64[ns]"),
                "asset_id": pd.Series(pd.Categorical([], categories=assets)),
                "reason": pd.Series(pd.Categorical([], categories=reason_names)),
            }
        )
    result_dates = dates.copy().rename("date")
    result_assets = assets.copy().rename("asset_id")
    return SelectionResult(
        selected=pd.DataFrame(selected, index=result_dates, columns=result_assets),
        rank=pd.DataFrame(rank_arr, index=result_dates, columns=result_assets),
        diagnostics=diagnostics,
        exclusion_reasons=exclusion_reasons,
    )
