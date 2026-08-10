"""数据帧契约 (规范 6.2 / 6.4 / 6.5 / 6.6 / 6.7)。

所有帧统一使用 index=交易日 (pd.DatetimeIndex), columns=资产代码 的宽表布局。
校验在构造时完成, 保证下游只处理已经通过 schema 检查的对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import numpy as np
import pandas as pd

__all__ = [
    "FactorFrame",
    "MarketPriceFrame",
    "TradabilityFrame",
    "PortfolioLiquidityData",
    "PortfolioInitialState",
    "ResolvedLongOnlyBacktestData",
]


def _check_matrix(name: str, df: pd.DataFrame, *, numeric: bool = True) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"{name} 必须是 DataFrame, 实际为 {type(df)!r}")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError(f"{name}.index 必须是 DatetimeIndex")
    if not df.index.is_monotonic_increasing:
        raise ValueError(f"{name}.index 必须按日期升序")
    if df.index.has_duplicates:
        raise ValueError(f"{name}.index 存在重复日期")
    if df.columns.has_duplicates:
        raise ValueError(f"{name}.columns 存在重复资产")
    if not df.columns.is_monotonic_increasing:
        df = df.reindex(columns=sorted(df.columns))
    if numeric:
        bad = [c for c, dt in df.dtypes.items() if not np.issubdtype(dt, np.number)]
        if bad:
            raise TypeError(f"{name} 含非数值列: {bad[:5]}")
    return df


@dataclass(frozen=True)
class FactorFrame:
    """最终因子矩阵。回测器只消费, 不做任何再加工 (规范 6.2)。"""

    values: pd.DataFrame
    factor_id: str
    direction: int = 1
    description: str = ""
    missing_policy: str = "exclude_from_eligible"
    data_version: str = "unversioned"
    content_hash: str = ""
    code_version: str = "unversioned"
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", _check_matrix("FactorFrame.values", self.values))
        if self.direction not in (1, -1):
            raise ValueError("direction 必须是 +1 或 -1")
        if not self.factor_id:
            raise ValueError("factor_id 不能为空")

    @property
    def oriented(self) -> pd.DataFrame:
        """按 direction 调整后的分数, 统一高分代表预期高收益。"""
        return self.values * float(self.direction)

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.values.index


@dataclass(frozen=True)
class MarketPriceFrame:
    """价格与成交量数据 (规范 6.4)。

    adj_* 为复权口径 (记账与收益计算使用);
    raw_* 为原始价口径 (整手、涨跌停判定使用);
    adj_factor = adj_close / raw_close, 逐段常数。
    """

    adj_open: pd.DataFrame
    adj_high: pd.DataFrame
    adj_low: pd.DataFrame
    adj_close: pd.DataFrame
    adj_vwap: pd.DataFrame
    adj_prev_close: pd.DataFrame
    raw_close: pd.DataFrame
    raw_open: pd.DataFrame
    raw_vwap: pd.DataFrame
    adj_factor: pd.DataFrame
    volume: pd.DataFrame
    amount: pd.DataFrame
    price_basis: str = "backward_adjusted_from_provider"
    fill_price_field: str = "adj_vwap"
    suspension_price_policy: str = "last_valid_close"

    _MATRICES = (
        "adj_open", "adj_high", "adj_low", "adj_close", "adj_vwap", "adj_prev_close",
        "raw_close", "raw_open", "raw_vwap", "adj_factor", "volume", "amount",
    )

    def __post_init__(self) -> None:
        ref_idx = ref_cols = None
        for name in self._MATRICES:
            df = _check_matrix(f"MarketPriceFrame.{name}", getattr(self, name))
            object.__setattr__(self, name, df)
            if ref_idx is None:
                ref_idx, ref_cols = df.index, df.columns
            else:
                if not df.index.equals(ref_idx):
                    raise ValueError(f"MarketPriceFrame.{name} 日期轴与 adj_open 不一致")
                if not df.columns.equals(ref_cols):
                    raise ValueError(f"MarketPriceFrame.{name} 资产轴与 adj_open 不一致")

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.adj_close.index

    @property
    def assets(self) -> pd.Index:
        return self.adj_close.columns


@dataclass(frozen=True)
class TradabilityFrame:
    """可交易性状态 (规范 6.5)。指数成分资格与可交易资格分开保存。

    ex_ante_* 为 T 日收盘即可知、允许进入选股过滤的状态;
    其余字段只在成交层生效 (规范 6.7 / 确认清单 B7)。
    """

    is_listed: pd.DataFrame
    is_delisted: pd.DataFrame
    is_st: pd.DataFrame
    is_suspended: pd.DataFrame
    limit_up_block_buy: pd.DataFrame
    limit_down_block_sell: pd.DataFrame
    allow_buy: pd.DataFrame
    allow_sell: pd.DataFrame
    st_data_available: bool = False
    delist_data_available: bool = False
    suspension_source: str = "zero_volume_or_missing_row"

    _MATRICES = (
        "is_listed", "is_delisted", "is_st", "is_suspended",
        "limit_up_block_buy", "limit_down_block_sell", "allow_buy", "allow_sell",
    )

    def __post_init__(self) -> None:
        ref_idx = ref_cols = None
        for name in self._MATRICES:
            df = getattr(self, name)
            df = _check_matrix(f"TradabilityFrame.{name}", df, numeric=False)
            if not df.dtypes.map(pd.api.types.is_bool_dtype).all():
                df = df.astype(bool)
            object.__setattr__(self, name, df)
            if ref_idx is None:
                ref_idx, ref_cols = df.index, df.columns
            elif not df.index.equals(ref_idx) or not df.columns.equals(ref_cols):
                raise ValueError(f"TradabilityFrame.{name} 轴与 is_listed 不一致")

    @property
    def ex_ante_tradable(self) -> pd.DataFrame:
        """T 日收盘已知的策略资格: 已上市、未退市、未停牌。"""
        return self.is_listed & (~self.is_delisted) & (~self.is_suspended)


@dataclass(frozen=True)
class PortfolioLiquidityData:
    """流动性输入 (规范 6.7)。"""

    adv: pd.DataFrame
    turnover_rate: pd.DataFrame | None = None
    adv_window: int = 20

    def __post_init__(self) -> None:
        object.__setattr__(self, "adv", _check_matrix("PortfolioLiquidityData.adv", self.adv))
        if self.turnover_rate is not None:
            object.__setattr__(
                self, "turnover_rate",
                _check_matrix("PortfolioLiquidityData.turnover_rate", self.turnover_rate),
            )


@dataclass(frozen=True)
class PortfolioInitialState:
    initial_capital: float = 100_000_000.0
    initial_holdings: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not np.isfinite(self.initial_capital) or self.initial_capital <= 0:
            raise ValueError("initial_capital 必须为正")
        for asset, quantity in self.initial_holdings.items():
            if not asset or not np.isfinite(quantity) or quantity < 0:
                raise ValueError("initial_holdings 必须是非负有限数量")


@dataclass(frozen=True)
class ResolvedLongOnlyBacktestData:
    """DataPortal 解析结果 (规范 6.1)。"""

    index_universe: pd.DataFrame
    index_weights: pd.DataFrame | None
    benchmark_returns: pd.Series
    prices: MarketPriceFrame
    tradability: TradabilityFrame
    style_exposures: Mapping[str, pd.DataFrame]
    liquidity_data: PortfolioLiquidityData
    sample_masks: Mapping[str, pd.Series]
    rebalance_dates: tuple[pd.Timestamp, ...]
    initial_state: PortfolioInitialState
    dataset_refs: tuple = ()
    benchmark_basis: str = "price_return_index_proxy"
    notes: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "index_universe",
            _check_matrix("index_universe", self.index_universe.astype(bool), numeric=False),
        )
        if not isinstance(self.benchmark_returns, pd.Series):
            raise TypeError("benchmark_returns 必须是 Series")
        if not self.rebalance_dates:
            raise ValueError("rebalance_dates 为空")
