"""主回测器编排 (规范 14.1 / 17-P0..P5)。

本模块把 DataPortal、选股、权重、执行、收益、指标、Alpha/Beta、风格、选股诊断
串联成规范要求的冻结结果。回测器不导入任何绘图或报告代码。
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qbt.contracts import (
    ConstraintConfig,
    DatasetRef,
    FactorFrame,
    LongOnlyFactorBacktestConfig,
    LongOnlyFactorBacktestRequest,
    LongOnlyFactorBacktestResult,
    PortfolioBacktestDiagnostics,
    PortfolioConstraintReport,
    ResolvedLongOnlyBacktestData,
    RunManifest,
    position_period_to_frame,
)
from qbt.data.hashing import (
    git_code_version,
    hash_frame,
    hash_object,
    new_run_id,
    utc_now_iso,
)
from qbt.data.portal import PortfolioDataPortal

from .execution import ExecutionEngine, ExecutionOutput
from .selection import select_daily
from .weighting import build_target_weights

__all__ = ["LongOnlyFactorBacktester", "BacktesterConfig"]


@dataclass(frozen=True)
class BacktesterConfig:
    """回测器自身的行为配置 (不影响业务口径)。"""

    repo_root: Path | None = None


class LongOnlyFactorBacktester:
    """研究员入口: factor + index_id -> 冻结结果。"""

    def __init__(
        self,
        data_portal: PortfolioDataPortal,
        *,
        backtester_config: BacktesterConfig | None = None,
    ) -> None:
        self.portal = data_portal
        self.bcfg = backtester_config or BacktesterConfig()

    def run(self, request: LongOnlyFactorBacktestRequest) -> LongOnlyFactorBacktestResult:
        cfg = request.config
        resolved = self.portal.resolve(request.factor, request.index_id, cfg)
        manifest = self._build_manifest(request, resolved, cfg)

        # P1: 选股
        selection = select_daily(
            factor_values=request.factor.values,
            direction=request.factor.direction,
            index_universe=resolved.index_universe,
            ex_ante_tradable=resolved.tradability.ex_ante_tradable,
            selection_fraction=cfg.selection.selection_fraction,
            min_holdings=cfg.selection.min_holdings,
            fail_on_insufficient_universe=cfg.selection.fail_on_insufficient_universe,
            requires_tradable=cfg.selection.eligibility_requires_tradable,
            requires_valid_factor=cfg.selection.eligibility_requires_valid_factor,
        )

        # P1: 目标权重
        scores = request.factor.oriented.reindex(
            index=resolved.index_universe.index, columns=resolved.index_universe.columns
        )
        weighting = build_target_weights(
            scores=scores,
            selected=selection.selected,
            rank=selection.rank,
            method=cfg.weighting.method,
            index_weights=resolved.index_weights,
            max_weight=cfg.weighting.max_weight,
            cash_buffer=cfg.weighting.cash_buffer,
            allow_equal_weight_fallback=cfg.weighting.allow_equal_weight_fallback,
            min_holdings=cfg.selection.min_holdings,
        )
        target_weights = self._apply_target_turnover_limit(
            weighting.target_weights,
            resolved.rebalance_dates,
            cfg.constraints.max_turnover,
        )

        # P2: 执行 / 账户
        engine = ExecutionEngine(
            config=cfg,
            prices=resolved.prices,
            tradability=resolved.tradability,
            liquidity=resolved.liquidity_data,
            index_universe=resolved.index_universe,
        )
        execution = engine.run(
            target_weights=target_weights,
            rebalance_dates=resolved.rebalance_dates,
            initial_capital=resolved.initial_state.initial_capital,
        )

        # P3: 收益 / 净值 / 回撤
        from qbt.analytics.returns import build_return_frame

        rf_daily = float(cfg.regression.risk_free_annual) / float(cfg.regression.trading_days_per_year)
        return_frame = build_return_frame(
            cash_ledger=execution.cash_ledger,
            benchmark_return=resolved.benchmark_returns,
            risk_free_daily=rf_daily,
        )
        # 把换手率/集中度/HHI 挂到 return_frame, 供指标层使用
        return_frame = self._attach_holding_metrics(
            return_frame, execution.actual_weights, execution.cash_ledger
        )

        # P5: 绩效指标

        samples = {
            "full_sample": return_frame,
            "in_sample": return_frame[resolved.sample_masks["in_sample"]]
            if "in_sample" in resolved.sample_masks
            else None,
            "out_of_sample": return_frame[resolved.sample_masks["out_of_sample"]]
            if "out_of_sample" in resolved.sample_masks
            else None,
        }
        performance = self._build_performance_report(
            return_frame, samples, cfg, execution.actual_weights
        )

        # P4: Alpha/Beta
        from qbt.analytics.alphabeta import compute_alpha_beta

        alpha_beta = compute_alpha_beta(
            return_frame,
            config=cfg.regression,
            samples=samples,
        )

        # P4: 风格暴露
        from qbt.analytics.style import compute_style_exposure

        if resolved.index_weights is None:
            raise ValueError("resolved index_weights cannot be None")
        style_exposure = compute_style_exposure(
            actual_weights=execution.actual_weights,
            index_weights=resolved.index_weights.fillna(0.0),
            style_panels={k.lower(): v for k, v in resolved.style_exposures.items()},
            excess_returns=return_frame["excess_return"],
            data_source="proxy_from_price_and_valuation",
        )

        # P5: 选股诊断
        from qbt.analytics.selection_report import build_selection_report
        from qbt.contracts.records import fills_to_frame

        selection_report = build_selection_report(
            return_frame=return_frame,
            selection_diagnostics=selection.diagnostics,
            selected=selection.selected,
            target_weights=target_weights,
            rebalance_dates=resolved.rebalance_dates,
            adj_close=resolved.prices.adj_close,
            adj_fill_price=getattr(resolved.prices, cfg.execution.fill_price_field),
            order_lag_days=cfg.clock.order_lag_days,
            fill_lag_days=cfg.clock.fill_lag_days,
            fill_price_field=cfg.execution.fill_price_field,
            fills=fills_to_frame(execution.fills),
            factor_coverage=selection.diagnostics.get("eligible_ratio"),
            unfilled_summary=execution.unfilled_summary,
            oos_start=cfg.oos_start,
        )

        # 约束报告
        constraint_reports = self._build_constraint_reports(
            cfg.constraints,
            execution.actual_weights,
            execution.cash_ledger,
            execution.unfilled_summary,
            fills_to_frame(execution.fills),
        )

        # 诊断信息
        diagnostics = self._build_diagnostics(
            cfg, resolved, execution, return_frame, request.factor,
            selection.exclusion_reasons,
        )

        holdings = self._build_holdings_frame(execution, resolved.prices.adj_factor)
        position_period_analysis = position_period_to_frame(execution.position_period_records)

        result = LongOnlyFactorBacktestResult(
            run_manifest=manifest,
            selected_members=selection.selected,
            target_weights=target_weights,
            actual_weights=execution.actual_weights,
            orders=execution.orders,
            fills=execution.fills,
            holdings=holdings,
            cash_ledger=execution.cash_ledger,
            gross_returns=return_frame["portfolio_gross_return"],
            net_returns=return_frame["portfolio_net_return"],
            benchmark_returns=return_frame["benchmark_return"],
            excess_returns=return_frame["excess_return"],
            portfolio_equity=return_frame["portfolio_nav"],
            benchmark_equity=return_frame["benchmark_nav"],
            excess_equity=return_frame["excess_nav"],
            performance=performance,
            alpha_beta=alpha_beta,
            style_exposure=style_exposure,
            selection_report=selection_report,
            constraint_reports=constraint_reports,
            diagnostics=diagnostics,
            gross_equity=return_frame["portfolio_gross_nav"],
            costs=execution.costs,
            portfolio_drawdown=return_frame["portfolio_drawdown"],
            benchmark_drawdown=return_frame["benchmark_drawdown"],
            excess_drawdown=return_frame["excess_drawdown"],
            position_period_analysis=position_period_analysis,
        )
        result_payload = {
            field.name: getattr(result, field.name)
            for field in fields(result)
            if field.name != "run_manifest"
        }
        result_hash = hash_object(
            {
                "manifest_contract": {
                    "strategy_id": manifest.strategy_id,
                    "factor_id": manifest.factor_id,
                    "index_id": manifest.index_id,
                    "code_version": manifest.code_version,
                    "config_version": manifest.config_version,
                    "config": manifest.config,
                    "dataset_refs": manifest.dataset_refs,
                    "factor_data_version": manifest.factor_data_version,
                    "factor_content_hash": manifest.factor_content_hash,
                    "factor_code_version": manifest.factor_code_version,
                    "disclosures": manifest.disclosures,
                },
                "result": result_payload,
            }
        )
        manifest = self._with_result_hash(manifest, result_hash)
        return replace(result, run_manifest=manifest)

    # ---------- 内部组装 ----------

    def _build_manifest(
        self,
        request: LongOnlyFactorBacktestRequest,
        resolved: ResolvedLongOnlyBacktestData,
        cfg: LongOnlyFactorBacktestConfig,
    ) -> RunManifest:
        code_ver = git_code_version(self.bcfg.repo_root)
        index_id = request.index_id or "ALL_A_EQ"
        strategy_id = (
            f"{request.factor.factor_id}_{index_id}_"
            f"sf{cfg.selection_fraction}_wm{cfg.weighting.method}_"
            f"cv{cfg.config_version}"
        )
        benchmark_disclosure = (
            "省略指数时使用 ALL_A_EQ 全A等权基准: 按每日可用上市股票等权再平衡, "
            "停牌日按最后有效收盘估值; 历史退市股缺失仍造成幸存者偏差。"
            if resolved.benchmark_basis == "all_a_equal_weight_daily"
            else "基准收益由 PIT 指数月度权重合成 (buy-and-hold within month), "
            "与官方指数存在跟踪误差; 拿到官方指数点位后可替换。"
        )
        disclosures = [
            "价格与收益在复权价格空间计算, 数量与估值使用复权股数, 等价于分红再投资的全收益近似。",
            "历史退市股与历史 ST 状态未包含在当前数据源中, 存在幸存者偏差与 ST 状态推断缺失。",
            benchmark_disclosure,
            "风格暴露为基于价量/估值字段自建的简化代理 (非 Barra), "
            "Growth/Quality/Leverage 因缺财务数据标记为缺失。",
            f"T+1 按 {cfg.execution.fill_price_field} 成交 (默认全天 VWAP), "
            "整手买入、卖出允许零股, 先卖后买, 未成交订单当日取消。",
        ]
        resolved_warnings = resolved.notes.get("warnings", ())
        if not isinstance(resolved_warnings, (list, tuple)) or not all(
            isinstance(item, str) for item in resolved_warnings
        ):
            raise TypeError("resolved.notes['warnings'] must be a sequence of strings")
        disclosures.extend(resolved_warnings)
        run_id = new_run_id("lof")
        actual_factor_hash = hash_frame(request.factor.values)
        if request.factor.content_hash and request.factor.content_hash != actual_factor_hash:
            raise ValueError(
                "FactorFrame.content_hash 与 values 实际内容不一致: "
                f"supplied={request.factor.content_hash}, actual={actual_factor_hash}"
            )
        factor_hash = actual_factor_hash
        factor_ref = DatasetRef(
            name=f"factor:{request.factor.factor_id}",
            uri="request:factor_frame",
            content_hash=factor_hash,
            rows=len(request.factor.values),
            columns=request.factor.values.shape[1],
            date_min=str(request.factor.values.index.min().date()),
            date_max=str(request.factor.values.index.max().date()),
            notes=(
                f"data_version={request.factor.data_version}; "
                f"code_version={request.factor.code_version}"
            ),
        )
        return RunManifest(
            run_id=run_id,
            strategy_id=strategy_id,
            factor_id=request.factor.factor_id,
            index_id=index_id,
            code_version=code_ver,
            config_version=cfg.config_version,
            created_at=utc_now_iso(),
            config=self._config_dict(cfg),
            dataset_refs=tuple(resolved.dataset_refs) + (factor_ref,),
            artifact_uri=str(Path("artifacts") / run_id),
            environment={"python": "3.11+", "backtester": "qbt.v1"},
            disclosures=tuple(disclosures),
            factor_data_version=request.factor.data_version,
            factor_content_hash=factor_hash,
            factor_code_version=request.factor.code_version,
        )

    @staticmethod
    def _with_result_hash(manifest: RunManifest, result_hash: str) -> RunManifest:
        return replace(manifest, result_hash=result_hash)

    @staticmethod
    def _config_dict(cfg: LongOnlyFactorBacktestConfig) -> dict[str, Any]:
        from qbt.contracts.config import asdict_deep

        d = asdict_deep(cfg)
        # 把顶层便捷字段与嵌套对象一起保留, 方便追踪
        d["business_summary"] = {
            "selection_fraction": cfg.selection_fraction,
            "weighting_method": cfg.weighting_method,
            "rebalance_frequency": cfg.rebalance_frequency,
            "signal_lag_days": cfg.signal_lag_days,
            "fill_price_field": cfg.execution.fill_price_field,
            "initial_capital": cfg.initial_capital,
        }
        return d

    @staticmethod
    def _attach_holding_metrics(
        frame: pd.DataFrame,
        actual_weights: pd.DataFrame,
        cash_ledger: pd.DataFrame,
    ) -> pd.DataFrame:
        """计算换手率、前 10 集中度、HHI, 并挂到收益表。"""
        idx = frame.index
        w = actual_weights.reindex(index=idx).fillna(0.0).to_numpy(dtype="float64")
        turnover = cash_ledger["turnover"].reindex(idx).rename("turnover")

        # 前 10 集中度
        sorted_w = np.sort(w, axis=1)[:, ::-1]
        top10 = sorted_w[:, :10].sum(axis=1)
        top10_s = pd.Series(top10, index=idx, name="top10_concentration")

        # HHI
        hhi = pd.Series(np.nansum(w ** 2, axis=1), index=idx, name="hhi")

        frame = frame.copy()
        frame["turnover"] = turnover
        frame["top10_concentration"] = top10_s
        frame["hhi"] = hhi
        return frame

    @staticmethod
    def _apply_target_turnover_limit(
        target_weights: pd.DataFrame,
        rebalance_dates: tuple[pd.Timestamp, ...],
        max_turnover: float | None,
    ) -> pd.DataFrame:
        """Scale rebalance transitions so planned one-way turnover stays within the limit."""
        out = target_weights.copy().astype("float64")
        if max_turnover is None:
            return out
        if not np.isfinite(max_turnover) or max_turnover < 0:
            raise ValueError("max_turnover 必须是非负有限数")

        previous = pd.Series(0.0, index=out.columns, dtype="float64")
        for date in sorted(pd.Timestamp(d) for d in rebalance_dates):
            if date not in out.index:
                continue
            desired = out.loc[date].fillna(0.0).clip(lower=0.0)
            planned = float((desired - previous).abs().sum() / 2.0)
            if planned > max_turnover and planned > 0:
                desired = previous + (desired - previous) * (max_turnover / planned)
            out.loc[date] = desired
            previous = desired
        return out

    @staticmethod
    def _build_holdings_frame(
        execution: ExecutionOutput,
        adj_factor: pd.DataFrame,
    ) -> pd.DataFrame:
        """Build the complete position contract with field/asset MultiIndex columns."""
        factor = adj_factor.reindex(
            index=execution.holdings_shares.index,
            columns=execution.holdings_shares.columns,
        )
        fields = {
            "quantity_raw": execution.holdings_shares * factor,
            "quantity_adjusted": execution.holdings_shares,
            "cost_basis": execution.holdings_cost_basis,
            "market_value": execution.holdings_value,
            "unrealized_pnl": execution.holdings_unrealized_pnl,
            "weight": execution.actual_weights,
        }
        frame = pd.concat(fields, axis=1)
        frame.columns.names = ["field", "asset_id"]
        return frame

    @staticmethod
    def _build_performance_report(
        frame: pd.DataFrame,
        samples: dict[str, pd.DataFrame | None],
        cfg: LongOnlyFactorBacktestConfig,
        actual_weights: pd.DataFrame,
    ):
        from qbt.analytics.metrics import compute_performance_stats, monthly_table, yearly_table

        def _stats(label: str, sub: pd.DataFrame | None):
            if sub is None or sub.empty:
                return None
            return compute_performance_stats(
                sub,
                label=label,
                trading_days_per_year=cfg.regression.trading_days_per_year,
                risk_free_daily=cfg.regression.risk_free_annual
                / cfg.regression.trading_days_per_year,
                turnover_oneway=sub.get("turnover"),
                top10_concentration=sub.get("top10_concentration"),
                hhi=sub.get("hhi"),
            )

        full = _stats("full_sample", samples["full_sample"])
        in_sample = _stats("in_sample", samples.get("in_sample"))
        oos = _stats("out_of_sample", samples.get("out_of_sample"))

        yearly = yearly_table(samples["full_sample"], trading_days_per_year=cfg.regression.trading_days_per_year)
        monthly = monthly_table(samples["full_sample"], trading_days_per_year=cfg.regression.trading_days_per_year)

        # 滚动指标: 年化收益 / 波动 / Sharpe / IR, 252 日窗口
        ppy = cfg.regression.trading_days_per_year
        win = 252
        rolling = pd.DataFrame(index=frame.index)
        if len(frame) > win:
            net = frame["portfolio_net_return"].astype("float64")
            excess = frame["excess_return"].astype("float64")
            rolling["annual_return"] = net.rolling(win, min_periods=120).mean() * ppy
            rolling["annual_volatility"] = net.rolling(win, min_periods=120).std(ddof=1) * np.sqrt(ppy)
            rolling["sharpe"] = rolling["annual_return"] / rolling["annual_volatility"]
            te = excess.rolling(win, min_periods=120).std(ddof=1) * np.sqrt(ppy)
            er = excess.rolling(win, min_periods=120).mean() * ppy
            rolling["tracking_error"] = te
            rolling["information_ratio"] = er / te.where(te > 0)
        from qbt.analytics.returns import drawdown_table

        drawdown = drawdown_table(frame["portfolio_nav"], top_n=10)

        definitions = {
            "turnover": "实际成交单边换手率 = (买入成交额 + 卖出成交额) / (2 × 期初净资产)",
            "excess_return": "组合费后日收益 - 指数日收益 (算术)",
            "excess_nav": "组合费后净值 / 基准净值, 几何超额口径",
            "sharpe": "(年化收益 - rf) / 年化波动",
            "information_ratio": "年化算术超额 / 跟踪误差",
            "cost_erosion_ratio": "(毛年化收益 - 净年化收益) / |毛组合相对基准的年化超额|",
        }
        from qbt.contracts.reports import PortfolioPerformanceReport

        return PortfolioPerformanceReport(
            full_sample=full,
            in_sample=in_sample,
            out_of_sample=oos,
            yearly=yearly,
            monthly=monthly,
            rolling=rolling,
            drawdown_table=drawdown,
            definitions=definitions,
        )

    @staticmethod
    def _build_constraint_reports(
        cfg: ConstraintConfig,
        actual_weights: pd.DataFrame,
        cash_ledger: pd.DataFrame,
        unfilled_summary: pd.DataFrame,
        fills: pd.DataFrame,
    ) -> tuple[PortfolioConstraintReport, ...]:
        reports: list[PortfolioConstraintReport] = []
        rebalance = cash_ledger.get("is_rebalance", pd.Series(False, index=cash_ledger.index))
        active_dates = cash_ledger.index
        if rebalance.astype(bool).any():
            first_active = rebalance.astype(bool).to_numpy().argmax()
            active_dates = cash_ledger.index[first_active:]
        actual_eval = actual_weights.reindex(active_dates)
        ledger_eval = cash_ledger.reindex(active_dates)
        w = actual_eval.to_numpy(dtype="float64")
        w_sorted = np.sort(np.where(w > 0, w, 0.0), axis=1)[:, ::-1]

        total_weight = actual_eval.sum(axis=1) + ledger_eval["cash_ratio"]
        full_investment_violations = (total_weight - 1.0).abs() > 1e-9
        full_violation_rows = pd.DataFrame(
            {
                "observed": total_weight[full_investment_violations],
                "limit": 1.0,
                "absolute_error": (total_weight[full_investment_violations] - 1.0).abs(),
            }
        ).reset_index()
        reports.append(
            PortfolioConstraintReport(
                constraint="full_investment",
                enabled=cfg.enforce_full_investment,
                limit=1.0,
                n_checked=len(actual_eval),
                n_violations=int(full_investment_violations.sum()),
                max_observed=float((total_weight - 1.0).abs().max()),
                action="account_identity_enforced",
                violations=full_violation_rows,
            )
        )

        # 单票上限
        max_w = w_sorted[:, 0] if w_sorted.shape[1] else np.array([0.0])
        max_mask = actual_eval > cfg.max_single_weight + 1e-9
        max_violation_rows = (
            actual_eval.where(max_mask).stack().dropna().rename("observed").reset_index()
        )
        if not max_violation_rows.empty:
            max_violation_rows["limit"] = cfg.max_single_weight
            max_violation_rows["excess"] = (
                max_violation_rows["observed"] - cfg.max_single_weight
            )
        reports.append(
            PortfolioConstraintReport(
                constraint="max_single_weight",
                enabled=True,
                limit=cfg.max_single_weight,
                n_checked=len(actual_eval),
                n_violations=len(max_violation_rows),
                max_observed=float(max_w.max()) if len(max_w) else 0.0,
                action="target_capped; post_close_drift_or_unfilled_reported",
                violations=max_violation_rows,
            )
        )

        # 最少持股
        n_holdings = (w > 1e-9).sum(axis=1)
        min_mask = n_holdings < cfg.min_holdings
        min_violation_rows = pd.DataFrame(
            {
                "date": actual_eval.index[min_mask],
                "observed": n_holdings[min_mask],
                "limit": cfg.min_holdings,
            }
        )
        reports.append(
            PortfolioConstraintReport(
                constraint="min_holdings",
                enabled=True,
                limit=float(cfg.min_holdings),
                n_checked=len(actual_eval),
                n_violations=int((n_holdings < cfg.min_holdings).sum()),
                max_observed=float(n_holdings.min()),
                action="warn_if_below",
                violations=min_violation_rows,
            )
        )

        # 最大现金比例
        cash_ratio = ledger_eval.get("cash_ratio", pd.Series(0.0, index=ledger_eval.index))
        cash_mask = cash_ratio > cfg.max_cash_ratio + 1e-9
        cash_violation_rows = pd.DataFrame(
            {
                "date": cash_ratio.index[cash_mask],
                "observed": cash_ratio[cash_mask].to_numpy(),
                "limit": cfg.max_cash_ratio,
            }
        )
        reports.append(
            PortfolioConstraintReport(
                constraint="max_cash_ratio",
                enabled=True,
                limit=cfg.max_cash_ratio,
                n_checked=len(ledger_eval),
                n_violations=int((cash_ratio > cfg.max_cash_ratio + 1e-9).sum()),
                max_observed=float(cash_ratio.max()),
                action="warn_if_above",
                violations=cash_violation_rows,
            )
        )

        # ADV 参与率 (从成交汇总看)
        adv_bindings = 0
        if not unfilled_summary.empty and "reason" in unfilled_summary.columns:
            adv_bindings = int((unfilled_summary["reason"] == "adv_cap").sum())
        executed = fills[fills["filled_quantity"] > 0] if not fills.empty else fills
        adv_observed = (
            executed["adv_participation"].dropna()
            if not executed.empty and "adv_participation" in executed
            else pd.Series(dtype="float64")
        )
        adv_mask = adv_observed > cfg.max_adv_participation + 1e-9
        adv_violation_rows = (
            executed.loc[adv_mask.index[adv_mask]].copy()
            if len(adv_observed) and adv_mask.any()
            else pd.DataFrame()
        )
        reports.append(
            PortfolioConstraintReport(
                constraint="max_adv_participation",
                enabled=True,
                limit=cfg.max_adv_participation,
                n_checked=len(adv_observed),
                n_violations=len(adv_violation_rows),
                max_observed=float(adv_observed.max()) if len(adv_observed) else np.nan,
                action=f"partial_fill; cap_bindings={adv_bindings}",
                violations=adv_violation_rows,
            )
        )

        # 行业偏离 / 风格暴露: 无数据, 仅监控
        reports.append(
            PortfolioConstraintReport(
                constraint="max_turnover",
                enabled=cfg.max_turnover is not None,
                limit=cfg.max_turnover,
                n_checked=len(ledger_eval),
                n_violations=(
                    int((ledger_eval["turnover"] > float(cfg.max_turnover) + 1e-9).sum())
                    if cfg.max_turnover is not None else 0
                ),
                max_observed=float(ledger_eval["turnover"].max()),
                action="target_transition_scaled_and_execution_capped",
                violations=(
                    pd.DataFrame({
                        "date": ledger_eval.index[
                            ledger_eval["turnover"] > float(cfg.max_turnover) + 1e-9
                        ],
                        "observed": ledger_eval.loc[
                            ledger_eval["turnover"] > float(cfg.max_turnover) + 1e-9,
                            "turnover",
                        ].to_numpy(),
                        "limit": cfg.max_turnover,
                    }) if cfg.max_turnover is not None else pd.DataFrame()
                ),
            )
        )

        reports.append(
            PortfolioConstraintReport(
                constraint="max_industry_deviation",
                enabled=False,
                limit=cfg.max_industry_deviation,
                n_checked=0,
                n_violations=0,
                max_observed=np.nan,
                action="not_implemented_no_data",
            )
        )
        reports.append(
            PortfolioConstraintReport(
                constraint="max_active_style_exposure",
                enabled=False,
                limit=cfg.max_active_style_exposure,
                n_checked=0,
                n_violations=0,
                max_observed=np.nan,
                action="monitor_only",
            )
        )
        return tuple(reports)

    @staticmethod
    def _build_diagnostics(
        cfg: LongOnlyFactorBacktestConfig,
        resolved: ResolvedLongOnlyBacktestData,
        execution: ExecutionOutput,
        return_frame: pd.DataFrame,
        factor: FactorFrame,
        exclusion_reasons: pd.DataFrame,
    ) -> PortfolioBacktestDiagnostics:
        identity = execution.accounting_identity
        residual_bps = identity.get("residual_bps_of_nav", pd.Series(dtype="float64"))
        raw_disclosures = resolved.notes.get("warnings", ())
        disclosures = (
            tuple(item for item in raw_disclosures if isinstance(item, str))
            if isinstance(raw_disclosures, (list, tuple))
            else ()
        )
        return PortfolioBacktestDiagnostics(
            timeline={
                "signal_time": cfg.clock.signal_time,
                "order_lag_days": cfg.clock.order_lag_days,
                "fill_lag_days": cfg.clock.fill_lag_days,
                "return_lag_days": cfg.clock.return_lag_days,
                "rebalance_frequency": cfg.rebalance_frequency,
                "fill_price_field": cfg.execution.fill_price_field,
            },
            data_quality={
                "factor_coverage": factor.metadata.get("coverage_ratio"),
                "benchmark_basis": resolved.benchmark_basis,
                "n_rebalance_dates": len(resolved.rebalance_dates),
                "n_trading_days": len(resolved.prices.dates),
                "n_assets": len(resolved.prices.assets),
                "price_missing_members": resolved.notes.get("price_missing_members", {}),
            },
            exclusion_reasons=exclusion_reasons,
            unfilled_summary=execution.unfilled_summary,
            accounting_identity=identity,
            warnings=tuple(
                [
                    f"账户恒等式最大残差: {float(residual_bps.max()):.4f} bps"
                    if residual_bps.notna().any()
                    else ""
                ]
            ),
            disclosures=disclosures,
        )
