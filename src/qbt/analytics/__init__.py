"""分析层: 收益、绩效、Alpha/Beta、风格、选股诊断。"""

from qbt.analytics.alphabeta import OLSResult, compute_alpha_beta, ols_with_newey_west
from qbt.analytics.metrics import (
    compute_performance_stats,
    monthly_table,
    yearly_table,
)
from qbt.analytics.returns import build_return_frame, drawdown_series, drawdown_table
from qbt.analytics.selection_report import build_selection_report
from qbt.analytics.style import REQUIRED_STYLES, compute_style_exposure

__all__ = [
    "OLSResult",
    "REQUIRED_STYLES",
    "build_return_frame",
    "build_selection_report",
    "compute_alpha_beta",
    "compute_performance_stats",
    "compute_style_exposure",
    "drawdown_series",
    "drawdown_table",
    "monthly_table",
    "ols_with_newey_west",
    "yearly_table",
]
