"""Thin shim around the original qbt backtest engine.

This module imports qbt from the original project by adding its src directory
to sys.path. The original project is never modified.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from qbt_web.config import settings

# Add original qbt src to path without touching it.
_QBT_SRC = str(settings.qbt_src)
if _QBT_SRC not in sys.path:
    sys.path.insert(0, _QBT_SRC)

import qbt  # noqa: E402
from qbt.contracts.config import CostRate  # noqa: E402
from qbt.data.ingest_index import ALL_A_INDEX_ID, INDEX_SPECS, ingest_index_membership  # noqa: E402
from qbt.data.panel import load_price_panel  # noqa: E402
from qbt.data.portal import PortalConfig  # noqa: E402
from qbt.factors.demo import DEMO_FACTOR_SPECS, build_demo_factor  # noqa: E402
from qbt.factors.values import inspect_factor_values, load_factor_values  # noqa: E402
from qbt.reporting import LongOnlyFactorReporter  # noqa: E402


def get_demo_factors() -> dict[str, Any]:
    return {
        fid: {
            "factor_id": spec.factor_id,
            "direction": spec.direction,
            "description": spec.description,
            "warmup_days": spec.warmup_days,
            "inputs": list(spec.inputs),
        }
        for fid, spec in DEMO_FACTOR_SPECS.items()
    }


def get_indexes() -> list[dict[str, str]]:
    return [
        {"index_id": ALL_A_INDEX_ID, "name": "全A等权"},
        {"index_id": "000300.SH", "name": "沪深300"},
        {"index_id": "000905.SH", "name": "中证500"},
        {"index_id": "000852.SH", "name": "中证1000"},
    ]


def _build_factor(factor_id: str, sources: dict[str, pd.DataFrame], lookback: int | None) -> qbt.FactorFrame:
    spec = DEMO_FACTOR_SPECS[factor_id]
    if factor_id == "reversal_20d":
        from qbt.factors.demo import build_reversal_20d
        values = build_reversal_20d(sources["adj_close"], window=lookback or 20)
    elif factor_id == "turnover_21d":
        from qbt.factors.demo import build_turnover_21d
        values = build_turnover_21d(sources["turnover_rate"], window=lookback or 21)
    elif factor_id == "volatility_252d":
        from qbt.factors.demo import build_volatility_252d
        values = build_volatility_252d(sources["adj_close"], window=lookback or 252)
    elif factor_id == "bp_1_over_pb":
        values = build_demo_factor(factor_id, sources, data_version="web", code_version="web").values
    elif factor_id == "size_ln_float_mktcap":
        values = build_demo_factor(factor_id, sources, data_version="web", code_version="web").values
    else:
        raise ValueError(f"未知因子: {factor_id}")

    if factor_id in ("reversal_20d", "turnover_21d", "volatility_252d"):
        from qbt.data.hashing import hash_frame
        return qbt.FactorFrame(
            values=values,
            factor_id=factor_id,
            direction=spec.direction,
            description=spec.description,
            missing_policy="exclude_from_eligible",
            data_version="web",
            content_hash=hash_frame(values),
            code_version="web",
            metadata={
                "warmup_days": lookback or spec.warmup_days,
                "inputs": list(spec.inputs),
                "coverage_ratio": round(float(values.notna().to_numpy().mean()), 6),
                "direction_locked_before_backtest": True,
                "source": "mentor A6 demo factor set",
            },
        )
    return build_demo_factor(factor_id, sources, data_version="web", code_version="web")


def _build_cost_config(params: dict[str, Any]) -> qbt.CostConfig:
    """按表单费率构建成本配置。

    佣金与滑点直接透传; 印花税/过户费为可选覆盖 —— 提供时用单一档位
    schedule (全期一个费率), 未提供时保留 qbt 官方时变档位
    (过户费 2022-04-29 起 0.001%, 印花税 2023-08-28 起 0.05%)。
    """
    kwargs: dict[str, Any] = {
        "commission_rate": params["commission_rate"],
        "slippage_bps": params["slippage_bps"],
    }
    stamp_rate = params.get("stamp_duty_rate")
    if stamp_rate is not None:
        kwargs["stamp_duty_schedule"] = (CostRate(date(1900, 1, 1), float(stamp_rate)),)
    transfer_rate = params.get("transfer_fee_rate")
    if transfer_rate is not None:
        kwargs["transfer_fee_schedule"] = (CostRate(date(1900, 1, 1), float(transfer_rate)),)
    return qbt.CostConfig(**kwargs)


def run_backtest(run_id: str, params: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """Execute a qbt backtest and write artifacts to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)

    portal = qbt.PortfolioDataPortal(
        PortalConfig(
            warehouse_dir=settings.warehouse_dir,
            index_source_dir=settings.index_source_dir,
            style_warmup_days=300,
        )
    )

    factor_values_path = params.get("factor_values_path")
    index_id = params["index_id"]
    resolved_index_id = ALL_A_INDEX_ID if index_id in (None, ALL_A_INDEX_ID) else index_id

    if factor_values_path:
        # 外部导入因子值: 直接构建 FactorFrame, 不加载行情面板计算公式因子。
        factor = load_factor_values(
            factor_values_path,
            factor_id=params["factor_id"],
            direction=int(params.get("factor_direction") or 1),
            description=str(params.get("factor_values_name") or ""),
            data_version="web-import",
            code_version="web",
            metadata={
                "source": "web imported factor values",
                "imported_name": params.get("factor_values_name"),
                "imported_source": params.get("factor_values_source"),
            },
        )
    else:
        if resolved_index_id == ALL_A_INDEX_ID:
            assets = sorted(
                {
                    str(asset)
                    for path in (settings.warehouse_dir / "daily_prices").glob("*.parquet")
                    for asset in pd.read_parquet(path, columns=["asset_id"])["asset_id"].dropna().unique()
                }
            )
        else:
            monthly, _ = ingest_index_membership(settings.index_source_dir, INDEX_SPECS[resolved_index_id])
            assets = sorted(monthly["asset_id"].unique())
        panel = load_price_panel(
            settings.warehouse_dir,
            assets=assets,
            start=pd.Timestamp("2015-01-01"),
            end=pd.Timestamp("2026-04-07"),
            trading_days=portal.trading_calendar(),
        )
        sources = {
            "adj_close": panel.wide["adj_close"],
            "float_mktcap": panel.wide.get("float_mktcap"),
            "turnover_rate": panel.wide.get("turnover_rate"),
            "pb": panel.wide.get("pb"),
        }
        factor = _build_factor(params["factor_id"], sources, params.get("lookback"))

    config = qbt.LongOnlyFactorBacktestConfig(
        start_date=params["start_date"],
        end_date=params["end_date"],
        rebalance_frequency=params["rebalance_frequency"],
        initial_capital=params["initial_capital"],
        selection_fraction=params["selection_fraction"],
        weighting_method=params["weighting_method"],
        constraints=qbt.ConstraintConfig(
            max_single_weight=params["max_single_weight"],
            force_sell_index_exits=True,
        ),
        costs=_build_cost_config(params),
        execution=qbt.ExecutionConfig(
            fill_price_field=params["fill_price_field"],
        ),
    )

    request = qbt.LongOnlyFactorBacktestRequest(
        factor=factor, index_id=resolved_index_id, config=config
    )
    backtester = qbt.LongOnlyFactorBacktester(portal)
    result = backtester.run(request)

    reporter = LongOnlyFactorReporter()
    report_request = qbt.LongOnlyFactorReportRequest(backtest=result, output_dir=output_dir)
    reporter.render(report_request)

    perf = result.performance.full_sample
    return {
        "run_id": result.run_manifest.run_id,
        "factor_id": result.run_manifest.factor_id,
        "index_id": result.run_manifest.index_id,
        "total_return": perf.total_return,
        "annual_return": perf.annual_return,
        "annual_volatility": perf.annual_volatility,
        "sharpe": perf.sharpe,
        "max_drawdown": perf.max_drawdown,
        "benchmark_total_return": perf.benchmark_total_return,
        "excess_total_return_geometric": perf.excess_total_return_geometric,
        "information_ratio": perf.information_ratio,
        "alpha_annual": result.alpha_beta.alpha_annual,
        "beta": result.alpha_beta.beta,
        "n_days": perf.n_days,
    }
