# 指数内多头因子回测报告

## 1. 运行摘要

- **run_id**: `lof_20260806T132121Z_34d0d0ce`
- **strategy_id**: `reversal_20d_000905.SH_sf0.3_wmfactor_strength_cvv1.0.0`
- **因子**: reversal_20d
- **指数**: 000905.SH
- **代码版本**: `unversioned`
- **配置版本**: v1.0.0
- **创建时间**: 2026-08-06T13:21:21+00:00
- **回测区间**: 2019-06-01 ~ 2019-09-30
- **调仓频率**: monthly
- **成交价字段**: adj_open
- **初始资金**: 100,000,000

## 2. 绩效指标

| 样本 | 区间 | 年化收益 | 年化波动 | Sharpe | 最大回撤 | 基准年化 | 几何超额 | 信息比率 | 年化换手 | 成本侵蚀 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 全样本 | 2019-06-03 ~ 2019-09-30 | -59.26% | 28.86% | -2.92 | -25.60% | 6.39% | -61.70% | -2.85 | 6.88 | 1.82% |
| IS | 2019-06-03 ~ 2019-09-30 | -59.26% | 28.86% | -2.92 | -25.60% | 6.39% | -61.70% | -2.85 | 6.88 | 1.82% |

## 3. Alpha / Beta 拆分

- **日度 Alpha**: -0.003406
- **年化 Alpha**: -57.68%
- **Beta**: 0.206
- **Alpha t-stat (OLS)**: -1.72
- **Alpha t-stat (NW)**: -1.87
- **Alpha p-value (NW)**: 0.0649
- **R-squared**: 0.018
- **残差波动率(年化)**: 28.77%
- **观测数**: 84

## 4. 风格因子暴露

| style | portfolio_mean | index_mean | active_mean | active_max_abs | active_latest | missing_ratio |
| --- | --- | --- | --- | --- | --- | --- |
| size | -0.4174 | 0.3801 | -0.7995 | 0.8866 | -0.6560 | 0.2262 |
| value | 0.0185 | -0.1323 | 0.1564 | 0.3621 | 0.3321 | 0.2262 |
| momentum | -0.2239 | 0.2099 | -0.4372 | 0.7851 | -0.5936 | 0.2262 |
| volatility | 0.5804 | 0.0470 | 0.5259 | 0.7961 | 0.0449 | 0.2262 |
| liquidity | 0.2372 | 0.0808 | 0.1478 | 0.6025 | -0.2997 | 0.2262 |
| growth | - | - | - | - | - | 1.0000 |
| quality | - | - | - | - | - | 1.0000 |
| leverage | - | - | - | - | - | 1.0000 |

**缺失风格**: growth, quality, leverage

## 5. 指数内选股诊断

| sample | n_days | portfolio_net_return | portfolio_gross_return | benchmark_return | excess_return_geometric | equal_weight_diagnostic_return | target_weight_diagnostic_return | implementation_shortfall | excess_win_rate_daily | mean_n_index_members | mean_n_selected | mean_n_holdings | mean_factor_coverage | total_trade_cost | cost_erosion_ratio | total_unfilled_orders | total_unfilled_amount |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| in_sample | 84 | -0.2560 | -0.2497 | 0.0206 | -0.2710 | 0.0483 | 0.0422 | 0.2982 | 0.4405 | 500.0000 | 142.6786 | 105.6310 | 0.9472 | 674595.4785 | 0.0253 | 23.0000 | 876215.4747 |
| out_of_sample | 0 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| full_sample | 84 | -0.2560 | -0.2497 | 0.0206 | -0.2710 | 0.0483 | 0.0422 | 0.2982 | 0.4405 | 500.0000 | 142.6786 | 105.6310 | 0.9472 | 674595.4785 | 0.0253 | 23.0000 | 876215.4747 |

- **diagnostic_definition**: 等权/目标权重诊断收益不含交易成本、整手约束、涨跌停与 ADV 限制,仅衡量选股信号强度, 不可作为可实现收益。
- **actual_definition**: portfolio_net_return 为扣费后实际净值收益, 含全部执行摩擦。
- **shortfall_definition**: implementation_shortfall = 目标权重诊断收益 - 实际净收益, 正数表示执行摩擦侵蚀了信号收益。
- **timing**: T 日收盘定权重, T+1 开盘成交, 诊断收益同样用 T 日权重 * T+1 收益, 时序一致。

## 6. 换手与成本

| 成本项 | 合计 |
| --- | --- |
| commission | 91,158.94 |
| stamp_duty | 138,705.88 |
| transfer_fee | 7,292.72 |
| slippage_cost | 437,437.94 |

## 7. 约束检查

| 约束 | 启用 | 上限 | 检查次数 | 违规次数 | 最大观测 | 处理 |
| --- | --- | --- | --- | --- | --- | --- |
| max_single_weight | True | 0.0500 | 84 | 18 | 0.0547 | capped_and_redistributed |
| min_holdings | True | 20.0000 | 84 | 19 | 0.0000 | warn_if_below |
| max_cash_ratio | True | 0.0500 | 84 | 61 | 1.0000 | warn_if_above |
| max_adv_participation | True | 0.1000 | 23 | 3 | - | partial_fill |
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

- **结果内容哈希**: `164e4e9906baa0069395b2f522478dc22067617e1d1b352f58af9ae495b7f4f2`
