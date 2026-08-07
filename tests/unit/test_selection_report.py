"""Frictionless diagnostic portfolio timing tests."""

import pandas as pd
import pytest

from qbt.analytics.selection_report import _simulate_frictionless


def test_diagnostic_portfolio_only_rebalances_on_configured_dates():
    dates = pd.date_range("2020-01-02", periods=6, freq="B")
    close = pd.DataFrame(
        {"A": [10, 11, 12, 13, 14, 15], "B": [10, 10, 10, 10, 10, 10]},
        index=dates,
        dtype="float64",
    )
    weights = pd.DataFrame(
        {"A": [1, 0, 0, 0, 0, 0], "B": [0, 1, 1, 1, 1, 1]},
        index=dates,
        dtype="float64",
    )

    _, actual_weights = _simulate_frictionless(
        weights,
        rebalance_dates=(dates[0],),
        adj_close=close,
        adj_fill_price=close,
        order_lag_days=1,
        fill_lag_days=0,
    )

    assert actual_weights.loc[dates[1], "A"] == 1.0
    assert (actual_weights.loc[dates[1]:, "B"] == 0.0).all()


def test_diagnostic_rebalance_day_includes_fill_to_close_return():
    dates = pd.date_range("2020-01-02", periods=3, freq="B")
    close = pd.DataFrame({"A": [10.0, 12.0, 12.0]}, index=dates)
    fill = pd.DataFrame({"A": [10.0, 10.0, 12.0]}, index=dates)
    weights = pd.DataFrame({"A": [1.0, 1.0, 1.0]}, index=dates)

    returns, _ = _simulate_frictionless(
        weights,
        rebalance_dates=(dates[0],),
        adj_close=close,
        adj_fill_price=fill,
        order_lag_days=1,
        fill_lag_days=0,
    )

    assert returns.loc[dates[1]] == pytest.approx(0.2)
