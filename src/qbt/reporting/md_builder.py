"""Markdown 报告生成 (规范第 16 节)。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from qbt.contracts import LongOnlyFactorBacktestResult

__all__ = ["MarkdownReportBuilder"]


class MarkdownReportBuilder:
    """仅读取回测结果生成 Markdown 报告。"""

    def __init__(
        self, title: str = "指数内多头因子回测报告", *, max_table_rows: int = 40
    ) -> None:
        self.title = title
        self.max_table_rows = max_table_rows

    def _table(self, frame: pd.DataFrame) -> list[str]:
        return _df_to_md(frame.head(self.max_table_rows))

    def build(self, result: LongOnlyFactorBacktestResult) -> str:
        lines: list[str] = []
        lines.append(f"# {self.title}")
        lines.append("")
        lines.extend(self._header(result))
        lines.extend(self._methodology(result))
        lines.extend(self._performance(result))
        lines.extend(self._alpha_beta(result))
        lines.extend(self._style_exposure(result))
        lines.extend(self._selection_diagnostics(result))
        lines.extend(self._costs_and_turnover(result))
        lines.extend(self._constraints(result))
        lines.extend(self._disclosures(result))
        lines.extend(self._data_lineage(result))
        return "\n".join(lines)

    def _header(self, result: LongOnlyFactorBacktestResult) -> list[str]:
        m = result.run_manifest
        cfg = m.config
        return [
            "## 1. 运行摘要",
            "",
            f"- **run_id**: `{m.run_id}`",
            f"- **strategy_id**: `{m.strategy_id}`",
            f"- **因子**: {m.factor_id}",
            f"- **因子数据版本**: `{m.factor_data_version}`",
            f"- **因子代码版本**: `{m.factor_code_version}`",
            f"- **因子内容哈希**: `{m.factor_content_hash}`",
            f"- **指数**: {m.index_id}",
            f"- **代码版本**: `{m.code_version}`",
            f"- **配置版本**: {cfg.get('config_version', 'unknown')}",
            f"- **创建时间**: {m.created_at}",
            f"- **回测区间**: {cfg.get('start_date')} ~ {cfg.get('end_date')}",
            f"- **调仓频率**: {cfg.get('rebalance_frequency')}",
            f"- **成交价字段**: {cfg.get('execution', {}).get('fill_price_field', 'unknown')}",
            f"- **初始资金**: {cfg.get('initial_capital', 0):,.0f}",
            "",
        ]

    def _methodology(self, result: LongOnlyFactorBacktestResult) -> list[str]:
        cfg = result.run_manifest.config
        clock = cfg.get("clock", {})
        selection = cfg.get("selection", {})
        weighting = cfg.get("weighting", {})
        execution = cfg.get("execution", {})
        lag = int(clock.get("order_lag_days", 1)) + int(clock.get("fill_lag_days", 0))
        return [
            "## 2. 方法与时间线",
            "",
            f"- **信号**: T 日 `{clock.get('signal_time', 'close')}` 后，使用 T 日及以前可知数据。",
            f"- **下单/成交**: T+{lag} 交易日下单并按 `{execution.get('fill_price_field')}` 成交；"
            "先卖后买，卖出回款当日可用。",
            "- **收益归属**: 成交日计入成交价至当日收盘损益，之后按收盘到收盘计价；"
            "正式收益只由实际成交持仓和现金账户生成。",
            f"- **末端处理**: `drop_incomplete={clock.get('drop_incomplete')}`，"
            "不能完成信号→成交→估值链路的末端信号日被剔除。",
            f"- **选股**: PIT 指数成分 ∩ T 日可交易 ∩ 因子有效为分母，"
            f"取前 {float(selection.get('selection_fraction', 0)):.0%}；"
            f"并列规则 `{selection.get('tie_break')}`。",
            f"- **权重**: `{weighting.get('method')}`；cutoff `{weighting.get('cutoff_mode')}`；"
            f"等权兜底 `{weighting.get('allow_equal_weight_fallback')}`；"
            f"单票上限 {float(weighting.get('max_weight', 0)):.2%}；"
            f"现金缓冲 {float(weighting.get('cash_buffer', 0)):.2%}。",
            f"- **调仓频率**: `{cfg.get('rebalance_frequency')}`；初始资金 "
            f"{float(cfg.get('initial_capital', 0)):,.2f}。",
            "",
        ]

    def _performance(self, result: LongOnlyFactorBacktestResult) -> list[str]:
        lines = ["## 3. 绩效指标", ""]
        stats = [result.performance.full_sample, result.performance.in_sample, result.performance.out_of_sample]
        labels = ["全样本", "IS", "OOS"]
        samples: list[tuple[str, Any]] = []
        for label, s in zip(labels, stats):
            if s is None:
                continue
            samples.append((label, s))
        metrics = [
            ("区间", lambda s: f"{s.start_date} ~ {s.end_date}"),
            ("交易日数", lambda s: str(s.n_days)),
            ("累计收益", lambda s: _fmt_pct(s.total_return)),
            ("年化收益", lambda s: _fmt_pct(s.annual_return)),
            ("毛年化收益", lambda s: _fmt_pct(s.gross_annual_return)),
            ("年化波动", lambda s: _fmt_pct(s.annual_volatility)),
            ("Sharpe", lambda s: _fmt_num(s.sharpe)),
            ("Sortino", lambda s: _fmt_num(s.sortino)),
            ("最大回撤", lambda s: _fmt_pct(s.max_drawdown)),
            ("最大回撤峰值/谷底/修复", lambda s: f"{s.max_drawdown_start} / {s.max_drawdown_trough} / {s.max_drawdown_recovery or '未修复'}"),
            ("回撤持续/修复交易日", lambda s: f"{s.max_drawdown_duration_days} / {s.max_drawdown_recovery_days}"),
            ("Calmar", lambda s: _fmt_num(s.calmar)),
            ("基准累计收益", lambda s: _fmt_pct(s.benchmark_total_return)),
            ("基准年化收益", lambda s: _fmt_pct(s.benchmark_annual_return)),
            ("几何累计超额", lambda s: _fmt_pct(s.excess_total_return_geometric)),
            ("几何年化超额", lambda s: _fmt_pct(s.excess_annual_return_geometric)),
            ("算术年化超额", lambda s: _fmt_pct(s.excess_annual_return_arithmetic)),
            ("跟踪误差", lambda s: _fmt_pct(s.tracking_error)),
            ("信息比率", lambda s: _fmt_num(s.information_ratio)),
            ("超额最大回撤", lambda s: _fmt_pct(s.excess_max_drawdown)),
            ("日/月/年超额胜率", lambda s: f"{_fmt_pct(s.win_rate_daily)} / {_fmt_pct(s.win_rate_monthly)} / {_fmt_pct(s.win_rate_yearly)}"),
            ("年化单边换手", lambda s: _fmt_num(s.turnover_annual_oneway)),
            ("总交易成本", lambda s: _fmt_money(s.total_cost)),
            ("成本侵蚀比例", lambda s: _fmt_pct(s.cost_erosion_ratio)),
            ("平均持股数", lambda s: _fmt_num(s.avg_holdings)),
            ("平均前十集中度", lambda s: _fmt_pct(s.avg_top10_concentration)),
            ("平均现金比例", lambda s: _fmt_pct(s.avg_cash_ratio)),
            ("平均 HHI", lambda s: _fmt_num(s.hhi)),
        ]
        rows = [{"指标": metric, **{label: render(s) for label, s in samples}} for metric, render in metrics]
        lines.extend(self._table(pd.DataFrame(rows)))
        lines.extend(["", "### 年度表现", ""])
        lines.extend(self._table(result.performance.yearly))
        lines.append("")
        return lines

    def _alpha_beta(self, result: LongOnlyFactorBacktestResult) -> list[str]:
        ab = result.alpha_beta
        return [
            "## 4. Alpha / Beta 拆分",
            "",
            f"- **日度 Alpha**: {ab.alpha_daily:.6f}",
            f"- **年化 Alpha**: {ab.alpha_annual:.2%}",
            f"- **Beta**: {ab.beta:.3f}",
            f"- **Alpha t-stat (OLS)**: {ab.alpha_tstat_ols:.2f}",
            f"- **Alpha t-stat (NW)**: {ab.alpha_tstat_nw:.2f}",
            f"- **Alpha p-value (NW)**: {ab.alpha_pvalue_nw:.4f}",
            f"- **Alpha p-value (OLS)**: {ab.alpha_pvalue_ols:.4f}",
            f"- **Beta t-stat (OLS / NW)**: {ab.beta_tstat_ols:.2f} / {ab.beta_tstat_nw:.2f}",
            f"- **R-squared**: {ab.r_squared:.3f}",
            f"- **残差波动率(年化)**: {ab.residual_volatility_annual:.2%}",
            f"- **观测数**: {ab.n_observations}",
            f"- **Beta 累计贡献**: {ab.beta_contribution_total:.4f}",
            f"- **Alpha/残差累计贡献**: {ab.alpha_contribution_total:.4f}",
            "",
            "### 分样本回归",
            "",
            *self._table(pd.DataFrame.from_dict(ab.by_sample, orient="index").reset_index(names="sample")),
            "",
        ]

    def _style_exposure(self, result: LongOnlyFactorBacktestResult) -> list[str]:
        lines = ["## 5. 风格因子暴露", ""]
        if result.style_exposure.summary.empty:
            lines.append("无风格暴露数据。")
            lines.append("")
            return lines
        summary = result.style_exposure.summary[[
            "style", "portfolio_mean", "index_mean", "active_mean",
            "active_max_abs", "active_latest", "missing_ratio"
        ]].copy()
        lines.extend(self._table(summary))
        lines.append("")
        if result.style_exposure.missing_styles:
            lines.append(f"**缺失风格**: {', '.join(result.style_exposure.missing_styles)}")
            lines.append("")
        lines.append("### 风格暴露与超额收益关系")
        lines.append("")
        lines.extend(self._table(result.style_exposure.excess_return_relation))
        lines.append("")
        return lines

    def _selection_diagnostics(self, result: LongOnlyFactorBacktestResult) -> list[str]:
        lines = ["## 6. 指数内选股诊断", ""]
        bs = result.selection_report.by_sample
        if not bs.empty:
            lines.extend(self._table(bs))
        lines.append("")
        lines.append("### 分年度选股表现")
        lines.append("")
        lines.extend(self._table(result.selection_report.yearly))
        lines.append("")
        notes = result.selection_report.notes
        for k, v in notes.items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")
        return lines

    def _costs_and_turnover(self, result: LongOnlyFactorBacktestResult) -> list[str]:
        lines = ["## 7. 换手、成本、流动性与未成交", ""]
        costs = result.costs
        if not costs.empty:
            total = costs[["commission", "stamp_duty", "transfer_fee", "slippage_cost"]].sum()
            lines.append("| 成本项 | 合计 |")
            lines.append("| --- | --- |")
            for k, v in total.items():
                lines.append(f"| {k} | {v:,.2f} |")
            lines.append("")
        cl = result.cash_ledger
        if "turnover" in cl.columns:
            lines.append(f"- **累计单边换手**: {cl['turnover'].sum():.4f}")
            lines.append(f"- **日均单边换手**: {cl['turnover'].mean():.4f}")
            lines.append("")
        daily = result.selection_report.daily
        lines.extend([
            f"- **平均 / 最大 ADV 参与率**: {_fmt_pct(daily['adv_participation_mean'].mean())} / "
            f"{_fmt_pct(daily['adv_participation_max'].max())}",
            f"- **未成交订单数**: {int(daily['n_unfilled'].sum())}",
            f"- **未成交金额**: {_fmt_money(daily['unfilled_amount'].sum())}",
            f"- **最大单日未成交金额比例**: {_fmt_pct(daily['unfilled_ratio'].max())}",
            "",
        ])
        if not result.diagnostics.unfilled_summary.empty:
            lines.append("### 未成交明细（按原因）")
            lines.append("")
            summary = result.diagnostics.unfilled_summary.groupby(["side", "reason"], as_index=False).agg(
                n_orders=("asset_id", "size"),
                unfilled_shares=("unfilled_quantity", "sum"),
                unfilled_amount=("unfilled_amount", "sum"),
            )
            lines.extend(self._table(summary))
            lines.append("")
        return lines

    def _constraints(self, result: LongOnlyFactorBacktestResult) -> list[str]:
        lines = ["## 8. 约束检查", ""]
        rows = []
        for c in result.constraint_reports:
            rows.append(
                {
                    "约束": c.constraint,
                    "启用": c.enabled,
                    "上限": c.limit,
                    "检查次数": c.n_checked,
                    "违规次数": c.n_violations,
                    "最大观测": c.max_observed,
                    "处理": c.action,
                }
            )
        lines.extend(self._table(pd.DataFrame(rows)))
        lines.append("")
        violating = [c for c in result.constraint_reports if c.n_violations > 0]
        if violating:
            lines.append("### 约束违规明细")
            lines.append("")
            for constraint in violating:
                lines.append(
                    f"#### `{constraint.constraint}`（{constraint.n_violations} 条；"
                    "完整明细见 `constraint_reports.json`）"
                )
                lines.append("")
                lines.extend(self._table(constraint.violations))
                lines.append("")
        return lines

    def _disclosures(self, result: LongOnlyFactorBacktestResult) -> list[str]:
        lines = ["## 9. 数据缺失、排除与风险披露", ""]
        if not result.diagnostics.exclusion_reasons.empty:
            totals = result.diagnostics.exclusion_reasons.sum(numeric_only=True)
            lines.append("### 选股排除汇总")
            lines.append("")
            exclusion_table = totals.rename("count").rename_axis("reason").reset_index()
            lines.extend(self._table(exclusion_table))
            lines.append("")
        for warning in result.diagnostics.warnings:
            if warning:
                lines.append(f"- {warning}")
        for d in result.run_manifest.disclosures:
            lines.append(f"- {d}")
        lines.append("")
        return lines

    def _data_lineage(self, result: LongOnlyFactorBacktestResult) -> list[str]:
        lines = ["## 10. 数据谱系与指标定义", ""]
        lines.append("| 数据集 | URI | 内容哈希 | 行数 | 列数 | 日期范围 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for ref in result.run_manifest.dataset_refs:
            lines.append(
                f"| {ref.name} | {ref.uri} | `{ref.content_hash[:16]}...` | "
                f"{ref.rows} | {ref.columns} | {ref.date_min} ~ {ref.date_max} |"
            )
        lines.append("")
        lines.append(f"- **结果内容哈希**: `{result.run_manifest.result_hash}`")
        lines.append("")
        lines.append("### 指标定义")
        lines.append("")
        definitions = pd.DataFrame(
            [{"指标": key, "定义": value} for key, value in result.performance.definitions.items()]
        )
        lines.extend(self._table(definitions))
        lines.append("")
        return lines


def _df_to_md(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return ["(空表)", ""]
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |"]
    lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
    for _, row in df.iterrows():
        vals = []
        for c in cols:
            v = row[c]
            if isinstance(v, float):
                if pd.isna(v):
                    vals.append("-")
                else:
                    vals.append(f"{v:.4f}")
            else:
                vals.append(str(v))
        lines.append("| " + " | ".join(vals) + " |")
    return lines


def _fmt_num(value: float) -> str:
    return "-" if pd.isna(value) else f"{value:.4f}"


def _fmt_pct(value: float) -> str:
    return "-" if pd.isna(value) else f"{value:.2%}"


def _fmt_money(value: float) -> str:
    return "-" if pd.isna(value) else f"{value:,.2f}"
