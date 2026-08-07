"""分析报告契约与冻结回测结果 (规范 13 / 10 / 11 / 12 / 14.2)。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd

from .records import FillRecord, OrderRecord, RunManifest

__all__ = [
    "PerformanceStats",
    "PortfolioPerformanceReport",
    "AlphaBetaReport",
    "StyleExposureReport",
    "IndexSelectionReport",
    "PortfolioConstraintReport",
    "PortfolioBacktestDiagnostics",
    "LongOnlyFactorBacktestResult",
]


@dataclass(frozen=True)
class PerformanceStats:
    """单一样本区间的绩效指标 (规范 13)。"""

    label: str
    start_date: str
    end_date: str
    n_days: int
    total_return: float
    annual_return: float
    annual_volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    max_drawdown_start: str
    max_drawdown_trough: str
    max_drawdown_recovery: str
    max_drawdown_duration_days: int
    max_drawdown_recovery_days: int
    calmar: float
    benchmark_total_return: float
    benchmark_annual_return: float
    excess_total_return_geometric: float
    excess_annual_return_geometric: float
    excess_annual_return_arithmetic: float
    tracking_error: float
    information_ratio: float
    excess_max_drawdown: float
    win_rate_daily: float
    win_rate_monthly: float
    win_rate_yearly: float
    gross_annual_return: float
    turnover_annual_oneway: float
    total_cost: float
    cost_erosion_ratio: float
    avg_holdings: float
    avg_top10_concentration: float
    avg_cash_ratio: float
    hhi: float


@dataclass(frozen=True)
class PortfolioPerformanceReport:
    full_sample: PerformanceStats
    in_sample: PerformanceStats | None
    out_of_sample: PerformanceStats | None
    yearly: pd.DataFrame
    monthly: pd.DataFrame
    rolling: pd.DataFrame
    drawdown_table: pd.DataFrame
    definitions: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AlphaBetaReport:
    """规范 10。ols/nw 双口径 t 值同时输出 (确认清单 F1)。"""

    alpha_daily: float
    alpha_annual: float
    beta: float
    alpha_tstat_ols: float
    alpha_tstat_nw: float
    alpha_pvalue_ols: float
    alpha_pvalue_nw: float
    beta_tstat_ols: float
    beta_tstat_nw: float
    r_squared: float
    residual_volatility_annual: float
    n_observations: int
    rolling: pd.DataFrame
    contributions: pd.DataFrame
    beta_contribution_total: float
    alpha_contribution_total: float
    by_sample: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StyleExposureReport:
    """规范 11。主动暴露 = 组合暴露 - 指数暴露。"""

    portfolio_exposure: pd.DataFrame
    index_exposure: pd.DataFrame
    active_exposure: pd.DataFrame
    summary: pd.DataFrame
    coverage: pd.DataFrame
    excess_return_relation: pd.DataFrame
    missing_styles: tuple[str, ...] = ()
    data_source: str = "proxy_from_price_and_valuation"


@dataclass(frozen=True)
class IndexSelectionReport:
    """规范 12 指数内多头选股表现。"""

    daily: pd.DataFrame
    yearly: pd.DataFrame
    by_sample: pd.DataFrame
    diagnostic_equal_weight_returns: pd.Series
    diagnostic_target_weight_returns: pd.Series
    notes: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PortfolioConstraintReport:
    constraint: str
    enabled: bool
    limit: float | None
    n_checked: int
    n_violations: int
    max_observed: float
    action: str
    violations: pd.DataFrame = field(default_factory=pd.DataFrame)


@dataclass(frozen=True)
class PortfolioBacktestDiagnostics:
    timeline: Mapping[str, Any]
    data_quality: Mapping[str, Any]
    exclusion_reasons: pd.DataFrame
    unfilled_summary: pd.DataFrame
    accounting_identity: pd.DataFrame
    warnings: tuple[str, ...] = ()
    disclosures: tuple[str, ...] = ()


@dataclass(frozen=True)
class LongOnlyFactorBacktestResult:
    """回测器与报告器之间唯一的业务数据契约 (规范 14.2)。"""

    run_manifest: RunManifest
    selected_members: pd.DataFrame
    target_weights: pd.DataFrame
    actual_weights: pd.DataFrame
    orders: tuple[OrderRecord, ...]
    fills: tuple[FillRecord, ...]
    holdings: pd.DataFrame
    cash_ledger: pd.DataFrame
    gross_returns: pd.Series
    net_returns: pd.Series
    benchmark_returns: pd.Series
    excess_returns: pd.Series
    portfolio_equity: pd.Series
    benchmark_equity: pd.Series
    excess_equity: pd.Series
    performance: PortfolioPerformanceReport
    alpha_beta: AlphaBetaReport
    style_exposure: StyleExposureReport
    selection_report: IndexSelectionReport
    constraint_reports: tuple[PortfolioConstraintReport, ...]
    diagnostics: PortfolioBacktestDiagnostics
    gross_equity: pd.Series = field(default_factory=pd.Series)
    costs: pd.DataFrame = field(default_factory=pd.DataFrame)
    portfolio_drawdown: pd.Series = field(default_factory=pd.Series)
    benchmark_drawdown: pd.Series = field(default_factory=pd.Series)
    excess_drawdown: pd.Series = field(default_factory=pd.Series)
