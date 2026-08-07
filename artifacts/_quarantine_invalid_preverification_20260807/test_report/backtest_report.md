# 指数内多头因子回测报告

## 1. 运行摘要

- **run_id**: `lof_20260806T130224Z_d29ee104`
- **strategy_id**: `reversal_20d_000905.SH_sf0.3_wmfactor_strength_cvv1.0.0`
- **因子**: reversal_20d
- **指数**: 000905.SH
- **代码版本**: `unversioned`
- **配置版本**: v1.0.0
- **创建时间**: 2026-08-06T13:02:24+00:00
- **回测区间**: 2019-06-01 ~ 2019-09-30
- **调仓频率**: monthly
- **成交价字段**: adj_open
- **初始资金**: 100,000,000

## 2. 绩效指标

| 样本 | 区间 | 年化收益 | 年化波动 | Sharpe | 最大回撤 | 基准年化 | 几何超额 | 信息比率 | 年化换手 | 成本侵蚀 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 全样本 | 2019-06-03 ~ 2019-09-30 | -49.46% | 29.88% | -2.09 | -20.73% | 6.39% | -52.49% | -2.28 | 4.46 | 1.74% |
| IS | 2019-06-03 ~ 2019-09-30 | -49.46% | 29.88% | -2.09 | -20.73% | 6.39% | -52.49% | -2.28 | 4.46 | 1.74% |

## 3. Alpha / Beta 拆分

- **日度 Alpha**: -0.002612
- **年化 Alpha**: -48.27%
- **Beta**: 0.415
- **Alpha t-stat (OLS)**: -1.31
- **Alpha t-stat (NW)**: -1.19
- **Alpha p-value (NW)**: 0.2385
- **R-squared**: 0.070
- **残差波动率(年化)**: 28.99%
- **观测数**: 84

## 4. 风格因子暴露

| style | portfolio_mean | index_mean | active_mean | active_max_abs | active_latest | missing_ratio |
| --- | --- | --- | --- | --- | --- | --- |
| size | -0.3407 | 0.3801 | -0.7327 | 0.8419 | -0.6210 | 0.5000 |
| value | 0.0198 | -0.1323 | 0.1698 | 0.3632 | 0.3424 | 0.5000 |
| momentum | -0.2490 | 0.2099 | -0.4809 | 0.7313 | -0.5451 | 0.5000 |
| volatility | 0.4429 | 0.0470 | 0.3815 | 0.7173 | 0.0208 | 0.5000 |
| liquidity | 0.0971 | 0.0808 | -0.0175 | 0.3253 | -0.3073 | 0.5000 |
| growth | - | - | - | - | - | 1.0000 |
| quality | - | - | - | - | - | 1.0000 |
| leverage | - | - | - | - | - | 1.0000 |

**缺失风格**: growth, quality, leverage

## 5. 指数内选股诊断

| sample | n_days | portfolio_net_return | portfolio_gross_return | benchmark_return | excess_return_geometric | equal_weight_diagnostic_return | target_weight_diagnostic_return | implementation_shortfall | excess_win_rate_daily | mean_n_index_members | mean_n_selected | mean_n_holdings | mean_factor_coverage | total_trade_cost | cost_erosion_ratio | total_unfilled_orders | total_unfilled_amount |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| in_sample | 84 | -0.2013 | -0.1969 | 0.0206 | -0.2174 | -0.0379 | -0.0347 | 0.1666 | 0.4405 | 500.0000 | 109.4524 | 72.0000 | 0.7263 | 449892.5295 | 0.0222 | 0.0000 | 0.0000 |
| out_of_sample | 0 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| full_sample | 84 | -0.2013 | -0.1969 | 0.0206 | -0.2174 | -0.0379 | -0.0347 | 0.1666 | 0.4405 | 500.0000 | 109.4524 | 72.0000 | 0.7263 | 449892.5295 | 0.0222 | 0.0000 | 0.0000 |

- **diagnostic_definition**: 等权/目标权重诊断收益不含交易成本、整手约束、涨跌停与 ADV 限制,仅衡量选股信号强度, 不可作为可实现收益。
- **actual_definition**: portfolio_net_return 为扣费后实际净值收益, 含全部执行摩擦。
- **shortfall_definition**: implementation_shortfall = 目标权重诊断收益 - 实际净收益, 正数表示执行摩擦侵蚀了信号收益。
- **timing**: T 日收盘定权重, T+1 开盘成交, 诊断收益同样用 T 日权重 * T+1 收益, 时序一致。

## 6. 换手与成本

| 成本项 | 合计 |
| --- | --- |
| commission | 62,449.84 |
| stamp_duty | 82,808.26 |
| transfer_fee | 4,995.99 |
| slippage_cost | 299,638.44 |

## 7. 约束检查

| 约束 | 启用 | 上限 | 检查次数 | 违规次数 | 最大观测 | 处理 |
| --- | --- | --- | --- | --- | --- | --- |
| max_single_weight | True | 0.0500 | 84 | 0 | 0.0419 | capped_and_redistributed |
| min_holdings | True | 20.0000 | 84 | 42 | 0.0000 | warn_if_below |
| max_cash_ratio | True | 0.0500 | 84 | 62 | 1.0000 | warn_if_above |
| max_adv_participation | True | 0.1000 | 0 | 0 | - | partial_fill |
| max_industry_deviation | False | - | 0 | 0 | - | not_implemented_no_data |
| max_active_style_exposure | False | - | 0 | 0 | - | monitor_only |
| max_turnover | False | - | 84 | 0 | - | not_enforced_v1 |

## 8. 披露与风险提示

- 价格与收益在复权价格空间计算, 数量与估值使用复权股数, 等价于分红再投资的全收益近似。
- 历史退市股与历史 ST 状态未包含在当前数据源中, 存在幸存者偏差与 ST 状态推断缺失。
- 基准收益由 PIT 指数月度权重合成 (buy-and-hold within month), 与官方指数存在跟踪误差; 拿到官方指数点位后可替换。
- 风格暴露为基于价量/估值字段自建的简化代理 (非 Barra), Growth/Quality/Leverage 因缺财务数据标记为缺失。
- T+1 开盘价成交 (导师 B1 确认), 整手买入、卖出允许零股, 先卖后买, 未成交订单当日取消。
- 196 只历史成分股缺少行情数据 (疑似已退市), 最大单期权重缺口 17.16%; 存在幸存者偏差

## 9. 数据谱系

| 数据集 | URI | 内容哈希 | 行数 | 列数 | 日期范围 |
| --- | --- | --- | --- | --- | --- |
| index_membership:000905.SH | /Users/a1/Desktop/添橙/5days20260806/指数月度成分股 | `302a3b8089db0653...` | 38000 | 4 | 2019-01-01 ~ 2026-04-01 |
| daily_prices | /Users/a1/Desktop/添橙/5days20260806/quant_backtest_system/warehouse/daily_prices | `7eaa60135868cb6f...` | 2386760 | 1074 | 2018-03-08 ~ 2019-09-30 |
| benchmark_returns | synthetic:pit_monthly_weights | `2552aa7fc1714dbb...` | 84 | 1 | 2019-06-03 ~ 2019-09-30 |
| style_exposures | derived:proxy_styles_v1 | `c7e96881af88a933...` | 84 | 5 | 2019-06-03 ~ 2019-09-30 |

- **结果内容哈希**: `6c3fcb077665b88f3b0ee59777c9633769da40f781a9dfff713bc9da68329e8d`
