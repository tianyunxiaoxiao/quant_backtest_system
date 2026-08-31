"""集成测试: 端到端回测与报告器一致性。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import qbt
from qbt.data.ingest_index import INDEX_SPECS, ingest_index_membership
from qbt.data.panel import load_price_panel
from qbt.data.portal import PortalConfig
from qbt.factors.demo import build_demo_factor
from qbt.reporting import LongOnlyFactorReporter
from qbt.reporting import load_backtest_artifacts
from qbt.data.hashing import hash_file


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _require_legacy_integration_data(root: Path) -> tuple[Path, Path]:
    warehouse = root / "warehouse"
    index_dir = root.parent / "指数月度成分股"
    has_prices = (warehouse / "daily_prices").is_dir()
    has_index = index_dir.is_dir() and any(index_dir.glob("*.xlsx"))
    if not (has_prices and has_index):
        pytest.skip("legacy real-data integration fixture is not installed")
    return warehouse, index_dir


def _make_backtest(
    *,
    factor_id: str = "reversal_20d",
    start: str = "2019-06-01",
    end: str = "2019-09-30",
    rebalance_frequency: str = "monthly",
    commission_rate: float = 0.00025,
    slippage_bps: float = 12.0,
    max_adv_participation: float = 0.10,
) -> qbt.LongOnlyFactorBacktestResult:
    root = _project_root()
    warehouse, index_dir = _require_legacy_integration_data(root)
    portal = qbt.PortfolioDataPortal(
        PortalConfig(warehouse_dir=warehouse, index_source_dir=index_dir, style_warmup_days=300)
    )
    monthly, _ = ingest_index_membership(index_dir, INDEX_SPECS["000905.SH"])
    assets = sorted(monthly["asset_id"].unique())
    panel = load_price_panel(
        warehouse,
        assets=assets,
        start=pd.Timestamp("2019-01-01"),
        end=pd.Timestamp("2024-04-01"),
        trading_days=portal.trading_calendar(),
    )
    factor = build_demo_factor(
        factor_id,
        {
            "adj_close": panel.wide["adj_close"],
            "float_mktcap": panel.wide["float_mktcap"],
            "turnover_rate": panel.wide["turnover_rate"],
            "pb": panel.wide["pb"],
        },
        data_version="integration",
        code_version="integration",
    )
    config = qbt.LongOnlyFactorBacktestConfig(
        start_date=pd.Timestamp(start).date(),
        end_date=pd.Timestamp(end).date(),
        rebalance_frequency=rebalance_frequency,
        costs=qbt.CostConfig(
            commission_rate=commission_rate,
            min_commission=0.0 if commission_rate == 0.0 else 5.0,
            slippage_bps=slippage_bps,
        ),
        constraints=qbt.ConstraintConfig(max_adv_participation=max_adv_participation),
    )
    request = qbt.LongOnlyFactorBacktestRequest(factor=factor, index_id="000905.SH", config=config)
    backtester = qbt.LongOnlyFactorBacktester(portal)
    return backtester.run(request)


@pytest.mark.slow
@pytest.mark.integration
def test_end_to_end_real_data():
    result = _make_backtest()
    assert len(result.portfolio_equity) > 50
    assert result.portfolio_equity.iloc[0] == 1.0
    # 账户恒等式残差应接近 0
    residual = result.diagnostics.accounting_identity["residual_bps_of_nav"].abs().max()
    assert residual < 1e-6
    # 必须有持仓
    assert result.actual_weights.abs().sum(axis=1).max() > 0.9


@pytest.mark.slow
@pytest.mark.integration
def test_reporting_does_not_mutate_result_and_reloaded_result_is_identical(tmp_path):
    result = _make_backtest()
    pre_hash = result.run_manifest.result_hash
    reporter = LongOnlyFactorReporter()
    out_dir = _project_root() / "artifacts" / "integration_test_report"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stale_unregistered.txt").write_text("stale", encoding="utf-8")
    request = qbt.LongOnlyFactorReportRequest(backtest=result, output_dir=out_dir)
    report_result = reporter.render(request)
    assert not (out_dir / "stale_unregistered.txt").exists()
    assert result.run_manifest.result_hash == pre_hash
    assert len(report_result.chart_artifacts) == 14
    markdown = (out_dir / "backtest_report.md").read_text(encoding="utf-8")
    for required in (
        "方法与时间线", "Sortino", "回撤持续/修复交易日", "Alpha p-value (OLS)",
        "风格暴露与超额收益关系", "未成交金额", "ADV 参与率", "选股排除汇总",
        "指标定义", "因子内容哈希",
    ):
        assert required in markdown

    reloaded = load_backtest_artifacts(out_dir)
    assert reloaded.run_manifest.result_hash == result.run_manifest.result_hash
    reload_dir = tmp_path / "reloaded_report"
    reloaded_report = reporter.render(
        qbt.LongOnlyFactorReportRequest(backtest=reloaded, output_dir=reload_dir)
    )
    assert (reload_dir / "backtest_report.md").read_bytes() == (
        out_dir / "backtest_report.md"
    ).read_bytes()
    assert (reload_dir / "backtest_report.json").read_bytes() == (
        out_dir / "backtest_report.json"
    ).read_bytes()
    original_charts = {
        path.name: hash_file(path) for path in (out_dir / "charts").glob("*.png")
    }
    reloaded_charts = {
        path.name: hash_file(path) for path in (reload_dir / "charts").glob("*.png")
    }
    assert reloaded_charts == original_charts
    assert len(reloaded_report.all_artifacts) == len(report_result.all_artifacts)
    manifest = json.loads((out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_uri"] == str(out_dir.resolve())

    configured_dir = tmp_path / "configured_report"
    configured = reporter.render(
        qbt.LongOnlyFactorReportRequest(
            backtest=result,
            output_dir=configured_dir,
            report_config=qbt.PortfolioReportConfig(
                chart_format="svg", write_markdown=False, write_json=False
            ),
        )
    )
    assert not (configured_dir / "backtest_report.md").exists()
    assert not (configured_dir / "backtest_report.json").exists()
    assert len(list((configured_dir / "charts").glob("*.svg"))) == 14
    assert all(artifact.uri.endswith(".svg") for artifact in configured.chart_artifacts)


@pytest.mark.slow
@pytest.mark.integration
def test_zero_costs_produces_higher_return():
    result_costly = _make_backtest(commission_rate=0.00025, slippage_bps=12.0)
    result_free = _make_backtest(commission_rate=0.0, slippage_bps=0.0)
    nav_costly = result_costly.portfolio_equity.iloc[-1]
    nav_free = result_free.portfolio_equity.iloc[-1]
    assert nav_free >= nav_costly


@pytest.mark.slow
@pytest.mark.integration
def test_real_data_adv_constraint_changes_execution():
    constrained = _make_backtest(max_adv_participation=0.001)
    unconstrained = _make_backtest(max_adv_participation=1.0)
    constrained_notional = sum(fill.filled_amount for fill in constrained.fills)
    unconstrained_notional = sum(fill.filled_amount for fill in unconstrained.fills)
    constrained_caps = sum(fill.reject_reason == "adv_cap" for fill in constrained.fills)
    unconstrained_caps = sum(fill.reject_reason == "adv_cap" for fill in unconstrained.fills)
    assert constrained_notional < unconstrained_notional
    assert constrained_caps > unconstrained_caps


@pytest.mark.slow
@pytest.mark.integration
def test_is_oos_slicing():
    result = _make_backtest(start="2019-06-01", end="2019-09-30")
    perf = result.performance
    assert perf.full_sample is not None
    # 短窗口内 OOS 可能为空, 不强制断言
    if perf.in_sample is not None:
        assert perf.in_sample.n_days <= perf.full_sample.n_days
    if perf.out_of_sample is not None:
        assert perf.out_of_sample.n_days <= perf.full_sample.n_days


@pytest.mark.slow
@pytest.mark.integration
def test_end_to_end_all_demo_factors():
    for fid in [
        "reversal_20d", "bp_1_over_pb", "size_ln_float_mktcap",
        "turnover_21d", "volatility_252d",
    ]:
        result = _make_backtest(factor_id=fid)
        assert result.run_manifest.factor_id == fid
        assert len(result.portfolio_equity) > 0
