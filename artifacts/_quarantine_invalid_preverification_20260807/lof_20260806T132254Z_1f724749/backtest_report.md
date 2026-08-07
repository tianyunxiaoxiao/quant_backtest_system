# 指数内多头因子回测报告

## 1. 运行摘要

- **run_id**: `lof_20260806T132254Z_1f724749`
- **strategy_id**: `reversal_20d_000905.SH_sf0.3_wmfactor_strength_cvv1.0.0`
- **因子**: reversal_20d
- **指数**: 000905.SH
- **代码版本**: `unversioned`
- **配置版本**: v1.0.0
- **创建时间**: 2026-08-06T13:22:54+00:00
- **回测区间**: 2019-01-01 ~ 2024-04-01
- **调仓频率**: monthly
- **成交价字段**: adj_open
- **初始资金**: 100,000,000

## 2. 绩效指标

| 样本 | 区间 | 年化收益 | 年化波动 | Sharpe | 最大回撤 | 基准年化 | 几何超额 | 信息比率 | 年化换手 | 成本侵蚀 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 全样本 | 2019-01-02 ~ 2024-04-01 | -7.00% | 27.26% | -0.13 | -57.72% | 8.04% | -13.92% | -0.63 | 9.81 | 108.42% |
| IS | 2019-01-02 ~ 2024-03-29 | -7.53% | 27.24% | -0.15 | -57.72% | 7.58% | -14.05% | -0.64 | 9.70 | 90.66% |

## 3. Alpha / Beta 拆分

- **日度 Alpha**: -0.000469
- **年化 Alpha**: -11.16%
- **Beta**: 0.843
- **Alpha t-stat (OLS)**: -1.26
- **Alpha t-stat (NW)**: -1.35
- **Alpha p-value (NW)**: 0.1783
- **R-squared**: 0.404
- **残差波动率(年化)**: 21.06%
- **观测数**: 1273

## 4. 风格因子暴露

| style | portfolio_mean | index_mean | active_mean | active_max_abs | active_latest | missing_ratio |
| --- | --- | --- | --- | --- | --- | --- |
| size | -0.1505 | 0.4122 | -0.5637 | 1.5173 | -0.8296 | 0.0173 |
| value | -0.1626 | -0.1753 | 0.0144 | 0.9392 | -0.2651 | 0.0173 |
| momentum | -0.0293 | 0.2517 | -0.2820 | 1.2904 | -0.7853 | 0.0173 |
| volatility | 0.5035 | 0.1676 | 0.3329 | 0.9449 | 0.4387 | 0.0173 |
| liquidity | 0.2109 | 0.1223 | 0.0860 | 1.0674 | -0.0377 | 0.0173 |
| growth | - | - | - | - | - | 1.0000 |
| quality | - | - | - | - | - | 1.0000 |
| leverage | - | - | - | - | - | 1.0000 |

**缺失风格**: growth, quality, leverage

## 5. 指数内选股诊断

| sample | n_days | portfolio_net_return | portfolio_gross_return | benchmark_return | excess_return_geometric | equal_weight_diagnostic_return | target_weight_diagnostic_return | implementation_shortfall | excess_win_rate_daily | mean_n_index_members | mean_n_selected | mean_n_holdings | mean_factor_coverage | total_trade_cost | cost_erosion_ratio | total_unfilled_orders | total_unfilled_amount |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| in_sample | 1272 | -0.3263 | -0.1839 | 0.4458 | -0.5340 | 0.4127 | 0.2283 | 0.5546 | 0.4796 | 500.0000 | 145.4403 | 143.0039 | 0.9666 | 19290708.4055 | 0.7737 | 234.0000 | 19977295.6809 |
| out_of_sample | 1 | 0.0291 | 0.0313 | 0.0218 | 0.0072 | 0.0258 | 0.0250 | -0.0041 | 1.0000 | 500.0000 | 150.0000 | 150.0000 | 0.9960 | 152264.5331 | 0.9365 | 0.0000 | 0.0000 |
| full_sample | 1273 | -0.3067 | -0.1584 | 0.4772 | -0.5307 | 0.4491 | 0.2591 | 0.5657 | 0.4800 | 500.0000 | 145.4438 | 143.0094 | 0.9666 | 19442972.9385 | 0.9365 | 234.0000 | 19977295.6809 |

- **diagnostic_definition**: 等权/目标权重诊断收益不含交易成本、整手约束、涨跌停与 ADV 限制,仅衡量选股信号强度, 不可作为可实现收益。
- **actual_definition**: portfolio_net_return 为扣费后实际净值收益, 含全部执行摩擦。
- **shortfall_definition**: implementation_shortfall = 目标权重诊断收益 - 实际净收益, 正数表示执行摩擦侵蚀了信号收益。
- **timing**: T 日收盘定权重, T+1 开盘成交, 诊断收益同样用 T 日权重 * T+1 收益, 时序一致。

## 6. 换手与成本

| 成本项 | 合计 |
| --- | --- |
| commission | 2,504,546.44 |
| stamp_duty | 4,748,573.98 |
| transfer_fee | 168,116.66 |
| slippage_cost | 12,021,735.87 |

## 7. 约束检查

| 约束 | 启用 | 上限 | 检查次数 | 违规次数 | 最大观测 | 处理 |
| --- | --- | --- | --- | --- | --- | --- |
| max_single_weight | True | 0.0500 | 1273 | 52 | 0.0668 | capped_and_redistributed |
| min_holdings | True | 20.0000 | 1273 | 22 | 0.0000 | warn_if_below |
| max_cash_ratio | True | 0.0500 | 1273 | 1231 | 1.0000 | warn_if_above |
| max_adv_participation | True | 0.1000 | 234 | 6 | - | partial_fill |
| max_industry_deviation | False | - | 0 | 0 | - | not_implemented_no_data |
| max_active_style_exposure | False | - | 0 | 0 | - | monitor_only |
| max_turnover | False | - | 1273 | 0 | - | not_enforced_v1 |

## 8. 披露与风险提示

- 价格与收益在复权价格空间计算, 数量与估值使用复权股数, 等价于分红再投资的全收益近似。
- 历史退市股与历史 ST 状态未包含在当前数据源中, 存在幸存者偏差与 ST 状态推断缺失。
- 基准收益由 PIT 指数月度权重合成 (buy-and-hold within month), 与官方指数存在跟踪误差; 拿到官方指数点位后可替换。
- 风格暴露为基于价量/估值字段自建的简化代理 (非 Barra), Growth/Quality/Leverage 因缺财务数据标记为缺失。
- T+1 开盘价成交 (导师 B1 确认), 整手买入、卖出允许零股, 先卖后买, 未成交订单当日取消。
- 52 只历史成分股缺少行情数据 (疑似已退市), 最大单期权重缺口 5.73%; 存在幸存者偏差

## 9. 数据谱系

| 数据集 | URI | 内容哈希 | 行数 | 列数 | 日期范围 |
| --- | --- | --- | --- | --- | --- |
| index_membership:000905.SH | /Users/a1/Desktop/添橙/5days20260806/指数月度成分股 | `302a3b8089db0653...` | 38000 | 4 | 2019-01-01 ~ 2026-04-01 |
| daily_prices | /Users/a1/Desktop/添橙/5days20260806/quant_backtest_system/warehouse/daily_prices | `2109afb6070a715c...` | 2386760 | 1074 | 2017-10-12 ~ 2024-04-01 |
| benchmark_returns | synthetic:pit_monthly_weights | `2a5fb8c3b7534cb6...` | 1273 | 1 | 2019-01-02 ~ 2024-04-01 |
| style_exposures | derived:proxy_styles_v1 | `23b1f139d47079b9...` | 1273 | 5 | 2019-01-02 ~ 2024-04-01 |

- **结果内容哈希**: `7bc1e57761f3af22b0db2b1fd33c63212df528350acb82c75771aaaca7cf83f4`
