# 指数内多头因子回测报告

## 1. 运行摘要

- **run_id**: `lof_20260807T042106Z_c1dd1eff`
- **strategy_id**: `reversal_20d_000905.SH_sf0.3_wmfactor_strength_cvv1.0.0`
- **因子**: reversal_20d
- **因子数据版本**: `integration`
- **因子代码版本**: `integration`
- **因子内容哈希**: `a347d889695e6799960ab55c4571d791e5a887cb61bbc1bc69440d3688fca320`
- **指数**: 000905.SH
- **代码版本**: `source-38d893060ffee9b3`
- **配置版本**: v1.0.0
- **创建时间**: 2026-08-07T04:21:07+00:00
- **回测区间**: 2019-06-01 ~ 2019-09-30
- **调仓频率**: monthly
- **成交价字段**: adj_vwap
- **初始资金**: 100,000,000

## 2. 方法与时间线

- **信号**: T 日 `close` 后，使用 T 日及以前可知数据。
- **下单/成交**: T+1 交易日下单并按 `adj_vwap` 成交；先卖后买，卖出回款当日可用。
- **收益归属**: 成交日计入成交价至当日收盘损益，之后按收盘到收盘计价；正式收益只由实际成交持仓和现金账户生成。
- **末端处理**: `drop_incomplete=True`，不能完成信号→成交→估值链路的末端信号日被剔除。
- **选股**: PIT 指数成分 ∩ T 日可交易 ∩ 因子有效为分母，取前 30%；并列规则 `asset_id_asc`。
- **权重**: `factor_strength`；cutoff `first_rejected`；等权兜底 `True`；单票上限 5.00%；现金缓冲 1.00%。
- **调仓频率**: `monthly`；初始资金 100,000,000.00。

## 3. 绩效指标

| 指标 | 全样本 | IS |
| --- | --- | --- |
| 区间 | 2019-06-03 ~ 2019-09-30 | 2019-06-03 ~ 2019-09-30 |
| 交易日数 | 84 | 84 |
| 累计收益 | -6.33% | -6.33% |
| 年化收益 | -18.01% | -18.01% |
| 毛年化收益 | -16.08% | -16.08% |
| 年化波动 | 18.19% | 18.19% |
| Sharpe | -0.9880 | -0.9880 |
| Sortino | -0.7121 | -0.7121 |
| 最大回撤 | -14.26% | -14.26% |
| 最大回撤峰值/谷底/修复 | 2019-07-02 / 2019-08-09 / 未修复 | 2019-07-02 / 2019-08-09 / 未修复 |
| 回撤持续/修复交易日 | 63 / -1 | 63 / -1 |
| Calmar | -1.2634 | -1.2634 |
| 基准累计收益 | 2.08% | 2.08% |
| 基准年化收益 | 6.44% | 6.44% |
| 几何累计超额 | -8.24% | -8.24% |
| 几何年化超额 | -22.97% | -22.97% |
| 算术年化超额 | -25.94% | -25.94% |
| 跟踪误差 | 12.39% | 12.39% |
| 信息比率 | -2.0925 | -2.0925 |
| 超额最大回撤 | -13.69% | -13.69% |
| 日/月/年超额胜率 | 44.05% / 25.00% / 0.00% | 44.05% / 25.00% / 0.00% |
| 年化单边换手 | 6.3429 | 6.3429 |
| 总交易成本 | 731,049.42 | 731,049.42 |
| 成本侵蚀比例 | 9.14% | 9.14% |
| 平均持股数 | 94.7619 | 94.7619 |
| 平均前十集中度 | 19.11% | 19.11% |
| 平均现金比例 | 23.40% | 23.40% |
| 平均 HHI | 0.0106 | 0.0106 |

### 年度表现

| year | portfolio_return | benchmark_return | excess_return_geometric | excess_return_arithmetic | n_days | volatility_annual | tracking_error_annual | win_rate_daily | max_drawdown | trade_cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019 | -0.0633 | 0.0208 | -0.0824 | -0.0865 | 84 | 0.1819 | 0.1239 | 0.4405 | -0.1426 | 731049.4159 |

## 4. Alpha / Beta 拆分

- **日度 Alpha**: -0.000948
- **年化 Alpha**: -21.26%
- **Beta**: 0.743
- **Alpha t-stat (OLS)**: -1.20
- **Alpha t-stat (NW)**: -1.24
- **Alpha p-value (NW)**: 0.2199
- **Alpha p-value (OLS)**: 0.2319
- **Beta t-stat (OLS / NW)**: 11.30 / 4.61
- **R-squared**: 0.609
- **残差波动率(年化)**: 11.45%
- **观测数**: 84
- **Beta 累计贡献**: 0.0165
- **Alpha/残差累计贡献**: -0.0785

### 分样本回归

| sample | alpha_daily | alpha_annual | beta | alpha_tstat_nw | alpha_tstat_ols | r_squared | residual_volatility_annual | n_observations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full_sample | -0.0009 | -0.2126 | 0.7426 | -1.2361 | -1.2045 | 0.6088 | 0.1145 | 84.0000 |
| in_sample | -0.0009 | -0.2126 | 0.7426 | -1.2361 | -1.2045 | 0.6088 | 0.1145 | 84.0000 |

## 5. 风格因子暴露

| style | portfolio_mean | index_mean | active_mean | active_max_abs | active_latest | missing_ratio |
| --- | --- | --- | --- | --- | --- | --- |
| size | -0.3548 | 0.3801 | -0.7369 | 0.8295 | -0.5729 | 0.2262 |
| value | 0.0036 | -0.1323 | 0.1415 | 0.3363 | 0.3073 | 0.2262 |
| momentum | -0.1715 | 0.2099 | -0.3847 | 0.7224 | -0.5584 | 0.2262 |
| volatility | 0.5298 | 0.0470 | 0.4753 | 0.7583 | 0.0011 | 0.2262 |
| liquidity | 0.2040 | 0.0808 | 0.1146 | 0.5566 | -0.3206 | 0.2262 |
| growth | - | - | - | - | - | 1.0000 |
| quality | - | - | - | - | - | 1.0000 |
| leverage | - | - | - | - | - | 1.0000 |

**缺失风格**: growth, quality, leverage

### 风格暴露与超额收益关系

| style | n_obs | corr_active_vs_excess | corr_lag1_active_vs_excess | mean_excess_high_exposure | mean_excess_low_exposure |
| --- | --- | --- | --- | --- | --- |
| size | 65 | 0.1420 | 0.1117 | -0.0013 | -0.0009 |
| value | 65 | 0.0762 | 0.1105 | -0.0008 | -0.0013 |
| momentum | 65 | -0.2182 | -0.0376 | -0.0015 | -0.0007 |
| volatility | 65 | -0.1677 | -0.1580 | -0.0010 | -0.0012 |
| liquidity | 65 | -0.2247 | -0.1785 | -0.0026 | 0.0005 |
| growth | 0 | - | - | - | - |
| quality | 0 | - | - | - | - |
| leverage | 0 | - | - | - | - |

## 6. 指数内选股诊断

| sample | n_days | portfolio_net_return | portfolio_gross_return | benchmark_return | excess_return_geometric | equal_weight_diagnostic_return | target_weight_diagnostic_return | implementation_shortfall | excess_win_rate_daily | mean_n_index_members | mean_n_selected | mean_n_holdings | mean_factor_coverage | total_trade_cost | cost_erosion_ratio | total_unfilled_orders | total_unfilled_amount |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| in_sample | 84 | -0.0633 | -0.0561 | 0.0208 | -0.0824 | -0.0440 | -0.0623 | 0.0010 | 0.4405 | 500.0000 | 142.6786 | 94.7619 | 0.9472 | 731049.4159 | 0.0959 | 78.0000 | 7278001.9963 |
| out_of_sample | 0 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| full_sample | 84 | -0.0633 | -0.0561 | 0.0208 | -0.0824 | -0.0440 | -0.0623 | 0.0010 | 0.4405 | 500.0000 | 142.6786 | 94.7619 | 0.9472 | 731049.4159 | 0.0959 | 78.0000 | 7278001.9963 |

### 分年度选股表现

| year | n_days | portfolio_net_return | portfolio_gross_return | benchmark_return | excess_return_geometric | equal_weight_diagnostic_return | target_weight_diagnostic_return | implementation_shortfall | excess_win_rate_daily | mean_n_index_members | mean_n_selected | mean_n_holdings | mean_factor_coverage | total_trade_cost | cost_erosion_ratio | total_unfilled_orders | total_unfilled_amount |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019.0000 | 84.0000 | -0.0633 | -0.0561 | 0.0208 | -0.0824 | -0.0440 | -0.0623 | 0.0010 | 0.4405 | 500.0000 | 142.6786 | 94.7619 | 0.9472 | 731049.4159 | 0.0959 | 78.0000 | 7278001.9963 |

- **diagnostic_definition**: 等权/目标权重诊断收益不含交易成本、整手约束、涨跌停与 ADV 限制,仅衡量选股信号强度, 不可作为可实现收益。
- **actual_definition**: portfolio_net_return 为扣费后实际净值收益, 含全部执行摩擦。
- **shortfall_definition**: implementation_shortfall = 目标权重诊断收益 - 实际净收益, 正数表示执行摩擦侵蚀了信号收益。
- **timing**: T 日收盘定权重, T+1 按 adj_vwap 无摩擦成交; 成交日计入成交价到收盘的收益, 非调仓日持仓数量不变、权重自然漂移。

## 7. 换手、成本、流动性与未成交

| 成本项 | 合计 |
| --- | --- |
| commission | 99,060.99 |
| stamp_duty | 148,712.42 |
| transfer_fee | 7,924.88 |
| slippage_cost | 475,351.13 |

- **累计单边换手**: 2.0891
- **日均单边换手**: 0.0249

- **平均 / 最大 ADV 参与率**: 0.04% / 10.00%
- **未成交订单数**: 78
- **未成交金额**: 7,278,002.00
- **最大单日未成交金额比例**: 2.28%

### 未成交明细（按原因）

| side | reason | n_orders | unfilled_shares | unfilled_amount |
| --- | --- | --- | --- | --- |
| buy | insufficient_cash | 75 | 721969.8361 | 4927491.2742 |
| sell | adv_cap | 3 | 784407.5419 | 2350510.7221 |

## 8. 约束检查

| 约束 | 启用 | 上限 | 检查次数 | 违规次数 | 最大观测 | 处理 |
| --- | --- | --- | --- | --- | --- | --- |
| full_investment | True | 1.0000 | 65 | 0 | 0.0000 | account_identity_enforced |
| max_single_weight | True | 0.0500 | 65 | 20 | 0.0546 | target_capped; post_close_drift_or_unfilled_reported |
| min_holdings | True | 20.0000 | 65 | 0 | 108.0000 | warn_if_below |
| max_cash_ratio | True | 0.0500 | 65 | 0 | 0.0109 | warn_if_above |
| max_adv_participation | True | 0.1000 | 507 | 0 | 0.1000 | partial_fill; cap_bindings=3 |
| max_turnover | False | - | 65 | 0 | 0.8496 | target_transition_scaled_and_execution_capped |
| max_industry_deviation | False | - | 0 | 0 | - | not_implemented_no_data |
| max_active_style_exposure | False | - | 0 | 0 | - | monitor_only |

### 约束违规明细

#### `max_single_weight`（20 条；完整明细见 `constraint_reports.json`）

| date | asset_id | observed | limit | excess |
| --- | --- | --- | --- | --- |
| 2019-07-01 00:00:00 | 600179.SH | 0.0522 | 0.0500 | 0.0022 |
| 2019-07-02 00:00:00 | 600179.SH | 0.0546 | 0.0500 | 0.0046 |
| 2019-07-02 00:00:00 | 600338.SH | 0.0505 | 0.0500 | 0.0005 |
| 2019-07-03 00:00:00 | 600179.SH | 0.0529 | 0.0500 | 0.0029 |
| 2019-07-03 00:00:00 | 600338.SH | 0.0511 | 0.0500 | 0.0011 |
| 2019-07-04 00:00:00 | 600179.SH | 0.0537 | 0.0500 | 0.0037 |
| 2019-07-04 00:00:00 | 600338.SH | 0.0508 | 0.0500 | 0.0008 |
| 2019-07-05 00:00:00 | 600179.SH | 0.0526 | 0.0500 | 0.0026 |
| 2019-07-05 00:00:00 | 600338.SH | 0.0507 | 0.0500 | 0.0007 |
| 2019-07-08 00:00:00 | 600179.SH | 0.0529 | 0.0500 | 0.0029 |
| 2019-07-08 00:00:00 | 600338.SH | 0.0507 | 0.0500 | 0.0007 |
| 2019-07-09 00:00:00 | 600179.SH | 0.0535 | 0.0500 | 0.0035 |
| 2019-07-10 00:00:00 | 600179.SH | 0.0534 | 0.0500 | 0.0034 |
| 2019-07-11 00:00:00 | 600179.SH | 0.0534 | 0.0500 | 0.0034 |
| 2019-07-12 00:00:00 | 600179.SH | 0.0529 | 0.0500 | 0.0029 |
| 2019-07-12 00:00:00 | 600338.SH | 0.0507 | 0.0500 | 0.0007 |
| 2019-07-15 00:00:00 | 600179.SH | 0.0508 | 0.0500 | 0.0008 |
| 2019-07-16 00:00:00 | 600179.SH | 0.0500 | 0.0500 | 0.0000 |
| 2019-07-30 00:00:00 | 600179.SH | 0.0513 | 0.0500 | 0.0013 |
| 2019-07-31 00:00:00 | 600179.SH | 0.0501 | 0.0500 | 0.0001 |

## 9. 数据缺失、排除与风险披露

### 选股排除汇总

| reason | count |
| --- | --- |
| n_index_members | 42000 |
| n_eligible | 39781 |
| excluded_not_tradable | 2219 |
| excluded_invalid_factor | 2179 |
| excluded_both | 2179 |

- 账户恒等式最大残差: 0.0000 bps
- 价格与收益在复权价格空间计算, 数量与估值使用复权股数, 等价于分红再投资的全收益近似。
- 历史退市股与历史 ST 状态未包含在当前数据源中, 存在幸存者偏差与 ST 状态推断缺失。
- 基准收益由 PIT 指数月度权重合成 (buy-and-hold within month), 与官方指数存在跟踪误差; 拿到官方指数点位后可替换。
- 风格暴露为基于价量/估值字段自建的简化代理 (非 Barra), Growth/Quality/Leverage 因缺财务数据标记为缺失。
- T+1 按 adj_vwap 成交 (默认全天 VWAP), 整手买入、卖出允许零股, 先卖后买, 未成交订单当日取消。
- 196 只历史成分股缺少行情数据 (疑似已退市), 最大单期权重缺口 17.16%; 存在幸存者偏差

## 10. 数据谱系与指标定义

| 数据集 | URI | 内容哈希 | 行数 | 列数 | 日期范围 |
| --- | --- | --- | --- | --- | --- |
| index_membership:000905.SH | /Users/a1/Desktop/添橙/5days20260806/指数月度成分股 | `831c139e313a447c...` | 38000 | 4 | 2019-01-01 ~ 2026-04-01 |
| daily_prices | /Users/a1/Desktop/添橙/5days20260806/quant_backtest_system/warehouse/daily_prices | `da65e18e069c1b45...` | 2386760 | 1074 | 2018-03-08 ~ 2019-09-30 |
| benchmark_returns | synthetic:pit_monthly_weights | `388f489fb025d64d...` | 84 | 1 | 2019-06-03 ~ 2019-09-30 |
| style_exposures | derived:proxy_styles_v1 | `a0f043232c9b3198...` | 84 | 5 | 2019-06-03 ~ 2019-09-30 |
| factor:reversal_20d | request:factor_frame | `a347d889695e6799...` | 1273 | 1074 | 2019-01-02 ~ 2024-04-01 |

- **结果内容哈希**: `0166760fb2c097b341542f960aec4c6c43e8b746f6f374b7982b3709f36f4151`

### 指标定义

| 指标 | 定义 |
| --- | --- |
| turnover | 实际成交单边换手率 = (买入成交额 + 卖出成交额) / (2 × 期初净资产) |
| excess_return | 组合费后日收益 - 指数日收益 (算术) |
| excess_nav | 组合费后净值 / 基准净值, 几何超额口径 |
| sharpe | (年化收益 - rf) / 年化波动 |
| information_ratio | 年化算术超额 / 跟踪误差 |
| cost_erosion_ratio | (毛年化收益 - 净年化收益) / |毛组合相对基准的年化超额| |
