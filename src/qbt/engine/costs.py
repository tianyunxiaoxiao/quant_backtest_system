"""交易成本模型 (规范 8.2, 确认清单 D3 / D4)。

费用口径:
- 佣金: 双边, 费率 * 成交额, 有最低佣金 (默认 0 元, 机构口径)。
- 过户费: 双边, 沪深两市统一按成交额计 (2015-08-01 起 0.002%)。
- 印花税: 仅卖出, 0.1%; 2023-08-28 起降至 0.05%。
- 滑点: 按 bps 计, 买入抬价卖出压价, 已内含市场冲击 (impact_model=embedded)。

费率表按 effective_date 生效, 回测中按成交日取当时有效值 (时点正确, 不用当前费率
覆盖历史)。
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

import pandas as pd

from ..contracts.config import CostConfig, CostRate

__all__ = ["CostModel", "FillCosts"]


@dataclass(frozen=True, slots=True)
class FillCosts:
    commission: float
    stamp_duty: float
    transfer_fee: float
    slippage_cost: float
    impact_cost: float

    @property
    def explicit_total(self) -> float:
        """实际从现金账户扣除的费用；滑点/冲击已嵌入成交价。"""
        return self.commission + self.stamp_duty + self.transfer_fee

    @property
    def total(self) -> float:
        """用于费前/费后归因的全部经济成本。"""
        return self.explicit_total + self.slippage_cost + self.impact_cost


def _schedule_lookup(schedule: tuple[CostRate, ...], on: pd.Timestamp) -> float:
    """取 on 日有效的费率 (最后一个 effective_date <= on)。"""
    if not schedule:
        return 0.0
    items = sorted(schedule, key=lambda r: r.effective_date)
    keys = [pd.Timestamp(r.effective_date) for r in items]
    pos = bisect_right(keys, pd.Timestamp(on)) - 1
    if pos < 0:
        return float(items[0].value)
    return float(items[pos].value)


class CostModel:
    """按成交日解析费率并计算单笔成交成本。"""

    def __init__(self, config: CostConfig) -> None:
        self.config = config
        self._cache: dict[pd.Timestamp, tuple[float, float]] = {}

    def rates_on(self, fill_date: pd.Timestamp) -> tuple[float, float]:
        """返回 (印花税率, 过户费率)。"""
        key = pd.Timestamp(fill_date)
        if key not in self._cache:
            self._cache[key] = (
                _schedule_lookup(self.config.stamp_duty_schedule, key),
                _schedule_lookup(self.config.transfer_fee_schedule, key),
            )
        return self._cache[key]

    def slippage_price(self, reference_price: float, side: str) -> float:
        """滑点后的实际成交价。买入抬价, 卖出压价。"""
        bps = self.config.slippage_bps / 10_000.0
        if side == "buy":
            return reference_price * (1.0 + bps)
        if side == "sell":
            return reference_price * (1.0 - bps)
        raise ValueError(f"未知 side: {side}")

    def compute(
        self,
        *,
        side: str,
        filled_quantity: float,
        fill_price: float,
        reference_price: float,
        fill_date: pd.Timestamp,
    ) -> FillCosts:
        """计算单笔成交的各项成本。金额一律取正数。"""
        if filled_quantity <= 0:
            return FillCosts(0.0, 0.0, 0.0, 0.0, 0.0)
        notional = filled_quantity * fill_price
        stamp_rate, transfer_rate = self.rates_on(fill_date)
        commission = max(notional * self.config.commission_rate, self.config.min_commission)
        transfer_fee = notional * transfer_rate
        stamp_duty = 0.0
        if self.config.stamp_duty_side in ("sell", "both") and side == "sell":
            stamp_duty = notional * stamp_rate
        elif self.config.stamp_duty_side == "both" and side == "buy":
            stamp_duty = notional * stamp_rate
        # 滑点成本 = 实际成交价与参考价之差 * 数量 (已内含冲击)
        slippage_cost = abs(fill_price - reference_price) * filled_quantity
        return FillCosts(
            commission=commission,
            stamp_duty=stamp_duty,
            transfer_fee=transfer_fee,
            slippage_cost=slippage_cost,
            impact_cost=0.0,
        )
