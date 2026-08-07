"""选股与权重单元测试。"""

import numpy as np
import pandas as pd
import pytest

from qbt.engine.selection import select_daily
from qbt.engine.weighting import build_target_weights


def test_select_top30_percent(small_factor, small_universe, small_tradability):
    res = select_daily(
        factor_values=small_factor.values,
        direction=1,
        index_universe=small_universe,
        ex_ante_tradable=small_tradability.ex_ante_tradable,
        selection_fraction=0.30,
        min_holdings=1,
    )
    # 3 只成分、全部可交易: ceil(3*0.3)=1
    assert res.selected.shape == small_universe.shape
    assert res.selected.sum(axis=1).iloc[0] == 1
    # 排名最高的那只被选中
    scores = small_factor.oriented.iloc[0]
    top_asset = scores.idxmax()
    assert res.selected.iloc[0][top_asset]


def test_selection_direction_minus_one(small_factor, small_universe, small_tradability):
    res = select_daily(
        factor_values=small_factor.values,
        direction=-1,
        index_universe=small_universe,
        ex_ante_tradable=small_tradability.ex_ante_tradable,
        selection_fraction=0.30,
        min_holdings=1,
    )
    scores = (-small_factor.values).iloc[0]
    top_asset = scores.idxmax()
    assert res.selected.iloc[0][top_asset]


def test_select_excludes_not_tradable(small_factor, small_universe, small_tradability):
    # 把第一只票停牌
    tradable = small_tradability.ex_ante_tradable.copy()
    tradable.iloc[0, 0] = False
    res = select_daily(
        factor_values=small_factor.values,
        direction=1,
        index_universe=small_universe,
        ex_ante_tradable=tradable,
        selection_fraction=0.30,
        min_holdings=1,
    )
    assert not res.selected.iloc[0, 0]


def test_weighting_strength_positive(small_factor, small_universe, small_tradability):
    sel = select_daily(
        factor_values=small_factor.values,
        direction=1,
        index_universe=small_universe,
        ex_ante_tradable=small_tradability.ex_ante_tradable,
        selection_fraction=0.30,
        min_holdings=1,
    )
    w = build_target_weights(
        scores=small_factor.oriented,
        selected=sel.selected,
        rank=sel.rank,
        method="factor_strength",
        max_weight=1.0,
        cash_buffer=0.0,
    )
    row = w.target_weights.iloc[0]
    assert abs(row.sum() - 1.0) < 1e-9
    assert (row >= 0).all()


def test_weighting_equal_weight_fallback(small_factor, small_universe, small_tradability):
    # 让所有入选股分数相同 -> 强度为 0 -> 退回等权
    scores = pd.DataFrame(1.0, index=small_factor.values.index, columns=small_factor.values.columns)
    sel = select_daily(
        factor_values=scores,
        direction=1,
        index_universe=small_universe,
        ex_ante_tradable=small_tradability.ex_ante_tradable,
        selection_fraction=0.30,
        min_holdings=1,
    )
    w = build_target_weights(
        scores=scores,
        selected=sel.selected,
        rank=sel.rank,
        method="factor_strength",
        max_weight=0.5,
        cash_buffer=0.0,
    )
    # 第一天 3 只入选 1 只, 等权就是 1.0
    assert w.diagnostics.iloc[0]["used_equal_weight"]


def test_weighting_index_weight_renormalizes_selected_members():
    dates = pd.date_range("2020-01-02", periods=2, freq="B")
    assets = ["A", "B", "C"]
    selected = pd.DataFrame([[True, True, False], [True, True, False]], index=dates, columns=assets)
    scores = pd.DataFrame([[3.0, 2.0, 1.0], [3.0, 2.0, 1.0]], index=dates, columns=assets)
    rank = pd.DataFrame([[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]], index=dates, columns=assets)
    index_weights = pd.DataFrame([[0.6, 0.3, 0.1], [np.nan, np.nan, 1.0]], index=dates, columns=assets)

    result = build_target_weights(
        scores=scores,
        selected=selected,
        rank=rank,
        index_weights=index_weights,
        method="index_weight",
        max_weight=1.0,
        cash_buffer=0.0,
    )

    assert result.target_weights.loc[dates[0], "A"] == pytest.approx(2 / 3)
    assert result.target_weights.loc[dates[0], "B"] == pytest.approx(1 / 3)
    assert result.target_weights.loc[dates[1], "A"] == pytest.approx(0.5)
    assert result.target_weights.loc[dates[1], "B"] == pytest.approx(0.5)
    assert bool(result.diagnostics.loc[dates[1], "used_equal_weight"])
