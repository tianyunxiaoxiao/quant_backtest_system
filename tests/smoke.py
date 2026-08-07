"""Smoke test: 在短窗口内跑通一个演示因子。"""

from pathlib import Path

import pandas as pd

import qbt
from qbt.data.ingest_index import INDEX_SPECS, ingest_index_membership
from qbt.data.panel import load_price_panel
from qbt.data.portal import PortalConfig
from qbt.factors.demo import build_demo_factor

ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = ROOT / "warehouse"
INDEX_DIR = ROOT.parent / "指数月度成分股"

portal = qbt.PortfolioDataPortal(
    PortalConfig(
        warehouse_dir=WAREHOUSE,
        index_source_dir=INDEX_DIR,
        style_warmup_days=300,
    )
)

# 用指数成分代码构造反转因子
monthly, _ = ingest_index_membership(INDEX_DIR, INDEX_SPECS["000905.SH"])
assets = sorted(monthly["asset_id"].unique())
print("index unique assets:", len(assets))

panel = load_price_panel(
    WAREHOUSE,
    assets=assets,
    start=pd.Timestamp("2019-01-01"),
    end=pd.Timestamp("2024-04-01"),
    trading_days=portal.trading_calendar(),
)
print("panel assets:", len(panel.assets), "days:", len(panel.trading_days))

factor = build_demo_factor(
    "reversal_20d",
    {"adj_close": panel.wide["adj_close"]},
    data_version="smoke",
    code_version="smoke",
)
print("factor coverage:", factor.metadata["coverage_ratio"])

config = qbt.LongOnlyFactorBacktestConfig(
    start_date=pd.Timestamp("2019-06-01").date(),
    end_date=pd.Timestamp("2019-09-30").date(),
    rebalance_frequency="monthly",
)
request = qbt.LongOnlyFactorBacktestRequest(factor=factor, index_id="000905.SH", config=config)

backtester = qbt.LongOnlyFactorBacktester(portal)
result = backtester.run(request)
print("run_id:", result.run_manifest.run_id)
print("days:", len(result.portfolio_equity))
print("net_return total:", result.portfolio_equity.iloc[-1] - 1)
print("benchmark total:", result.benchmark_equity.iloc[-1] - 1)
print("alpha annual:", result.alpha_beta.alpha_annual, "beta:", result.alpha_beta.beta)
print("accounting residual max bps:", result.diagnostics.accounting_identity["residual_bps_of_nav"].max())
print("OK")
