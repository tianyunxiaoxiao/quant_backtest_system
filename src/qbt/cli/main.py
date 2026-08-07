"""命令行入口。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

import qbt
from qbt.data.ingest_index import INDEX_SPECS, ingest_index_membership
from qbt.data.panel import load_price_panel
from qbt.data.portal import PortalConfig
from qbt.factors.demo import DEMO_FACTOR_SPECS, build_demo_factor
from qbt.reporting import LongOnlyFactorReporter


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="指数内多头因子回测")
    p.add_argument("--factor", required=True, choices=sorted(DEMO_FACTOR_SPECS),
                   help="演示因子 ID")
    p.add_argument("--index", default="000905.SH", choices=sorted(INDEX_SPECS),
                   help="目标指数 ID")
    p.add_argument("--start", default="2018-01-01", help="回测开始日期 (YYYY-MM-DD)")
    p.add_argument("--end", default="2026-03-31", help="回测结束日期 (YYYY-MM-DD)")
    p.add_argument("--freq", default="daily", choices=["daily", "weekly", "monthly"],
                   help="调仓频率")
    p.add_argument("--warehouse", default=None, help="Parquet 仓库目录 (默认: 项目 warehouse)")
    p.add_argument("--index-dir", default=None, help="指数成分目录 (默认: 父目录 指数月度成分股)")
    p.add_argument("--output", default=None, help="产物输出目录 (默认: artifacts/lof_{run_id})")
    p.add_argument("--capital", type=float, default=100_000_000.0, help="初始资金")
    p.add_argument("--no-report", action="store_true", help="只跑回测, 不生成报告")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    project_root = Path(__file__).resolve().parents[3]
    warehouse = Path(args.warehouse) if args.warehouse else project_root / "warehouse"
    index_dir = Path(args.index_dir) if args.index_dir else project_root.parent / "指数月度成分股"

    portal = qbt.PortfolioDataPortal(
        PortalConfig(warehouse_dir=warehouse, index_source_dir=index_dir, style_warmup_days=300)
    )
    monthly, _ = ingest_index_membership(index_dir, INDEX_SPECS[args.index])
    assets = sorted(monthly["asset_id"].unique())
    panel = load_price_panel(
        warehouse,
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
    factor = build_demo_factor(args.factor, sources, data_version="cli", code_version="cli")

    config = qbt.LongOnlyFactorBacktestConfig(
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        rebalance_frequency=args.freq,
        initial_capital=args.capital,
    )
    request = qbt.LongOnlyFactorBacktestRequest(factor=factor, index_id=args.index, config=config)
    backtester = qbt.LongOnlyFactorBacktester(portal)
    result = backtester.run(request)

    print(f"run_id: {result.run_manifest.run_id}")
    print(f"交易日: {len(result.portfolio_equity)}")
    print(f"组合累计收益: {result.portfolio_equity.iloc[-1] - 1:.2%}")
    print(f"基准累计收益: {result.benchmark_equity.iloc[-1] - 1:.2%}")
    print(f"超额累计收益: {result.excess_equity.iloc[-1] - 1:.2%}")
    print(f"年化 Alpha: {result.alpha_beta.alpha_annual:.2%}, Beta: {result.alpha_beta.beta:.3f}")
    print(f"账户恒等式最大残差: {result.diagnostics.accounting_identity['residual_bps_of_nav'].abs().max():.6f} bps")

    if not args.no_report:
        output_dir = Path(args.output) if args.output else project_root / "artifacts" / result.run_manifest.run_id
        reporter = LongOnlyFactorReporter()
        report_request = qbt.LongOnlyFactorReportRequest(backtest=result, output_dir=output_dir)
        report_result = reporter.render(report_request)
        print(f"报告已生成: {output_dir}")
        print(f"产物数量: {len(report_result.all_artifacts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
