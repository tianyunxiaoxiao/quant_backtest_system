"""命令行入口。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

import qbt
from qbt.data.ingest_index import ALL_A_INDEX_ID, INDEX_SPECS, ingest_index_membership
from qbt.data.panel import load_price_panel
from qbt.data.portal import PortalConfig
from qbt.factors.demo import DEMO_FACTOR_SPECS, build_demo_factor
from qbt.factors.values import load_factor_values
from qbt.reporting import LongOnlyFactorReporter


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="指数内多头因子回测")
    p.add_argument(
        "--factor",
        default=None,
        choices=sorted(DEMO_FACTOR_SPECS),
        help="演示因子 ID (与 --factor-values 二选一)",
    )
    p.add_argument(
        "--factor-values",
        default=None,
        help="外部因子值 parquet 路径 (宽表: 日期行 x asset_id 列, 与 --factor 二选一)",
    )
    p.add_argument(
        "--factor-id", default=None, help="外部因子值回测使用的 factor_id (默认取文件名去扩展名)"
    )
    p.add_argument(
        "--factor-direction",
        type=int,
        default=1,
        choices=(1, -1),
        help="外部因子值方向: +1 越大越好 (默认), -1 越小越好; 回测前声明, 不许事后翻转",
    )
    p.add_argument("--factor-desc", default=None, help="外部因子值描述 (默认自动生成)")
    p.add_argument(
        "--index",
        default=None,
        choices=[ALL_A_INDEX_ID, *sorted(INDEX_SPECS)],
        help=f"目标指数 ID (省略时使用 {ALL_A_INDEX_ID}: 流动性过滤后的非 ST A 股)",
    )
    p.add_argument("--start", default="2018-01-01", help="回测开始日期 (YYYY-MM-DD)")
    p.add_argument("--end", default="2026-03-31", help="回测结束日期 (YYYY-MM-DD)")
    p.add_argument(
        "--freq", default="daily", choices=["daily", "weekly", "monthly"], help="调仓频率"
    )
    p.add_argument(
        "--warehouse", default=None, help="Parquet 仓库目录 (默认: 项目 warehouse_rqdata)"
    )
    p.add_argument(
        "--index-dir",
        default=None,
        help="指数成分目录 (默认: 项目 data/index_membership_source)",
    )
    p.add_argument("--output", default=None, help="产物输出目录 (默认: artifacts/lof_{run_id})")
    p.add_argument("--capital", type=float, default=100_000_000.0, help="初始资金")
    p.add_argument("--no-report", action="store_true", help="只跑回测, 不生成报告")
    args = p.parse_args(argv)
    if bool(args.factor) == bool(args.factor_values):
        p.error("--factor 与 --factor-values 必须且只能提供一个")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    project_root = Path(__file__).resolve().parents[3]
    warehouse = Path(args.warehouse) if args.warehouse else project_root / "warehouse_rqdata"
    index_dir = (
        Path(args.index_dir)
        if args.index_dir
        else project_root / "data" / "index_membership_source"
    )

    portal = qbt.PortfolioDataPortal(
        PortalConfig(warehouse_dir=warehouse, index_source_dir=index_dir, style_warmup_days=300)
    )
    if args.index in (None, ALL_A_INDEX_ID):
        index_id = ALL_A_INDEX_ID
    else:
        index_id = args.index

    if args.factor_values:
        # 外部因子值: 直接构建 FactorFrame, 无需加载行情面板计算公式因子。
        factor = load_factor_values(
            args.factor_values,
            factor_id=args.factor_id or Path(args.factor_values).stem,
            direction=args.factor_direction,
            description=args.factor_desc or "",
            data_version="cli",
            code_version="cli",
        )
    else:
        if index_id == ALL_A_INDEX_ID:
            assets = sorted(
                {
                    str(asset)
                    for path in (warehouse / "daily_prices").glob("*.parquet")
                    for asset in pd.read_parquet(path, columns=["asset_id"])["asset_id"]
                    .dropna()
                    .unique()
                }
            )
        else:
            monthly, _ = ingest_index_membership(index_dir, INDEX_SPECS[index_id])
            assets = sorted(monthly["asset_id"].unique())
        calendar = portal.trading_calendar()
        requested_end = pd.Timestamp(args.end)
        panel = load_price_panel(
            warehouse,
            assets=assets,
            start=calendar[0],
            end=min(requested_end, calendar[-1]),
            trading_days=calendar,
        )
        sources = {
            "adj_close": panel.wide["adj_close"],
            "float_mktcap": panel.wide.get("float_mktcap"),
            "turnover_rate": panel.wide.get("turnover_rate"),
            "pb": panel.wide.get("pb"),
        }
        factor = build_demo_factor(args.factor, sources, data_version="cli", code_version="cli")

    config = qbt.LongOnlyFactorBacktestConfig(
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        rebalance_frequency=args.freq,
        initial_capital=args.capital,
    )
    request = qbt.LongOnlyFactorBacktestRequest(factor=factor, index_id=index_id, config=config)
    backtester = qbt.LongOnlyFactorBacktester(portal)
    result = backtester.run(request)

    print(f"run_id: {result.run_manifest.run_id}")
    print(f"交易日: {len(result.portfolio_equity)}")
    print(f"组合累计收益: {result.portfolio_equity.iloc[-1] - 1:.2%}")
    print(f"基准累计收益: {result.benchmark_equity.iloc[-1] - 1:.2%}")
    print(f"超额累计收益: {result.excess_equity.iloc[-1] - 1:.2%}")
    print(f"年化 Alpha: {result.alpha_beta.alpha_annual:.2%}, Beta: {result.alpha_beta.beta:.3f}")
    print(
        f"账户恒等式最大残差: {result.diagnostics.accounting_identity['residual_bps_of_nav'].abs().max():.6f} bps"
    )

    if not args.no_report:
        output_dir = (
            Path(args.output)
            if args.output
            else project_root / "artifacts" / result.run_manifest.run_id
        )
        reporter = LongOnlyFactorReporter()
        report_request = qbt.LongOnlyFactorReportRequest(backtest=result, output_dir=output_dir)
        report_result = reporter.render(report_request)
        print(f"报告已生成: {output_dir}")
        print(f"产物数量: {len(report_result.all_artifacts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
