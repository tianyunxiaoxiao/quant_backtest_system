"""请求与配置契约 (规范 6 / 17-P0)。

研究员入口只需 factor + index_id; 其余口径由嵌套默认配置提供,
但完整解析后的配置必须写入运行记录 (规范 6 末段)。
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

from .frames import FactorFrame


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} 必须是有限数")
    return number

__all__ = [
    "ClockConfig",
    "SelectionConfig",
    "WeightingConfig",
    "ConstraintConfig",
    "CostConfig",
    "ExecutionConfig",
    "RegressionConfig",
    "LongOnlyFactorBacktestConfig",
    "LongOnlyFactorBacktestRequest",
    "PortfolioReportConfig",
    "asdict_deep",
]


@dataclass(frozen=True)
class ClockConfig:
    """规范 4 默认时钟。禁止当日收盘信号当日收盘成交。"""

    signal_time: str = "close"
    order_lag_days: int = 1
    fill_lag_days: int = 0
    return_lag_days: int = 1
    drop_incomplete: bool = True

    def __post_init__(self) -> None:
        if self.order_lag_days < 1:
            raise ValueError("order_lag_days 必须 >= 1, 否则构成未来函数")
        if self.fill_lag_days < 0:
            raise ValueError("fill_lag_days 不能为负")
        if self.return_lag_days < 0:
            raise ValueError("return_lag_days 不能为负")
        if self.signal_time != "close":
            raise ValueError("v1 仅支持 signal_time='close'")


@dataclass(frozen=True)
class SelectionConfig:
    """选股口径 (规范 7.1, 确认清单 C1/C3/C4)。"""

    selection_fraction: float = 0.30
    # 30% 分母 = PIT 成分 ∩ T 日可交易 ∩ 因子有效 (C1)
    eligibility_requires_tradable: bool = True
    eligibility_requires_valid_factor: bool = True
    tie_break: str = "asset_id_asc"
    min_holdings: int = 20
    fail_on_insufficient_universe: bool = False

    def __post_init__(self) -> None:
        if not 0.0 < _finite("selection_fraction", self.selection_fraction) <= 1.0:
            raise ValueError("selection_fraction 必须落在 (0, 1]")
        if self.min_holdings < 1:
            raise ValueError("min_holdings 必须 >= 1")
        if self.tie_break != "asset_id_asc":
            raise ValueError("v1 仅支持 tie_break='asset_id_asc'")


@dataclass(frozen=True)
class WeightingConfig:
    """权重口径 (规范 7.2, 确认清单 C2)。

    cutoff_mode='first_rejected' 取最高落选分数, 保证每只入选股权重为正。
    """

    method: str = "factor_strength"
    cutoff_mode: str = "first_rejected"
    allow_equal_weight_fallback: bool = True
    max_weight: float = 0.05
    cash_buffer: float = 0.01

    def __post_init__(self) -> None:
        if self.method not in ("factor_strength", "equal_weight", "index_weight"):
            raise ValueError(f"未知 weighting_method: {self.method}")
        if self.cutoff_mode not in ("first_rejected", "last_selected"):
            raise ValueError(f"未知 cutoff_mode: {self.cutoff_mode}")
        if not 0.0 < _finite("max_weight", self.max_weight) <= 1.0:
            raise ValueError("max_weight 必须落在 (0, 1]")
        if not 0.0 <= _finite("cash_buffer", self.cash_buffer) < 1.0:
            raise ValueError("cash_buffer 必须落在 [0, 1)")


@dataclass(frozen=True)
class ConstraintConfig:
    """规范 7.3 八类约束。v1 只开数据撑得起的项 (确认清单 C5)。"""

    enforce_full_investment: bool = True
    max_single_weight: float = 0.05
    min_holdings: int = 20
    max_industry_deviation: float | None = None      # 无行业分类数据, v1 关闭
    max_active_style_exposure: float | None = None   # 代理风格, v1 只监控不约束
    max_turnover: float | None = None
    max_adv_participation: float = 0.10
    max_cash_ratio: float = 0.05
    force_sell_index_exits: bool = True              # 确认清单 C7

    def __post_init__(self) -> None:
        if not 0.0 < _finite("max_single_weight", self.max_single_weight) <= 1.0:
            raise ValueError("max_single_weight 必须落在 (0, 1]")
        if self.min_holdings < 1:
            raise ValueError("min_holdings 必须 >= 1")
        for name in ("max_industry_deviation", "max_active_style_exposure", "max_turnover"):
            value = getattr(self, name)
            if value is not None and _finite(name, value) < 0:
                raise ValueError(f"{name} 不能为负")
        if not 0.0 < _finite("max_adv_participation", self.max_adv_participation) <= 1.0:
            raise ValueError("max_adv_participation 必须落在 (0, 1]")
        if not 0.0 <= _finite("max_cash_ratio", self.max_cash_ratio) <= 1.0:
            raise ValueError("max_cash_ratio 必须落在 [0, 1]")


@dataclass(frozen=True)
class CostRate:
    """时变成本档位: 自 effective_date 起生效。"""

    effective_date: date
    value: float

    def __post_init__(self) -> None:
        if _finite("CostRate.value", self.value) < 0:
            raise ValueError("CostRate.value 不能为负")


@dataclass(frozen=True)
class CostConfig:
    """成本模型 (规范 6.7, 确认清单 E1/E2)。

    佣金/过户费/印花税走显式现金费用; 滑点嵌入成交价并派生成本列, 杜绝重复计费。
    """

    commission_rate: float = 0.00025
    min_commission: float = 0.0
    transfer_fee_schedule: tuple[CostRate, ...] = (
        CostRate(date(1900, 1, 1), 0.00002),
        CostRate(date(2022, 4, 29), 0.00001),
    )
    stamp_duty_schedule: tuple[CostRate, ...] = (
        CostRate(date(1900, 1, 1), 0.001),
        CostRate(date(2008, 9, 19), 0.001),
        CostRate(date(2023, 8, 28), 0.0005),
    )
    stamp_duty_side: str = "sell"
    slippage_bps: float = 12.0
    impact_model: str = "embedded_in_slippage"

    def __post_init__(self) -> None:
        for name in ("commission_rate", "min_commission", "slippage_bps"):
            if _finite(name, getattr(self, name)) < 0:
                raise ValueError(f"{name} 不能为负")
        if self.stamp_duty_side != "sell":
            raise ValueError("v1 印花税仅支持 sell 侧")
        if self.impact_model != "embedded_in_slippage":
            raise ValueError("v1 仅支持 impact_model='embedded_in_slippage'")
        for name in ("transfer_fee_schedule", "stamp_duty_schedule"):
            schedule = getattr(self, name)
            if not schedule:
                raise ValueError(f"{name} 不能为空")
            dates = [item.effective_date for item in schedule]
            if len(set(dates)) != len(dates):
                raise ValueError(f"{name} 生效日期不能重复")

    def transfer_fee_rate(self, on: date) -> float:
        return _rate_at(self.transfer_fee_schedule, on)

    def stamp_duty_rate(self, on: date) -> float:
        return _rate_at(self.stamp_duty_schedule, on)


def _rate_at(schedule: tuple[CostRate, ...], on: date) -> float:
    rate = 0.0
    for item in sorted(schedule, key=lambda r: r.effective_date):
        if item.effective_date <= on:
            rate = item.value
    return rate


@dataclass(frozen=True)
class ExecutionConfig:
    """执行模型 (规范 8.2, 确认清单 B1/B2/B4/B5)。"""

    # 确认清单 B1: 默认 T+1 全天 VWAP; 开盘价保留为敏感性对照。
    fill_price_field: str = "adj_vwap"
    lot_size: int = 100
    star_market_lot_size: int = 200
    allow_odd_lot_sell: bool = True
    sell_before_buy: bool = True
    sell_proceeds_available_same_day: bool = True
    unfilled_policy: str = "cancel_at_close"
    max_adv_participation: float = 0.10
    limit_touch_buffer: float = 0.005   # 距涨跌停 0.5 个百分点即视为不可交易 (B5)
    split_large_orders: bool = False
    max_split_days: int = 1

    def __post_init__(self) -> None:
        if self.fill_price_field not in ("adj_open", "adj_vwap", "adj_close"):
            raise ValueError("fill_price_field 必须是 adj_open/adj_vwap/adj_close")
        if self.lot_size < 1 or self.star_market_lot_size < 1:
            raise ValueError("整手数量必须为正整数")
        if self.unfilled_policy != "cancel_at_close":
            raise ValueError("v1 仅支持 unfilled_policy='cancel_at_close'")
        if not 0.0 < _finite("max_adv_participation", self.max_adv_participation) <= 1.0:
            raise ValueError("max_adv_participation 必须落在 (0, 1]")
        if not 0.0 <= _finite("limit_touch_buffer", self.limit_touch_buffer) < 1.0:
            raise ValueError("limit_touch_buffer 必须落在 [0, 1)")
        if self.max_split_days != 1:
            raise ValueError("v1 未支持跨日拆单; max_split_days 必须为 1")
        if not self.allow_odd_lot_sell:
            raise ValueError("v1 只支持 allow_odd_lot_sell=True")
        if not self.sell_before_buy:
            raise ValueError("v1 只支持 sell_before_buy=True")
        if not self.sell_proceeds_available_same_day:
            raise ValueError("v1 只支持 sell_proceeds_available_same_day=True")
        if self.split_large_orders:
            raise ValueError("v1 未支持跨日拆单; 未成交订单收盘取消")


@dataclass(frozen=True)
class RegressionConfig:
    """Alpha/Beta 回归参数 (规范 10, 确认清单 F1)。"""

    risk_free_annual: float = 0.0
    trading_days_per_year: int = 252
    rolling_window: int = 252
    min_observations: int = 120
    newey_west_lags: int = 5
    report_both_tstats: bool = True

    def __post_init__(self) -> None:
        _finite("risk_free_annual", self.risk_free_annual)
        if self.trading_days_per_year < 1:
            raise ValueError("trading_days_per_year 必须 >= 1")
        if self.rolling_window < 2 or self.min_observations < 2:
            raise ValueError("rolling_window/min_observations 必须 >= 2")
        if self.min_observations > self.rolling_window:
            raise ValueError("min_observations 不能超过 rolling_window")
        if self.newey_west_lags < 0:
            raise ValueError("newey_west_lags 不能为负")


@dataclass(frozen=True)
class LongOnlyFactorBacktestConfig:
    # 确认清单 A1/G3/C6 的验收口径。
    start_date: date | None = date(2018, 1, 1)
    end_date: date | None = date(2026, 3, 31)
    oos_start: date | None = date(2023, 1, 1)
    selection_fraction: float = 0.30
    weighting_method: str = "factor_strength"
    rebalance_frequency: str = "daily"
    signal_lag_days: int = 1
    initial_capital: float = 100_000_000.0
    config_version: str = "v1.0.0"
    clock: ClockConfig = field(default_factory=ClockConfig)
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    weighting: WeightingConfig = field(default_factory=WeightingConfig)
    constraints: ConstraintConfig = field(default_factory=ConstraintConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    regression: RegressionConfig = field(default_factory=RegressionConfig)

    def __post_init__(self) -> None:
        _finite("selection_fraction", self.selection_fraction)
        _finite("initial_capital", self.initial_capital)
        if self.initial_capital <= 0:
            raise ValueError("initial_capital 必须为正")
        if self.signal_lag_days < 1:
            raise ValueError("signal_lag_days 必须 >= 1")
        if self.start_date is not None and self.end_date is not None:
            if self.start_date >= self.end_date:
                raise ValueError("start_date 必须早于 end_date")
        if not self.config_version:
            raise ValueError("config_version 不能为空")
        if self.rebalance_frequency not in ("daily", "weekly", "monthly"):
            raise ValueError(f"未知 rebalance_frequency: {self.rebalance_frequency}")
        # 顶层便捷字段与嵌套配置保持一致, 避免两处口径打架
        if self.selection.selection_fraction != self.selection_fraction:
            object.__setattr__(
                self, "selection",
                dataclasses.replace(self.selection, selection_fraction=self.selection_fraction),
            )
        if self.weighting.method != self.weighting_method:
            object.__setattr__(
                self, "weighting", dataclasses.replace(self.weighting, method=self.weighting_method)
            )
        if self.clock.order_lag_days != self.signal_lag_days:
            object.__setattr__(
                self, "clock", dataclasses.replace(self.clock, order_lag_days=self.signal_lag_days)
            )
        if self.weighting.max_weight != self.constraints.max_single_weight:
            object.__setattr__(
                self, "weighting",
                dataclasses.replace(self.weighting, max_weight=self.constraints.max_single_weight),
            )
        if self.selection.min_holdings != self.constraints.min_holdings:
            object.__setattr__(
                self, "selection",
                dataclasses.replace(self.selection, min_holdings=self.constraints.min_holdings),
            )
        if self.execution.max_adv_participation != self.constraints.max_adv_participation:
            object.__setattr__(
                self, "execution",
                dataclasses.replace(
                    self.execution, max_adv_participation=self.constraints.max_adv_participation
                ),
            )


@dataclass(frozen=True)
class LongOnlyFactorBacktestRequest:
    factor: FactorFrame
    index_id: str
    config: LongOnlyFactorBacktestConfig = field(
        default_factory=LongOnlyFactorBacktestConfig
    )

    def __post_init__(self) -> None:
        if not self.index_id:
            raise ValueError("index_id 不能为空")


@dataclass(frozen=True)
class PortfolioReportConfig:
    """报告器配置 (规范 14.3)。只影响展示, 不影响业务数字。"""

    title: str = "指数内多头因子回测报告"
    chart_dpi: int = 140
    chart_format: str = "png"
    figure_width: float = 11.0
    figure_height: float = 5.2
    max_table_rows: int = 40
    write_markdown: bool = True
    write_json: bool = True
    fail_on_missing_section: bool = True

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("title 不能为空")
        if not 50 <= self.chart_dpi <= 600:
            raise ValueError("chart_dpi 必须落在 [50, 600]")
        if self.chart_format not in {"png", "svg", "pdf"}:
            raise ValueError("chart_format 必须是 png/svg/pdf")
        for name in ("figure_width", "figure_height"):
            value = _finite(name, getattr(self, name))
            if not 1.0 <= value <= 50.0:
                raise ValueError(f"{name} 必须落在 [1, 50]")
        if not 1 <= self.max_table_rows <= 100_000:
            raise ValueError("max_table_rows 必须落在 [1, 100000]")
        if not self.fail_on_missing_section:
            raise ValueError("规范要求必要报告章节不得静默缺失")


@dataclass(frozen=True)
class LongOnlyFactorReportRequest:
    """报告器请求 (规范 14.3)。"""

    backtest: Any
    report_config: PortfolioReportConfig | None = None
    output_dir: Any = None


@dataclass(frozen=True)
class LongOnlyFactorReportResult:
    """报告器结果 (规范 14.3)。"""

    report_artifacts: tuple[Any, ...]
    chart_artifacts: tuple[Any, ...]
    data_artifacts: tuple[Any, ...] = ()
    all_artifacts: tuple[Any, ...] = ()
    output_dir: Any = None


def asdict_deep(obj: Any) -> Any:
    """把配置对象递归转成 JSON 友好结构, 用于运行记录。"""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: asdict_deep(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (tuple, list)):
        return [asdict_deep(v) for v in obj]
    if isinstance(obj, Mapping):
        return {str(k): asdict_deep(v) for k, v in obj.items()}
    if isinstance(obj, date):
        return obj.isoformat()
    return obj
