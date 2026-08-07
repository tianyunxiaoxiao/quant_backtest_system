# 指数内多头因子回测框架 (qbt)

基于导师规范 `19_portfolio_backtest_framework.md` 实现的 A 股指数内多头因子回测系统。

## 快速开始

```bash
# 创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 跑完整回测 (默认 000905.SH, 2018-01-01 ~ 2026-03-31, 日频)
PYTHONPATH=src python -m qbt.cli.main --factor reversal_20d

# 指定窗口和调仓频率
PYTHONPATH=src python -m qbt.cli.main \
  --factor reversal_20d \
  --start 2019-06-01 \
  --end 2019-09-30 \
  --freq monthly
```

## 项目结构

```text
quant_backtest_system/
  src/qbt/
    contracts/      # 请求/配置/数据契约
    data/           # 数据摄取、PIT DataPortal、风格代理
    engine/         # 选股、权重、执行、成本、主回测器
    analytics/      # 收益、绩效、Alpha/Beta、风格、选股诊断
    reporting/      # 图表、Markdown/JSON 报告、产物登记
    cli/            # 命令行入口
    factors/        # 演示因子库
  tests/
    unit/           # 单元测试
    integration/    # 集成测试 (真实数据)
    regression/     # 回归测试 (手算 fixture)
  warehouse/        # Parquet 数据仓库
  artifacts/        # 回测产物输出
```

## 数据准备

项目仓库已包含从 `data_backup_before_511_merge/` 摄取的 Parquet 文件。如需重新摄取:

```python
from pathlib import Path
from qbt.data.ingest_prices import IngestConfig, ingest_prices

cfg = IngestConfig(
    source_dir=Path("../data_backup_before_511_merge"),
    output_dir=Path("warehouse"),
)
ingest_prices(cfg)
```

## 运行测试

```bash
.venv/bin/python -m pytest tests -q
```

最终验收证据见 `verification/MENTOR_COMPLIANCE_AUDIT_20260807.md`。该文档登记了
81 项自动测试、两个全窗口真实数据运行、人工现金/NAV 复算、产物哈希和导师
最终 20 条完成条件。

## 关键口径

- 成交价: 默认 T+1 全天 VWAP；开盘价和收盘价可作为配置化敏感性对照
- 股数换算: T 日收盘价原始价, 买入按 100 股整数倍, 卖出允许零股
- 先卖后买, 卖出回款当日可用
- 未成交订单当日收盘取消
- 涨跌停: 距涨停/跌停 0.5 个百分点即视为不可交易
- 停牌: 零成交量行 + 上市区间内缺行
- 成本: 佣金双边万 2.5, 印花税卖方单边 (2008-09-19 后 0.1%, 2023-08-28 后 0.05%), 过户费双边
- 基准: 由 PIT 指数月度权重合成, 复权价空间
- 风格: Size/Value/Momentum/Volatility/Liquidity 代理, Growth/Quality/Leverage 标记缺失

## 产物目录

每个运行生成:

```text
artifacts/{run_id}/
  run_manifest.json
  request_config.json
  selected_members.parquet
  target_weights.parquet
  actual_weights.parquet
  orders.parquet
  fills.parquet
  holdings.parquet
  cash_ledger.parquet
  daily_returns.parquet
  costs.parquet
  alpha_beta.json
  style_exposures.parquet
  index_selection_report.json
  performance_report.json
  backtest_report.json
  backtest_report.md
  charts/
```

## 注意事项

- 历史退市股与 ST 状态未包含在当前数据源中, 报告已披露幸存者偏差。
- 风格暴露为简化代理, 非 Barra。
- 基准为合成指数, 拿到官方序列后可替换 `qbt/data/benchmark.py`。
