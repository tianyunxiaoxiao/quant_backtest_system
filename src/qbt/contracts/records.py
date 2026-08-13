"""订单、成交与运行登记记录 (规范 6.1 / 8.1 / 8.2 / 19)。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd

__all__ = [
    "DatasetRef",
    "RunArtifact",
    "RunManifest",
    "OrderRecord",
    "FillRecord",
    "PositionPeriodRecord",
    "orders_to_frame",
    "fills_to_frame",
    "position_period_to_frame",
]


@dataclass(frozen=True)
class DatasetRef:
    """DataPortal 实际读取的数据版本与内容哈希 (规范 6.1)。"""

    name: str
    uri: str
    content_hash: str
    rows: int = 0
    columns: int = 0
    date_min: str = ""
    date_max: str = ""
    notes: str = ""


@dataclass(frozen=True)
class RunArtifact:
    name: str
    uri: str
    content_hash: str
    bytes: int = 0
    kind: str = "data"


@dataclass(frozen=True)
class RunManifest:
    """运行登记 (规范 3.10 / 6.1 / 19)。"""

    run_id: str
    strategy_id: str
    factor_id: str
    index_id: str
    code_version: str
    config_version: str
    created_at: str
    config: Mapping[str, Any]
    dataset_refs: tuple[DatasetRef, ...] = ()
    artifact_uri: str = ""
    environment: Mapping[str, str] = field(default_factory=dict)
    disclosures: tuple[str, ...] = ()
    result_hash: str = ""
    factor_data_version: str = "unversioned"
    factor_content_hash: str = ""
    factor_code_version: str = "unversioned"


@dataclass(frozen=True)
class OrderRecord:
    """规范 8.1 订单字段。"""

    order_id: str
    asset_id: str
    signal_date: pd.Timestamp
    order_date: pd.Timestamp
    side: str
    target_quantity: float
    target_amount: float
    reference_price: float
    reason: str
    target_weight: float = 0.0
    current_weight: float = 0.0
    sequence: int = 0


@dataclass(frozen=True)
class FillRecord:
    """规范 8.2 成交字段。"""

    order_id: str
    asset_id: str
    order_date: pd.Timestamp
    fill_date: pd.Timestamp
    side: str
    fill_price: float
    reference_price: float
    filled_quantity: float
    filled_amount: float
    unfilled_quantity: float
    commission: float
    stamp_duty: float
    transfer_fee: float
    slippage_cost: float
    impact_cost: float
    status: str
    reject_reason: str = ""
    adv_participation: float = 0.0

    @property
    def explicit_cost(self) -> float:
        return self.commission + self.stamp_duty + self.transfer_fee

    @property
    def total_cost(self) -> float:
        return self.explicit_cost + self.slippage_cost + self.impact_cost


@dataclass(frozen=True)
class PositionPeriodRecord:
    """单个调仓日单只标的持仓迁移记录。

    数量使用原始股数（真实交易所股数）作为主要口径，同时保留复权股数
    以便与内部市值/PNL 账本对齐。买卖方向由 ``action`` 显式标注，
    ``fill_ratio`` 衡量目标订单的实际完成比例。
    """

    signal_date: pd.Timestamp
    date: pd.Timestamp
    asset_id: str
    action: str
    pre_quantity_raw: float
    pre_quantity_adjusted: float
    target_quantity_raw: float
    target_quantity_adjusted: float
    order_quantity_raw: float
    order_quantity_adjusted: float
    fill_quantity_raw: float
    fill_quantity_adjusted: float
    post_quantity_raw: float
    post_quantity_adjusted: float
    reason: str
    fill_price: float
    reference_price: float
    fill_ratio: float
    status: str
    reject_reason: str = ""


_ORDER_COLUMNS = (
    "order_id", "asset_id", "signal_date", "order_date", "side", "target_quantity",
    "target_amount", "reference_price", "reason", "target_weight", "current_weight", "sequence",
)

_FILL_COLUMNS = (
    "order_id", "asset_id", "order_date", "fill_date", "side", "fill_price", "reference_price",
    "filled_quantity", "filled_amount", "unfilled_quantity", "commission", "stamp_duty",
    "transfer_fee", "slippage_cost", "impact_cost", "status", "reject_reason", "adv_participation",
)


def orders_to_frame(orders: tuple[OrderRecord, ...]) -> pd.DataFrame:
    if not orders:
        return pd.DataFrame(columns=list(_ORDER_COLUMNS))
    return pd.DataFrame(
        [[getattr(o, c) for c in _ORDER_COLUMNS] for o in orders], columns=list(_ORDER_COLUMNS)
    )


def fills_to_frame(fills: tuple[FillRecord, ...]) -> pd.DataFrame:
    if not fills:
        return pd.DataFrame(columns=list(_FILL_COLUMNS))
    df = pd.DataFrame(
        [[getattr(f, c) for c in _FILL_COLUMNS] for f in fills], columns=list(_FILL_COLUMNS)
    )
    df["explicit_cost"] = df["commission"] + df["stamp_duty"] + df["transfer_fee"]
    df["total_cost"] = df["explicit_cost"] + df["slippage_cost"] + df["impact_cost"]
    return df


_POSITION_PERIOD_COLUMNS = (
    "signal_date", "date", "asset_id", "action",
    "pre_quantity_raw", "pre_quantity_adjusted",
    "target_quantity_raw", "target_quantity_adjusted",
    "order_quantity_raw", "order_quantity_adjusted",
    "fill_quantity_raw", "fill_quantity_adjusted",
    "post_quantity_raw", "post_quantity_adjusted",
    "reason", "fill_price", "reference_price", "fill_ratio", "status", "reject_reason",
)


def position_period_to_frame(records: tuple[PositionPeriodRecord, ...]) -> pd.DataFrame:
    """把 PositionPeriodRecord 序列转成可持久化的 DataFrame。"""
    if not records:
        return pd.DataFrame(columns=list(_POSITION_PERIOD_COLUMNS))
    return pd.DataFrame(
        [[getattr(r, c) for c in _POSITION_PERIOD_COLUMNS] for r in records],
        columns=list(_POSITION_PERIOD_COLUMNS),
    )
