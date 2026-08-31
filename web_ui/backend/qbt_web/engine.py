"""Thin shim around the original qbt backtest engine.

This module imports qbt from the original project by adding its src directory
to sys.path. The original project is never modified.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from time import perf_counter
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
from qbt.factors.values import inspect_factor_values as inspect_factor_values  # noqa: E402
from qbt.factors.values import load_factor_values  # noqa: E402
from qbt.factors.values import load_target_weights  # noqa: E402
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
    defaults = [
        {"index_id": ALL_A_INDEX_ID, "name": "流动性过滤后的非 ST A 股"},
        {"index_id": "000300.SH", "name": "沪深300"},
        {"index_id": "000905.SH", "name": "中证500"},
        {"index_id": "000852.SH", "name": "中证1000"},
    ]
    manifest_path = settings.warehouse_dir / "rqdata_warehouse_manifest.json"
    if not manifest_path.is_file():
        return defaults
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"米筐仓库清单无法读取: {manifest_path}") from exc
    return [
        {"index_id": str(item["index_id"]), "name": str(item["name"])}
        for item in manifest.get("supported_indexes", [])
        if isinstance(item, dict) and item.get("index_id") and item.get("name")
    ]


def _build_factor(
    factor_id: str, sources: dict[str, pd.DataFrame], lookback: int | None
) -> qbt.FactorFrame:
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
        values = build_demo_factor(
            factor_id, sources, data_version="web", code_version="web"
        ).values
    elif factor_id == "size_ln_float_mktcap":
        values = build_demo_factor(
            factor_id, sources, data_version="web", code_version="web"
        ).values
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
        "min_commission": params["min_commission"],
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
    total_started = perf_counter()
    stage_started = total_started
    timings: dict[str, float] = {}

    def mark(name: str) -> None:
        nonlocal stage_started
        now = perf_counter()
        timings[name] = round(now - stage_started, 6)
        stage_started = now

    output_dir.mkdir(parents=True, exist_ok=True)

    portal = qbt.PortfolioDataPortal(
        PortalConfig(
            warehouse_dir=settings.warehouse_dir,
            index_source_dir=settings.index_source_dir,
            style_warmup_days=300,
        )
    )
    mark("portal_init")

    direct_mode = params.get("portfolio_input_mode") == "direct_target_weights"
    config = qbt.LongOnlyFactorBacktestConfig(
        start_date=params["start_date"],
        end_date=params["end_date"],
        rebalance_frequency=params["rebalance_frequency"],
        initial_capital=params["initial_capital"],
        selection_fraction=1.0 if direct_mode else params["selection_fraction"],
        weighting_method="equal_weight" if direct_mode else params["weighting_method"],
        constraints=qbt.ConstraintConfig(
            max_single_weight=1.0 if direct_mode else params["max_single_weight"],
            force_sell_index_exits=True,
        ),
        costs=_build_cost_config(params),
        execution=qbt.ExecutionConfig(
            fill_price_field=params["fill_price_field"],
        ),
    )

    factor_values_path = params.get("factor_values_path")
    index_id = params["index_id"]
    resolved_index_id = ALL_A_INDEX_ID if index_id in (None, ALL_A_INDEX_ID) else index_id
    preloaded_panel = None

    if factor_values_path:
        # 外部导入因子值: 直接构建 FactorFrame, 不加载行情面板计算公式因子。
        import_metadata = {
            "source": "web imported target weights" if direct_mode else "web imported factor values",
            "imported_name": params.get("factor_values_name"),
            "imported_source": params.get("factor_values_source"),
        }
        factor = (
            load_target_weights(
                factor_values_path,
                portfolio_id=params["factor_id"],
                description=str(params.get("factor_values_name") or ""),
                data_version="web-import",
                code_version="web",
                metadata=import_metadata,
            )
            if direct_mode
            else load_factor_values(
                factor_values_path,
                factor_id=params["factor_id"],
                direction=int(params.get("factor_direction") or 1),
                description=str(params.get("factor_values_name") or ""),
                data_version="web-import",
                code_version="web",
                metadata=import_metadata,
            )
        )
    else:
        if resolved_index_id == ALL_A_INDEX_ID:
            assets = sorted(
                {
                    str(asset)
                    for path in (settings.warehouse_dir / "daily_prices").glob("*.parquet")
                    for asset in pd.read_parquet(path, columns=["asset_id"])["asset_id"]
                    .dropna()
                    .unique()
                }
            )
        else:
            monthly, _ = ingest_index_membership(
                settings.index_source_dir, INDEX_SPECS[resolved_index_id]
            )
            assets = sorted(monthly["asset_id"].unique())
        calendar = portal.trading_calendar()
        requested_start = pd.Timestamp(params["start_date"])
        start_pos = int(calendar.searchsorted(requested_start))
        factor_warmup = int(params.get("lookback") or DEMO_FACTOR_SPECS[params["factor_id"]].warmup_days)
        warmup_pos = max(start_pos - max(300, factor_warmup), 0)
        panel = load_price_panel(
            settings.warehouse_dir,
            assets=assets,
            start=calendar[warmup_pos],
            end=min(pd.Timestamp(params["end_date"]), calendar[-1]),
            trading_days=calendar,
        )
        preloaded_panel = panel
        sources = {
            "adj_close": panel.wide["adj_close"],
            "float_mktcap": panel.wide.get("float_mktcap"),
            "turnover_rate": panel.wide.get("turnover_rate"),
            "pb": panel.wide.get("pb"),
        }
        factor = _build_factor(params["factor_id"], sources, params.get("lookback"))
    mark("factor_and_panel_prepare")

    request = qbt.LongOnlyFactorBacktestRequest(
        factor=factor, index_id=resolved_index_id, config=config
    )
    backtester = qbt.LongOnlyFactorBacktester(
        portal,
        backtester_config=qbt.BacktesterConfig(
            repo_root=settings.qbt_project_root,
            run_id=run_id,
            preloaded_panel=preloaded_panel,
            direct_target_weights=factor.values if direct_mode else None,
            timing_sink=timings,
        ),
    )
    result = backtester.run(request)
    mark("backtester_return")

    # Web 页面使用数据产物实时绘图，无需在请求尾段同步渲染 14 张静态图。
    reporter = LongOnlyFactorReporter(
        qbt.PortfolioReportConfig(write_charts=False, verify_roundtrip=False)
    )
    report_request = qbt.LongOnlyFactorReportRequest(backtest=result, output_dir=output_dir)
    reporter.render(report_request)
    mark("report_render")
    timings["web_total"] = round(perf_counter() - total_started, 6)
    (output_dir / "performance_timing.json").write_text(
        json.dumps(timings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

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
        "portfolio_input_mode": "direct_target_weights" if direct_mode else "factor_scores",
        "performance_timing_seconds": timings,
    }
