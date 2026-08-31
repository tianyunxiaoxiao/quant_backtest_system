"""收益、指标与 Alpha/Beta 单元测试。"""

import numpy as np
import pandas as pd
import pytest

from qbt.analytics.alphabeta import compute_alpha_beta, ols_with_newey_west
from qbt.analytics.metrics import compute_performance_stats
from qbt.analytics.returns import build_return_frame, drawdown_series
from qbt.analytics.style import REQUIRED_STYLES, compute_style_exposure


def test_drawdown_series():
    nav = pd.Series([1.0, 1.1, 1.05, 1.2, 1.1, 1.15], index=pd.date_range("2020-01-02", periods=6, freq="B"))
    dd = drawdown_series(nav)
    assert dd.iloc[0] == 0.0
    assert dd.min() < 0.0
    assert dd.iloc[-1] < 0.0  # 1.15 < 1.2 峰值


def test_build_return_frame():
    idx = pd.date_range("2020-01-02", periods=5, freq="B")
    ledger = pd.DataFrame(
        {
            "net_assets": [100.0, 101.0, 100.5, 102.0, 101.0],
            "trade_cost": [0.0, 0.1, 0.0, 0.2, 0.0],
        },
        index=idx,
    )
    bench = pd.Series([0.0, 0.005, 0.0, 0.01, -0.005], index=idx)
    frame = build_return_frame(ledger, bench)
    assert "portfolio_net_return" in frame.columns
    assert "portfolio_gross_return" in frame.columns
    assert "excess_return" in frame.columns
    assert "portfolio_nav" in frame.columns
    # 净收益 = (NAV_t - NAV_{t-1}) / NAV_{t-1}
    assert abs(frame["portfolio_net_return"].iloc[1] - 0.01) < 1e-9
    # 毛收益 = (NAV_t + cost_t - NAV_{t-1}) / NAV_{t-1}
    assert abs(frame["portfolio_gross_return"].iloc[1] - 0.011) < 1e-9
    expected_excess_nav = frame["portfolio_nav"] / frame["benchmark_nav"]
    pd.testing.assert_series_equal(
        frame["excess_nav"], expected_excess_nav.rename("excess_nav")
    )


def test_compute_performance_stats():
    idx = pd.date_range("2020-01-02", periods=252, freq="B")
    np.random.seed(0)
    net = pd.Series(np.random.normal(0.0003, 0.015, size=len(idx)), index=idx)
    frame = pd.DataFrame(
        {
            "portfolio_net_return": net,
            "portfolio_gross_return": net,
            "benchmark_return": pd.Series(0.0, index=idx),
            "excess_return": net,
            "trade_cost": pd.Series(0.0, index=idx),
            "n_holdings": pd.Series(30, index=idx),
            "cash_ratio": pd.Series(0.02, index=idx),
        }
    )
    stats = compute_performance_stats(frame, label="test")
    assert stats.label == "test"
    assert stats.n_days == 252
    assert np.isfinite(stats.annual_return)
    assert np.isfinite(stats.sharpe)


def test_period_win_rate_compounds_portfolio_and_benchmark_separately():
    idx = pd.DatetimeIndex(["2020-01-02", "2020-01-03"])
    net = pd.Series([-0.8, -0.1], index=idx)
    benchmark = pd.Series([-0.3, -0.8], index=idx)
    frame = pd.DataFrame(
        {
            "portfolio_net_return": net,
            "portfolio_gross_return": net,
            "benchmark_return": benchmark,
            "excess_return": net - benchmark,
            "trade_cost": 0.0,
        }
    )
    stats = compute_performance_stats(frame, label="period-win")
    # 组合月收益 -82%，基准 -86%，几何相对收益为正；逐日算术超额复利会误判。
    assert stats.win_rate_monthly == 1.0
    assert stats.win_rate_yearly == 1.0


def test_performance_excess_drawdown_uses_nav_ratio():
    idx = pd.date_range("2020-01-02", periods=4, freq="B")
    net = pd.Series([0.0, 0.10, -0.05, 0.02], index=idx)
    benchmark = pd.Series([0.0, 0.20, -0.02, 0.01], index=idx)
    frame = pd.DataFrame(
        {
            "portfolio_net_return": net,
            "portfolio_gross_return": net,
            "benchmark_return": benchmark,
            "excess_return": net - benchmark,
            "trade_cost": 0.0,
        }
    )
    stats = compute_performance_stats(frame, label="ratio")
    excess_nav = (1.0 + net).cumprod() / (1.0 + benchmark).cumprod()
    assert stats.excess_max_drawdown == pytest.approx(drawdown_series(excess_nav).min())


def test_alpha_beta_regression():
    np.random.seed(0)
    n = 252
    x = np.random.normal(0.0, 0.01, size=n)
    y = 0.0002 + 0.8 * x + np.random.normal(0.0, 0.005, size=n)
    idx = pd.date_range("2020-01-02", periods=n, freq="B")
    frame = pd.DataFrame(
        {
            "portfolio_net_return": pd.Series(y, index=idx),
            "benchmark_return": pd.Series(x, index=idx),
            "excess_return": pd.Series(y - x, index=idx),
        }
    )
    report = compute_alpha_beta(frame)
    assert abs(report.beta - 0.8) < 0.2
    assert report.n_observations == n
    assert "beta_contribution" in report.contributions.columns


def test_ols_newey_west_std_errors():
    np.random.seed(1)
    x = np.random.randn(100)
    y = 0.1 + 0.5 * x + np.random.randn(100)
    r = ols_with_newey_west(y, x, lags=5)
    assert np.isfinite(r.alpha)
    assert np.isfinite(r.beta)
    assert r.se_nw[0] >= r.se_ols[0] * 0.5  # NW 标准误通常更大或相近


def test_style_active_identity_and_missing_style_contract():
    dates = pd.date_range("2020-01-02", periods=3, freq="B")
    assets = ["A", "B"]
    portfolio = pd.DataFrame([[0.6, 0.4]] * 3, index=dates, columns=assets)
    index = pd.DataFrame([[0.5, 0.5]] * 3, index=dates, columns=assets)
    size = pd.DataFrame([[1.0, -1.0], [2.0, 0.0], [0.5, -0.5]], index=dates, columns=assets)
    report = compute_style_exposure(portfolio, index, {"size": size})

    pd.testing.assert_frame_equal(
        report.active_exposure,
        report.portfolio_exposure - report.index_exposure,
    )
    assert set(report.missing_styles) == set(REQUIRED_STYLES) - {"size"}
    assert report.portfolio_exposure[list(report.missing_styles)].isna().all().all()
    missing_coverage = report.coverage.set_index("style").loc[list(report.missing_styles)]
    assert not missing_coverage["is_available"].any()
