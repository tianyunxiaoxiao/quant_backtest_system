# 指数内多头因子回测框架 (qbt)

基于导师规范 `19_portfolio_backtest_framework.md` 实现的 A 股指数内多头因子回测系统。

## 快速开始

```bash
# 创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 跑完整回测 (省略 --index 时默认 ALL_A_EQ 流动性过滤后的非 ST A 股)
PYTHONPATH=src python -m qbt.cli.main --factor reversal_20d

# 指定窗口和调仓频率
PYTHONPATH=src python -m qbt.cli.main \
  --factor reversal_20d \
  --start 2019-06-01 \
  --end 2019-09-30 \
  --freq monthly \
  --index 000905.SH
```

## 项目结构

```text
quant_backtest_system_clean/
  src/qbt/
    contracts/      # 请求/配置/数据契约
    data/           # 数据摄取、PIT DataPortal、风格代理
    engine/         # 选股、权重、执行、成本、主回测器
    analytics/      # 收益、绩效、Alpha/Beta、风格、选股诊断
    reporting/      # 图表、Markdown/JSON 报告、产物登记
    cli/            # 命令行入口
    factors/        # 演示因子库
  data/
    index_membership_source/  # 沪深300/中证500/中证1000月度 PIT 快照
  warehouse/        # Parquet 数据仓库
  artifacts/        # 回测产物输出 (首次运行前为空)
  DELIVERY_MANIFEST.md
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

### 从因子平台米筐快照构建同源仓库

组合回测可直接从因子研究平台的不可变 `panel_shards` 快照构建仓库，统一日期、
后复权价格、股票列表、历史 ST、涨跌停价和研究资格口径：

```bash
PYTHONPATH=src python scripts/ingest_rq_snapshot.py \
  --snapshot /path/to/panel_shards \
  --output warehouse_rqdata
```

构建结果写入 `rqdata_warehouse_manifest.json`，记录 RQData 供应商版本、源快照哈希、
年度分区哈希和资格规则。默认拒绝覆盖已有仓库；确认重建时显式增加 `--overwrite`。
本地 Web 服务通过 `.env` 中的 `QBT_WAREHOUSE` 切换仓库。

该仓库的交易日历、资产主表、研究股票池、行情、复权因子、ST 与涨跌停均从同一
米筐快照派生。快照未包含历史指数成分时，网页只开放 `ALL_A_EQ`，且后端会拒绝
沪深300、中证500、中证1000请求，不会回退读取旧 Excel 或其他仓库。

## 精简交付

本目录是可独立运行的精简交付副本。开发期虚拟环境、Git 历史、测试源码、缓存、
旧回测产物和验证中间文件均未打包。完整性范围和复核结果见
`DELIVERY_MANIFEST.md`。

## 关键口径

- 成交价: 默认 T+1 全天 VWAP；开盘价和收盘价可作为配置化敏感性对照
- 股数换算: T 日收盘价原始价, 买入按 100 股整数倍, 卖出允许零股
- 先卖后买, 卖出回款当日可用
- 未成交订单当日收盘取消
- 涨跌停: 距涨停/跌停 0.5 个百分点即视为不可交易
- 停牌: 零成交量行 + 上市区间内缺行
- 成本: 佣金双边万 2.5、每笔最低 5 元, 印花税卖方单边 (2008-09-19 后 0.1%, 2023-08-28 后 0.05%), 过户费双边
- 基准: 指定指数时由 PIT 指数月度权重合成; 省略指数时使用每日再平衡的“流动性过滤后的非 ST A 股” (`ALL_A_EQ`), 复权价空间
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
