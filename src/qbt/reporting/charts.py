"""标准图表 (规范第 15 节)。

报告器独占的 Matplotlib 绘图代码; 回测器不导入本模块。
"""

from __future__ import annotations

from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

from qbt.contracts import LongOnlyFactorBacktestResult


def _configure_cjk_font() -> None:
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    )
    for path in candidates:
        try:
            font_manager.fontManager.addfont(path)
            family = font_manager.FontProperties(fname=path).get_name()
            matplotlib.rcParams["font.sans-serif"] = [family, "DejaVu Sans"]
            matplotlib.rcParams["axes.unicode_minus"] = False
            return
        except (FileNotFoundError, RuntimeError, OSError):
            continue

_configure_cjk_font()

__all__ = ["ChartBuilder", "ChartResult"]


@dataclass(frozen=True)
class ChartResult:
    figures: dict[str, plt.Figure]


class ChartBuilder:
    """生成规范 §15 全部标准图表。"""

    def __init__(
        self,
        *,
        width: float = 11.0,
        height: float = 5.2,
        dpi: int = 140,
        format: str = "png",
    ) -> None:
        self.width = width
        self.height = height
        self.dpi = dpi
        self.format = format

    def build(self, result: LongOnlyFactorBacktestResult) -> ChartResult:
        figs: dict[str, plt.Figure] = {}
        figs["nav_comparison"] = self._nav_comparison(result)
        figs["excess_nav"] = self._excess_nav(result)
        figs["drawdown"] = self._drawdown(result)
        figs["monthly_returns"] = self._monthly_returns(result)
        figs["annual_returns"] = self._annual_returns(result)
        figs["rolling_metrics"] = self._rolling_metrics(result)
        figs["alpha_beta_contribution"] = self._alpha_beta_contribution(result)
        figs["rolling_alpha_beta"] = self._rolling_alpha_beta(result)
        figs["style_exposure_timeseries"] = self._style_exposure_timeseries(result)
        figs["style_exposure_heatmap"] = self._style_exposure_heatmap(result)
        figs["universe_coverage"] = self._universe_coverage(result)
        figs["turnover_and_costs"] = self._turnover_and_costs(result)
        figs["unfilled_and_adv"] = self._unfilled_and_adv(result)
        figs["sample_metrics"] = self._sample_metrics(result)
        return ChartResult(figures=figs)

    # ---------- 内部图表方法 ----------

    def _nav_comparison(self, result: LongOnlyFactorBacktestResult) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(self.width, self.height))
        df = pd.DataFrame(
            {
                "组合费后净值": result.portfolio_equity,
                "组合费前净值": result.gross_equity,
                "基准净值": result.benchmark_equity,
            }
        )
        df.plot(ax=ax, linewidth=1.2)
        ax.set_title("组合费前/费后/基准净值")
        ax.set_xlabel("日期")
        ax.set_ylabel("净值")
        ax.legend(loc="upper left")
        ax.grid(True, alpha=0.3)
        return fig

    def _excess_nav(self, result: LongOnlyFactorBacktestResult) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(self.width, self.height))
        result.excess_equity.plot(ax=ax, color="darkgreen", linewidth=1.2)
        ax.axhline(1.0, color="gray", linestyle="--", linewidth=0.8)
        ax.set_title("组合超额净值")
        ax.set_xlabel("日期")
        ax.set_ylabel("超额净值")
        ax.grid(True, alpha=0.3)
        return fig

    def _drawdown(self, result: LongOnlyFactorBacktestResult) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(self.width, self.height))
        result.portfolio_drawdown.plot(ax=ax, label="组合回撤", color="steelblue")
        result.excess_drawdown.plot(ax=ax, label="超额回撤", color="coral")
        ax.set_title("组合回撤与超额回撤")
        ax.set_xlabel("日期")
        ax.set_ylabel("回撤")
        ax.legend()
        ax.grid(True, alpha=0.3)
        return fig

    def _monthly_returns(self, result: LongOnlyFactorBacktestResult) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(self.width, self.height))
        source = result.performance.monthly.set_index("month")
        months = source[[
            "portfolio_return", "benchmark_return", "excess_return_geometric"
        ]].rename(columns={
            "portfolio_return": "组合", "benchmark_return": "基准",
            "excess_return_geometric": "超额",
        })
        months.plot(kind="bar", ax=ax, width=0.8)
        ax.set_title("月度组合/基准/超额收益")
        ax.set_xlabel("月份")
        ax.set_ylabel("收益")
        ax.legend()
        ax.grid(True, alpha=0.3, axis="y")
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
        return fig

    def _annual_returns(self, result: LongOnlyFactorBacktestResult) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(self.width, self.height))
        source = result.performance.yearly.set_index("year")
        years = source[[
            "portfolio_return", "benchmark_return", "excess_return_geometric"
        ]].rename(columns={
            "portfolio_return": "组合", "benchmark_return": "基准",
            "excess_return_geometric": "超额",
        })
        years.plot(kind="bar", ax=ax)
        ax.set_title("年度组合/基准/超额收益")
        ax.set_xlabel("年度")
        ax.set_ylabel("收益")
        ax.legend()
        ax.grid(True, alpha=0.3, axis="y")
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=0)
        return fig

    def _rolling_metrics(self, result: LongOnlyFactorBacktestResult) -> plt.Figure:
        fig, axes = plt.subplots(2, 2, figsize=(self.width, self.height * 1.4))
        rolling = result.performance.rolling
        if not rolling.empty and rolling.notna().any().any():
            rolling["annual_return"].plot(ax=axes[0, 0], title="滚动年化收益")
            rolling["annual_volatility"].plot(ax=axes[0, 1], title="滚动年化波动")
            rolling["sharpe"].plot(ax=axes[1, 0], title="滚动 Sharpe")
            rolling["information_ratio"].plot(ax=axes[1, 1], title="滚动信息比率")
        for ax in axes.flat:
            ax.grid(True, alpha=0.3)
        plt.tight_layout()
        return fig

    def _alpha_beta_contribution(self, result: LongOnlyFactorBacktestResult) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(self.width, self.height))
        contrib = result.alpha_beta.contributions
        if not contrib.empty:
            contrib["beta_contribution_cum"].plot(ax=ax, label="Beta 累计贡献")
            contrib["alpha_contribution_cum"].plot(ax=ax, label="Alpha/残差累计贡献")
        ax.set_title("Alpha / Beta 累计贡献")
        ax.set_xlabel("日期")
        ax.set_ylabel("累计收益")
        ax.legend()
        ax.grid(True, alpha=0.3)
        return fig

    def _rolling_alpha_beta(self, result: LongOnlyFactorBacktestResult) -> plt.Figure:
        fig, axes = plt.subplots(2, 2, figsize=(self.width, self.height * 1.4))
        r = result.alpha_beta.rolling
        if not r.empty:
            r["rolling_beta"].plot(ax=axes[0, 0], title="滚动 Beta")
            r["rolling_alpha_annual"].plot(ax=axes[0, 1], title="滚动年化 Alpha")
            r["rolling_r_squared"].plot(ax=axes[1, 0], title="滚动 R-squared")
            r["rolling_alpha_tstat_nw"].plot(ax=axes[1, 1], title="滚动 Alpha t-stat (NW)")
        axes[0, 0].set_ylabel("系数")
        axes[0, 1].set_ylabel("年化收益")
        axes[1, 0].set_ylabel("拟合优度")
        axes[1, 1].set_ylabel("t 统计量")
        for ax in axes.flat:
            ax.set_xlabel("日期")
            ax.grid(True, alpha=0.3)
        plt.tight_layout()
        return fig

    def _style_exposure_timeseries(self, result: LongOnlyFactorBacktestResult) -> plt.Figure:
        fig, axes = plt.subplots(3, 1, figsize=(self.width, self.height * 1.8), sharex=True)
        views = (
            (result.style_exposure.portfolio_exposure, "组合风格暴露"),
            (result.style_exposure.index_exposure, "指数风格暴露"),
            (result.style_exposure.active_exposure, "主动风格暴露"),
        )
        for ax, (frame, title) in zip(axes, views):
            available = frame.dropna(axis=1, how="all")
            if not available.empty:
                available.plot(ax=ax, linewidth=0.8)
            ax.set_title(title)
            ax.set_ylabel("z-score")
            if not available.empty:
                ax.legend(loc="upper left", ncol=3, fontsize="x-small")
            ax.grid(True, alpha=0.3)
        axes[-1].set_xlabel("日期")
        plt.tight_layout()
        return fig

    def _style_exposure_heatmap(self, result: LongOnlyFactorBacktestResult) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(self.width, self.height * 1.2))
        active = result.style_exposure.active_exposure
        if active.empty or active.dropna(how="all").empty:
            ax.text(0.5, 0.5, "无风格暴露数据", ha="center", va="center")
            return fig
        # 按年聚合主动暴露均值
        yearly = active.groupby(active.index.year).mean()
        im = ax.imshow(yearly.T.to_numpy(), aspect="auto", cmap="RdYlGn_r")
        ax.set_yticks(range(len(yearly.columns)))
        ax.set_yticklabels(yearly.columns)
        ax.set_xticks(range(len(yearly.index)))
        ax.set_xticklabels(yearly.index)
        ax.set_title("年度平均主动风格暴露热力图")
        plt.colorbar(im, ax=ax)
        return fig

    def _universe_coverage(self, result: LongOnlyFactorBacktestResult) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(self.width, self.height))
        sr = result.selection_report.daily
        cols = [c for c in ["n_index_members", "n_selected", "n_holdings"] if c in sr.columns]
        if cols:
            sr[cols].plot(ax=ax)
        if "factor_coverage" in sr.columns:
            ax2 = ax.twinx()
            (sr["factor_coverage"] * 100).plot(ax=ax2, color="gray", linestyle="--", label="因子覆盖率(%)")
            ax2.set_ylabel("因子覆盖率 (%)")
        ax.set_title("指数成分数量 / 入选数量 / 实际持股 / 因子覆盖率")
        ax.set_xlabel("日期")
        ax.set_ylabel("数量")
        ax.legend(loc="upper left")
        ax.grid(True, alpha=0.3)
        return fig

    def _turnover_and_costs(self, result: LongOnlyFactorBacktestResult) -> plt.Figure:
        fig, axes = plt.subplots(2, 1, figsize=(self.width, self.height * 1.2))
        cl = result.cash_ledger
        if "turnover" in cl.columns:
            cl["turnover"].plot(ax=axes[0], title="日度单边换手率")
        costs = result.costs
        if not costs.empty and "total" in costs.columns:
            costs[["commission", "stamp_duty", "transfer_fee", "slippage_cost"]].plot(
                ax=axes[1], stacked=True, title="日度交易成本分项"
            )
        for ax in axes:
            ax.grid(True, alpha=0.3)
        plt.tight_layout()
        return fig

    def _unfilled_and_adv(self, result: LongOnlyFactorBacktestResult) -> plt.Figure:
        fig, axes = plt.subplots(2, 1, figsize=(self.width, self.height * 1.25), sharex=True)
        sr = result.selection_report.daily
        (sr["adv_participation_mean"] * 100).plot(
            ax=axes[0], label="平均 ADV 参与率", color="#2f6f8f"
        )
        (sr["adv_participation_max"] * 100).plot(
            ax=axes[0], label="最大 ADV 参与率", color="#d95f02", alpha=0.8
        )
        axes[0].set_title("ADV 参与率")
        axes[0].set_ylabel("占 ADV (%)")
        axes[0].legend()
        (sr["unfilled_ratio"] * 100).plot(
            ax=axes[1], label="未成交金额比例", color="#b2182b"
        )
        axes[1].set_title("未成交比例与金额")
        axes[1].set_ylabel("比例 (%)")
        amount_axis = axes[1].twinx()
        sr["unfilled_amount"].plot(
            ax=amount_axis, label="未成交金额", color="#4d4d4d", alpha=0.45
        )
        amount_axis.set_ylabel("金额")
        axes[1].set_xlabel("日期")
        axes[1].legend(loc="upper left")
        amount_axis.legend(loc="upper right")
        for ax in axes:
            ax.grid(True, alpha=0.3)
        plt.tight_layout()
        return fig

    def _sample_metrics(self, result: LongOnlyFactorBacktestResult) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(self.width, self.height))
        bs = result.selection_report.by_sample
        if not bs.empty and "sample" in bs.columns:
            metrics = ["portfolio_net_return", "benchmark_return", "excess_return_geometric"]
            present = [m for m in metrics if m in bs.columns]
            bs.set_index("sample")[present].plot(kind="bar", ax=ax)
        ax.set_title("IS / OOS / 全样本收益对比")
        ax.set_ylabel("累计收益")
        ax.legend()
        ax.grid(True, alpha=0.3, axis="y")
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=0)
        return fig
