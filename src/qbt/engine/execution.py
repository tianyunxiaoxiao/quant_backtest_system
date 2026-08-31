"""订单生成、成交模拟与账户核算 (规范 8, 确认清单 B7 / C7 / D3 / E1)。

时间轴 (规范 5, 确认清单 G3):
    T 日收盘  -> 因子/信号已知, 生成目标权重
    T+1 日    -> 下单并按当日 VWAP 成交 (order_lag_days=1, fill_lag_days=0)
    T+1 起    -> 持仓按收盘价估值, 产生收益

持仓口径: 内部按"复权股数"记账 (shares_adj), 估值一律 shares_adj * adj_close。
下单时的交易所数量约束在"真实股数"空间做 (主板 100 股、科创板最低
200 股后逐股、北交所最低 100 股后逐股), 再折算回复权股数。
这样送转拆股不会凭空改变持仓市值, 分红也通过后复权价自然计入总收益。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..contracts import (
    FillRecord,
    LongOnlyFactorBacktestConfig,
    MarketPriceFrame,
    OrderRecord,
    PortfolioLiquidityData,
    PositionPeriodRecord,
    TradabilityFrame,
)
from .costs import CostModel

__all__ = ["ExecutionEngine", "ExecutionOutput"]

_LOT_EXEMPT_SUFFIX = ()  # A 股全部按整手买入


def _is_star_market(asset_id: str) -> bool:
    code = asset_id.split(".", 1)[0]
    return code.startswith(("688", "689"))


def _is_bse(asset_id: str) -> bool:
    code = asset_id.split(".", 1)[0]
    return asset_id.endswith(".BJ") or code.startswith(("43", "83", "87", "88", "92"))


@dataclass(frozen=True)
class ExecutionOutput:
    orders: tuple[OrderRecord, ...]
    fills: tuple[FillRecord, ...]
    holdings_shares: pd.DataFrame
    holdings_cost_basis: pd.DataFrame
    holdings_unrealized_pnl: pd.DataFrame
    holdings_value: pd.DataFrame
    actual_weights: pd.DataFrame
    cash_ledger: pd.DataFrame
    costs: pd.DataFrame
    unfilled_summary: pd.DataFrame
    accounting_identity: pd.DataFrame
    position_period_records: tuple[PositionPeriodRecord, ...] = ()


def _lot_size(asset_id: str, config: LongOnlyFactorBacktestConfig) -> int:
    """科创板 688/689 开头最小 200 股, 其余 100 股。"""
    if _is_star_market(asset_id):
        return int(config.execution.star_market_lot_size)
    return int(config.execution.lot_size)


def _buy_step(asset_id: str, config: LongOnlyFactorBacktestConfig) -> int:
    """科创板/北交所达到最低数量后按 1 股递增。"""
    return 1 if _is_star_market(asset_id) or _is_bse(asset_id) else int(config.execution.lot_size)


def _max_order_quantity(asset_id: str) -> int:
    """Limit-order maximum for one exchange-valid child order."""
    return 100_000 if _is_star_market(asset_id) else 1_000_000


def _round_buy_quantity(quantity: float, minimum: int, step: int) -> float:
    """Round a desired buy quantity down to an exchange-valid order quantity."""
    if not np.isfinite(quantity) or quantity < minimum:
        return 0.0
    return float(np.floor((quantity + 1e-9) / step) * step)


class ExecutionEngine:
    """把目标权重推进成实际持仓、现金与成交流水。"""

    def __init__(
        self,
        *,
        config: LongOnlyFactorBacktestConfig,
        prices: MarketPriceFrame,
        tradability: TradabilityFrame,
        liquidity: PortfolioLiquidityData,
        index_universe: pd.DataFrame,
    ) -> None:
        self.config = config
        self.prices = prices
        self.trad = tradability
        self.liq = liquidity
        self.index_universe = index_universe
        self.costs = CostModel(config.costs)

        self.dates = prices.adj_close.index
        self.assets = prices.adj_close.columns
        self._assets_array = self.assets.to_numpy(dtype=object, copy=False)
        self._pos = {a: i for i, a in enumerate(self.assets)}
        self._lots = np.array(
            [_lot_size(a, config) for a in self.assets], dtype="int64"
        )
        self._buy_steps = np.array(
            [_buy_step(a, config) for a in self.assets], dtype="int64"
        )
        self._max_order_quantities = np.array(
            [_max_order_quantity(a) for a in self.assets], dtype="int64"
        )

        # numpy 视图, 循环里避免 pandas 索引开销
        self._adj_close = prices.adj_close.to_numpy(dtype="float64")
        # 成交价口径由 config 决定 (确认清单 B1 默认 T+1 VWAP)。复权价用于记账,
        # 原始价用于按手取整 —— 手数是按真实价格下的, 不是复权价。
        adj_field = config.execution.fill_price_field
        raw_field = {"adj_open": "raw_open", "adj_vwap": "raw_vwap", "adj_close": "raw_close"}
        if adj_field not in raw_field:
            raise ValueError(
                f"不支持的 fill_price_field={adj_field}; 可选 {sorted(raw_field)}"
            )
        self.fill_price_field = adj_field
        self._fill_adj = getattr(prices, adj_field).to_numpy(dtype="float64")
        self._fill_raw = getattr(prices, raw_field[adj_field]).to_numpy(dtype="float64")
        self._amount = prices.amount.to_numpy(dtype="float64")
        self._allow_buy = tradability.allow_buy.to_numpy(dtype=bool)
        self._allow_sell = tradability.allow_sell.to_numpy(dtype=bool)
        self._is_delisted = tradability.is_delisted.to_numpy(dtype=bool)
        self._is_susp = tradability.is_suspended.to_numpy(dtype=bool)
        self._lu_block = tradability.limit_up_block_buy.to_numpy(dtype=bool)
        self._ld_block = tradability.limit_down_block_sell.to_numpy(dtype=bool)
        self._adv = liquidity.adv.reindex(
            index=self.dates, columns=self.assets
        ).to_numpy(dtype="float64")
        self._in_index = index_universe.to_numpy(dtype=bool)
        raw_close = prices.raw_close.to_numpy(dtype="float64")
        self._close_ratio = np.divide(
            raw_close,
            self._adj_close,
            out=np.full_like(raw_close, np.nan),
            where=np.isfinite(raw_close) & (raw_close > 0) & np.isfinite(self._adj_close)
            & (self._adj_close > 0),
        )

    # ---------- 主循环 ----------

    def run(
        self,
        *,
        target_weights: pd.DataFrame,
        rebalance_dates: tuple[pd.Timestamp, ...],
        initial_capital: float,
    ) -> ExecutionOutput:
        cfg = self.config
        n_d, n_a = len(self.dates), len(self.assets)
        order_lag = int(cfg.clock.order_lag_days)
        fill_lag = int(cfg.clock.fill_lag_days)

        tw = target_weights.reindex(index=self.dates, columns=self.assets)
        tw_arr = tw.to_numpy(dtype="float64")

        # 信号日 -> 成交日映射。信号在 T 收盘生成, T+order_lag 下单/成交。
        date_pos = {d: i for i, d in enumerate(self.dates)}
        exec_plan: dict[int, int] = {}   # 成交日索引 -> 信号日索引
        for d in rebalance_dates:
            si = date_pos.get(pd.Timestamp(d))
            if si is None:
                continue
            ti = si + order_lag + fill_lag
            if ti < n_d:
                exec_plan[ti] = si

        shares = np.zeros(n_a, dtype="float64")      # 复权股数
        cost_basis = np.zeros(n_a, dtype="float64")  # 累计买入成本 (含费)
        cash = float(initial_capital)
        identity_rows: list[dict] = []

        holdings_shares = np.zeros((n_d, n_a), dtype="float64")
        holdings_cost_basis = np.zeros((n_d, n_a), dtype="float64")
        holdings_unrealized_pnl = np.zeros((n_d, n_a), dtype="float64")
        holdings_value = np.zeros((n_d, n_a), dtype="float64")
        orders: list[OrderRecord] = []
        fills: list[FillRecord] = []
        ledger_rows: list[dict] = []
        unfilled_rows: list[dict] = []
        position_period_rows: list[PositionPeriodRecord] = []

        # 收盘价前值填充, 停牌日按最后有效价估值 (规范 6.6 suspension_price_policy)
        last_valid_close = np.full(n_a, np.nan, dtype="float64")
        last_valid_ratio = np.full(n_a, np.nan, dtype="float64")
        order_seq = 0
        cumulative_realized = 0.0

        for ti in range(n_d):
            day = self.dates[ti]
            close_t = self._adj_close[ti]
            valid_close = np.isfinite(close_t) & (close_t > 0) & (~self._is_delisted[ti])
            ratio_t = self._close_ratio[ti]
            valid_ratio = np.isfinite(ratio_t) & (ratio_t > 0) & (~self._is_delisted[ti])

            # 先取上一日收盘做期初估值, 再用今日收盘更新, 顺序不能反
            prev_close_vec = last_valid_close.copy()
            last_valid_close = np.where(valid_close, close_t, last_valid_close)
            last_valid_ratio = np.where(valid_ratio, ratio_t, last_valid_ratio)
            shares_start = shares.copy()
            open_equity = cash + float(np.nansum(shares * np.nan_to_num(prev_close_vec)))
            open_cash = cash
            day_cost = 0.0
            day_explicit_cost = 0.0
            day_buy_amt = 0.0
            day_sell_amt = 0.0
            day_buy_ref_amt = 0.0
            day_sell_ref_amt = 0.0
            realized = 0.0
            bought_adj = np.zeros(n_a, dtype="float64")
            sold_adj = np.zeros(n_a, dtype="float64")
            delisting_recovery_amount = 0.0
            delisting_writeoff_amount = 0.0

            # 退市不是一笔可成交订单。进入退市状态后，仍残留的持仓按配置回收率
            # 一次性终止确认，并单独标为 writeoff，避免最后价格永久续值。
            for j in np.flatnonzero(self._is_delisted[ti] & (shares > 0)):
                qty_adj = float(shares[j])
                prior_price = float(prev_close_vec[j]) if np.isfinite(prev_close_vec[j]) else 0.0
                prior_value = qty_adj * prior_price
                recovery = prior_value * float(cfg.execution.delisting_recovery_rate)
                ratio_j = last_valid_ratio[j] if np.isfinite(last_valid_ratio[j]) else 1.0
                qty_raw = qty_adj / ratio_j
                recovery_price_raw = recovery / qty_raw if qty_raw > 0 else 0.0
                asset = self._assets_array[j]
                order_seq += 1
                oid = f"{day.strftime('%Y%m%d')}-{order_seq:06d}"
                orders.append(OrderRecord(
                    order_id=oid, asset_id=asset, signal_date=day, order_date=day,
                    side="sell", target_quantity=qty_raw, target_amount=recovery,
                    reference_price=recovery_price_raw, reason="delisting_writeoff",
                    target_weight=0.0,
                    current_weight=(prior_value / open_equity if open_equity > 0 else 0.0),
                    sequence=order_seq,
                ))
                fills.append(FillRecord(
                    order_id=oid, asset_id=asset, order_date=day, fill_date=day,
                    side="sell", fill_price=recovery_price_raw,
                    reference_price=recovery_price_raw, filled_quantity=qty_raw,
                    filled_amount=recovery, unfilled_quantity=0.0, commission=0.0,
                    stamp_duty=0.0, transfer_fee=0.0, slippage_cost=0.0,
                    impact_cost=0.0, status="writeoff",
                    reject_reason="delisting_writeoff", adv_participation=0.0,
                ))
                position_period_rows.append(PositionPeriodRecord(
                    signal_date=day, date=day, asset_id=asset, action="exit",
                    pre_quantity_raw=qty_raw, pre_quantity_adjusted=qty_adj,
                    target_quantity_raw=0.0, target_quantity_adjusted=0.0,
                    order_quantity_raw=-qty_raw, order_quantity_adjusted=-qty_adj,
                    fill_quantity_raw=-qty_raw, fill_quantity_adjusted=-qty_adj,
                    post_quantity_raw=0.0, post_quantity_adjusted=0.0,
                    reason="delisting_writeoff", fill_price=recovery_price_raw,
                    reference_price=recovery_price_raw, fill_ratio=1.0,
                    status="writeoff", reject_reason="delisting_writeoff",
                ))
                realized += recovery - float(cost_basis[j])
                cash += recovery
                sold_adj[j] = qty_adj
                day_sell_ref_amt += recovery
                delisting_recovery_amount += recovery
                delisting_writeoff_amount += prior_value - recovery
                shares[j] = 0.0
                cost_basis[j] = 0.0

            si = exec_plan.get(ti)
            if si is not None:
                res = self._rebalance_day(
                    ti=ti, si=si, day=day, signal_day=self.dates[si],
                    tw_row=tw_arr[si], shares=shares, cost_basis=cost_basis,
                    cash=cash, last_valid_close=prev_close_vec,
                    orders=orders, fills=fills, unfilled_rows=unfilled_rows,
                    order_seq=order_seq, bought_adj=bought_adj, sold_adj=sold_adj,
                )
                cash = res["cash"]
                day_cost += res["cost"]
                day_explicit_cost += res["explicit_cost"]
                day_buy_amt += res["buy_amount"]
                day_sell_amt += res["sell_amount"]
                day_buy_ref_amt += res["buy_reference_amount"]
                day_sell_ref_amt += res["sell_reference_amount"]
                realized += res["realized"]
                order_seq = res["order_seq"]
                position_period_rows.extend(res["position_period_rows"])

            mkt_val = shares * np.nan_to_num(last_valid_close)
            holdings_shares[ti] = shares
            holdings_cost_basis[ti] = cost_basis
            holdings_value[ti] = mkt_val
            unrealized_by_asset = np.where(shares > 0, mkt_val - cost_basis, 0.0)
            holdings_unrealized_pnl[ti] = unrealized_by_asset
            total_mv = float(mkt_val.sum())
            net_assets = cash + total_mv
            cumulative_realized += realized
            turnover = (
                (day_buy_amt + day_sell_amt) / (2.0 * open_equity)
                if open_equity > 0
                else np.nan
            )

            # 独立重算持仓损益, 与净资产变动对账 (规范 8.3)。
            # 三段拆分: 全天持有段 + 当日卖出段 + 当日买入段。
            pc = np.nan_to_num(prev_close_vec)
            ct = np.where(valid_close, close_t, pc)
            held_through = shares_start - sold_adj
            pnl_hold = float(np.sum(np.where(held_through > 0, held_through * (ct - pc), 0.0)))
            pnl_sell = day_sell_ref_amt - float(
                np.sum(np.where(sold_adj > 0, sold_adj * pc, 0.0))
            )
            pnl_buy = (
                float(np.sum(np.where(bought_adj > 0, bought_adj * ct, 0.0)))
                - day_buy_ref_amt
            )
            gross_pnl = pnl_hold + pnl_sell + pnl_buy
            identity_rows.append({
                "date": day,
                "open_net_assets": open_equity,
                "pnl_holding": pnl_hold,
                "pnl_sold_intraday": pnl_sell,
                "pnl_bought_intraday": pnl_buy,
                "gross_pnl": gross_pnl,
                "trade_cost": day_cost,
                "explicit_cost": day_explicit_cost,
                "external_flow": 0.0,
                "close_net_assets": net_assets,
                "expected_close": open_equity + gross_pnl - day_cost,
                "open_cash": open_cash,
            })

            ledger_rows.append(
                {
                    "date": day,
                    "open_net_assets": open_equity,
                    "cash": cash,
                    "available_cash": cash,
                    "frozen_cash": 0.0,
                    "market_value": total_mv,
                    "total_assets": net_assets,
                    "net_assets": net_assets,
                    "n_holdings": int((shares > 0).sum()),
                    "cash_ratio": cash / net_assets if net_assets > 0 else np.nan,
                    "buy_amount": day_buy_amt,
                    "sell_amount": day_sell_amt,
                    "trade_cost": day_cost,
                    "explicit_cost": day_explicit_cost,
                    "realized_pnl": realized,
                    "cumulative_realized_pnl": cumulative_realized,
                    "unrealized_pnl": float(unrealized_by_asset.sum()),
                    "turnover": turnover,
                    "delisting_recovery_amount": delisting_recovery_amount,
                    "delisting_writeoff_amount": delisting_writeoff_amount,
                    "is_rebalance": si is not None,
                    "signal_date": self.dates[si] if si is not None else pd.NaT,
                }
            )

        return self._finalize(
            holdings_shares, holdings_cost_basis, holdings_unrealized_pnl,
            holdings_value, ledger_rows, orders, fills, unfilled_rows,
            initial_capital, identity_rows, position_period_rows,
        )

    # ---------- 调仓日 ----------

    def _rebalance_day(
        self, *, ti, si, day, signal_day, tw_row, shares, cost_basis, cash,
        last_valid_close, orders, fills, unfilled_rows, order_seq,
        bought_adj, sold_adj,
    ) -> dict:
        cfg = self.config
        vwap_adj = self._fill_adj[ti]
        vwap_raw = self._fill_raw[ti]
        allow_buy = self._allow_buy[ti]
        allow_sell = self._allow_sell[ti]
        adv = self._adv[ti]
        max_part = float(cfg.execution.max_adv_participation)
        order_id_prefix = day.strftime("%Y%m%d")

        # 估值基准: 用当日收盘前的最后有效价推总资产, 目标金额按该总资产计
        mkt_val = shares * np.nan_to_num(last_valid_close)
        equity = cash + float(mkt_val.sum())
        if equity <= 0:
            return {
                "cash": cash,
                "cost": 0.0,
                "explicit_cost": 0.0,
                "buy_amount": 0.0,
                "sell_amount": 0.0,
                "buy_reference_amount": 0.0,
                "sell_reference_amount": 0.0,
                "realized": 0.0,
                "order_seq": order_seq,
                "position_period_rows": [],
            }

        # 目标权重本身已经包含 cash_buffer；这里直接乘总权益，避免重复留现。
        target_val = tw_row * equity
        target_val = np.where(np.isfinite(target_val), target_val, 0.0)

        # 强制卖出已剔出指数的持仓 (确认清单 C7)
        exits = (
            bool(cfg.constraints.force_sell_index_exits)
            & (shares > 0) & (~self._in_index[ti]) & (target_val <= 0)
        )

        held = shares > 0
        tradable_price = np.isfinite(vwap_adj) & (vwap_adj > 0)

        # 目标先在信号日复权股数空间计算，再按成交日复权比例还原真实股数。
        # 这样 T 到 T+1 发生送转除权时，目标经济敞口不会减半或翻倍。
        ratio = np.divide(
            vwap_raw, vwap_adj, out=np.ones_like(vwap_adj), where=tradable_price
        )
        sig_close_adj = self._adj_close[si]
        sizing_ok = (
            np.isfinite(sig_close_adj) & (sig_close_adj > 0)
            & np.isfinite(ratio) & (ratio > 0)
        )
        target_adj_shares = np.zeros_like(target_val)
        np.divide(target_val, sig_close_adj, out=target_adj_shares, where=sizing_ok)
        raw_target_shares = np.zeros_like(target_val)
        np.divide(target_adj_shares, ratio, out=raw_target_shares, where=sizing_ok)
        raw_held = np.divide(
            shares, ratio, out=np.zeros_like(shares), where=np.isfinite(ratio) & (ratio > 0)
        )
        # 实际账户只能持有整数股。复权因子重建误差可能产生极小的小数尾差，
        # 在原始股数空间统一还原为整数后再生成订单。
        raw_held = np.where(raw_held > 0, np.rint(raw_held), 0.0)
        # 信号日无有效收盘价 -> 无法折算目标股数。持仓票默认"不动"而不是清仓:
        # 缺价是数据问题, 按 0 处理会凭空造出一笔清仓单。
        hold_still = (~sizing_ok) & (shares > 0)
        raw_target_shares = np.where(hold_still, raw_held, raw_target_shares)
        # 目标权重先转换成交易所允许的目标股数，避免未触发现金/ADV 上限时
        # 原先的浮点目标直接成为小数股成交。
        valid_target = np.isfinite(raw_target_shares) & (raw_target_shares >= self._lots)
        rounded_target_shares = np.where(
            valid_target,
            np.floor((raw_target_shares + 1e-9) / self._buy_steps) * self._buy_steps,
            0.0,
        )
        rounded_target_shares = np.where(hold_still, raw_held, rounded_target_shares)
        raw_target_shares = rounded_target_shares

        total_cost = 0.0
        explicit_cost = 0.0
        buy_amount = 0.0
        sell_amount = 0.0
        buy_reference_amount = 0.0
        sell_reference_amount = 0.0
        realized = 0.0
        remaining_turnover_notional = (
            2.0 * float(cfg.constraints.max_turnover) * equity
            if cfg.constraints.max_turnover is not None
            else np.inf
        )

        # 持仓迁移记录: 每个调仓日单只标的 pre/target/order/fill/post
        shares_start = shares.copy()
        position_period_rows: list[PositionPeriodRecord] = []
        pp_order_qty_raw: dict[int, float] = {}
        pp_fill_qty_raw: dict[int, float] = {}
        pp_fill_price: dict[int, float] = {}
        pp_reference_price: dict[int, float] = {}
        pp_status: dict[int, str] = {}
        pp_reject_reason: dict[int, str] = {}
        pp_reason: dict[int, str] = {}

        def _record_order(j: int, side: str, qty_raw: float, reason: str) -> None:
            sign = -1.0 if side == "sell" else 1.0
            pp_order_qty_raw[j] = sign * qty_raw
            pp_reason[j] = reason

        def _record_fill(
            j: int,
            side: str,
            qty_raw: float,
            fill_price: float,
            ref_price: float,
            status: str,
            reject_reason: str,
        ) -> None:
            sign = -1.0 if side == "sell" else 1.0
            pp_fill_qty_raw[j] = pp_fill_qty_raw.get(j, 0.0) + sign * qty_raw
            pp_fill_price[j] = fill_price
            pp_reference_price[j] = ref_price
            pp_status[j] = status
            pp_reject_reason[j] = reject_reason

        # ---- 第一轮: 卖出 (先卖后买, 释放现金当日可用) ----
        sell_idx = np.flatnonzero(
            held & ((raw_target_shares < raw_held - 1e-9) | exits)
        )
        for j in sell_idx:
            asset = self._assets_array[j]
            lot = self._lots[j]
            step = self._buy_steps[j]
            max_order_qty = self._max_order_quantities[j]
            want_raw = 0.0 if exits[j] else float(raw_target_shares[j])
            delta_raw = float(raw_held[j]) - want_raw
            if delta_raw <= 0:
                continue
            # 卖出按整手向下取整, 但清仓允许卖零股 (allow_odd_lot_sell)
            full_exit = bool(exits[j] or want_raw <= 0)
            allow_odd = bool(cfg.execution.allow_odd_lot_sell and full_exit)
            sell_minimum = 1 if allow_odd else int(lot)
            sell_step = 1 if allow_odd else int(step)
            if allow_odd:
                qty_raw = float(np.floor(raw_held[j] + 1e-9))
            else:
                qty_raw = _round_buy_quantity(delta_raw, sell_minimum, sell_step)
            if qty_raw <= 0:
                continue
            order_size_capped = qty_raw > max_order_qty
            if order_size_capped:
                qty_raw = _round_buy_quantity(
                    float(max_order_qty), sell_minimum, sell_step
                )
            reason = "index_exit_forced" if exits[j] else "rebalance_reduce"
            order_seq += 1
            ref_price = float(vwap_adj[j]) if tradable_price[j] else np.nan
            oid = f"{order_id_prefix}-{order_seq:06d}"
            orders.append(OrderRecord(
                order_id=oid, asset_id=asset, signal_date=signal_day, order_date=day,
                side="sell", target_quantity=qty_raw,
                target_amount=qty_raw * (vwap_raw[j] if tradable_price[j] else np.nan),
                reference_price=ref_price, reason=reason,
                target_weight=float(tw_row[j]),
                current_weight=float(mkt_val[j] / equity), sequence=order_seq,
            ))
            _record_order(j, "sell", qty_raw, reason)
            blocked, why = self._blocked(ti, j, "sell", allow_sell, tradable_price)
            if blocked:
                fills.append(self._reject(oid, asset, day, "sell", ref_price, qty_raw, why))
                _record_fill(j, "sell", 0.0, np.nan, vwap_raw[j], "rejected", why)
                unfilled_rows.append({"date": day, "asset_id": asset, "side": "sell",
                                      "reason": why, "unfilled_quantity": qty_raw,
                                      "reference_price_raw": vwap_raw[j]})
                continue
            if not np.isfinite(adv[j]) or adv[j] <= 0:
                fills.append(self._reject(oid, asset, day, "sell", ref_price, qty_raw, "adv_missing"))
                _record_fill(j, "sell", 0.0, np.nan, vwap_raw[j], "rejected", "adv_missing")
                unfilled_rows.append({
                    "date": day, "asset_id": asset, "side": "sell",
                    "reason": "adv_missing", "unfilled_quantity": qty_raw,
                    "reference_price_raw": vwap_raw[j],
                })
                continue
            fill_price_raw = self.costs.slippage_price(float(vwap_raw[j]), "sell")
            qty_raw, capped = self._apply_adv(
                qty_raw, adv[j], fill_price_raw, max_part, lot,
                minimum=sell_minimum,
                step=sell_step,
            )
            if qty_raw <= 0:
                fills.append(self._reject(oid, asset, day, "sell", ref_price, 0.0, "adv_cap_zero"))
                _record_fill(j, "sell", 0.0, np.nan, vwap_raw[j], "rejected", "adv_cap")
                unfilled_rows.append({
                    "date": day, "asset_id": asset, "side": "sell",
                    "reason": "adv_cap", "unfilled_quantity": delta_raw,
                    "reference_price_raw": vwap_raw[j],
                })
                continue
            if exits[j]:
                turnover_capped = False
            else:
                qty_raw, turnover_capped = self._apply_notional_cap(
                    qty_raw, fill_price_raw, remaining_turnover_notional, lot,
                    minimum=sell_minimum,
                    step=sell_step,
                )
            if qty_raw <= 0:
                fills.append(
                    self._reject(
                        oid, asset, day, "sell", ref_price, delta_raw,
                        "turnover_cap_zero",
                    )
                )
                _record_fill(j, "sell", 0.0, np.nan, vwap_raw[j], "rejected", "turnover_cap")
                unfilled_rows.append({
                    "date": day, "asset_id": asset, "side": "sell",
                    "reason": "turnover_cap", "unfilled_quantity": delta_raw,
                    "reference_price_raw": vwap_raw[j],
                })
                continue
            notional = qty_raw * fill_price_raw
            remaining_turnover_notional = max(remaining_turnover_notional - notional, 0.0)
            fc = self.costs.compute(side="sell", filled_quantity=qty_raw,
                                    fill_price=fill_price_raw,
                                    reference_price=float(vwap_raw[j]), fill_date=day)
            # A full raw-share liquidation must consume the exact remaining adjusted
            # balance. Provider reconstruction noise can otherwise make
            # qty_raw * ratio exceed shares[j] slightly, and the later zero clamp
            # would create a false accounting residual.
            full_liquidation = qty_raw >= raw_held[j] - 1e-9
            qty_adj = shares[j] if full_liquidation else min(qty_raw * ratio[j], shares[j])
            avg_cost = cost_basis[j] / shares[j] if shares[j] > 0 else 0.0
            realized += notional - fc.explicit_total - avg_cost * qty_adj
            cost_basis[j] = max(cost_basis[j] - avg_cost * qty_adj, 0.0)
            shares[j] = max(shares[j] - qty_adj, 0.0)
            if shares[j] <= 1e-9:
                shares[j] = 0.0
                cost_basis[j] = 0.0
            cash += notional - fc.explicit_total
            total_cost += fc.total
            explicit_cost += fc.explicit_total
            sell_amount += notional
            sell_reference_amount += qty_raw * float(vwap_raw[j])
            sold_adj[j] += qty_adj
            fills.append(FillRecord(
                order_id=oid, asset_id=asset, order_date=day, fill_date=day, side="sell",
                fill_price=fill_price_raw, reference_price=float(vwap_raw[j]),
                filled_quantity=qty_raw, filled_amount=notional,
                unfilled_quantity=max(delta_raw - qty_raw, 0.0),
                commission=fc.commission, stamp_duty=fc.stamp_duty,
                transfer_fee=fc.transfer_fee, slippage_cost=fc.slippage_cost,
                impact_cost=fc.impact_cost,
                status="filled" if not (order_size_capped or capped or turnover_capped) else "partial",
                reject_reason=(
                    "turnover_cap" if turnover_capped else (
                        "adv_cap" if capped else (
                            "order_size_cap" if order_size_capped else ""
                        )
                    )
                ),
                adv_participation=float(notional / adv[j]) if adv[j] and adv[j] > 0 else np.nan,
            ))
            _record_fill(
                j, "sell", qty_raw, fill_price_raw, float(vwap_raw[j]),
                "filled" if not (order_size_capped or capped or turnover_capped) else "partial",
                "turnover_cap" if turnover_capped else (
                    "adv_cap" if capped else ("order_size_cap" if order_size_capped else "")
                ),
            )
            if order_size_capped or capped or turnover_capped:
                unfilled_rows.append({"date": day, "asset_id": asset, "side": "sell",
                                      "reason": "turnover_cap" if turnover_capped else (
                                          "adv_cap" if capped else "order_size_cap"
                                      ),
                                      "unfilled_quantity": delta_raw - qty_raw,
                                      "reference_price_raw": vwap_raw[j]})

        # ---- 第二轮: 买入 (现金约束下按缺口大小优先) ----
        buy_gap = raw_target_shares - raw_held
        buy_idx = np.flatnonzero((buy_gap > 0) & (target_val > 0))
        if len(buy_idx):
            order = np.argsort(-(buy_gap[buy_idx] * np.nan_to_num(vwap_raw[buy_idx])))
            buy_idx = buy_idx[order]
        reserve = float(cfg.weighting.cash_buffer) * equity
        for j in buy_idx:
            asset = self._assets_array[j]
            lot = self._lots[j]
            step = self._buy_steps[j]
            max_order_qty = self._max_order_quantities[j]
            gap_raw = float(buy_gap[j])
            if gap_raw <= 0:
                continue
            order_seq += 1
            ref_price = float(vwap_adj[j]) if tradable_price[j] else np.nan
            oid = f"{order_id_prefix}-{order_seq:06d}"
            orders.append(OrderRecord(
                order_id=oid, asset_id=asset, signal_date=signal_day, order_date=day,
                side="buy", target_quantity=gap_raw,
                target_amount=gap_raw * (vwap_raw[j] if tradable_price[j] else np.nan),
                reference_price=ref_price, reason="rebalance_increase",
                target_weight=float(tw_row[j]),
                current_weight=float(mkt_val[j] / equity), sequence=order_seq,
            ))
            _record_order(j, "buy", gap_raw, "rebalance_increase")
            exchange_qty = _round_buy_quantity(gap_raw, int(lot), int(step))
            if exchange_qty <= 0:
                why = "below_min_buy_quantity"
                fills.append(self._reject(oid, asset, day, "buy", ref_price, gap_raw, why))
                _record_fill(j, "buy", 0.0, np.nan, vwap_raw[j], "rejected", why)
                unfilled_rows.append({
                    "date": day, "asset_id": asset, "side": "buy",
                    "reason": why, "unfilled_quantity": gap_raw,
                    "reference_price_raw": vwap_raw[j],
                })
                continue
            exchange_capped = exchange_qty < gap_raw - 1e-9
            order_size_capped = exchange_qty > max_order_qty
            if order_size_capped:
                exchange_qty = _round_buy_quantity(
                    float(max_order_qty), int(lot), int(step)
                )
            blocked, why = self._blocked(ti, j, "buy", allow_buy, tradable_price)
            if blocked:
                fills.append(self._reject(oid, asset, day, "buy", ref_price, gap_raw, why))
                _record_fill(j, "buy", 0.0, np.nan, vwap_raw[j], "rejected", why)
                unfilled_rows.append({"date": day, "asset_id": asset, "side": "buy",
                                      "reason": why, "unfilled_quantity": gap_raw,
                                      "reference_price_raw": vwap_raw[j]})
                continue
            fill_price_raw = self.costs.slippage_price(float(vwap_raw[j]), "buy")
            if not np.isfinite(adv[j]) or adv[j] <= 0:
                fills.append(self._reject(oid, asset, day, "buy", ref_price, gap_raw, "adv_missing"))
                _record_fill(j, "buy", 0.0, np.nan, vwap_raw[j], "rejected", "adv_missing")
                unfilled_rows.append({
                    "date": day, "asset_id": asset, "side": "buy",
                    "reason": "adv_missing", "unfilled_quantity": gap_raw,
                    "reference_price_raw": vwap_raw[j],
                })
                continue
            qty_raw, capped = self._apply_adv(
                exchange_qty,
                adv[j],
                fill_price_raw,
                max_part,
                lot,
                minimum=int(lot),
                step=int(step),
            )
            # 现金约束必须用实际费率表和最低佣金，不能使用固定费率垫。
            budget = max(cash - reserve, 0.0)
            max_qty = self._max_affordable_buy_quantity(
                qty_raw,
                fill_price_raw,
                float(vwap_raw[j]),
                day,
                budget,
                minimum=int(lot),
                step=int(step),
            )
            cash_capped = max_qty < qty_raw
            qty_raw = min(qty_raw, max_qty)
            qty_raw, turnover_capped = self._apply_notional_cap(
                qty_raw, fill_price_raw, remaining_turnover_notional, lot,
                minimum=int(lot),
                step=int(step),
            )
            if qty_raw <= 0:
                why = (
                    "turnover_cap_zero" if turnover_capped
                    else ("insufficient_cash" if cash_capped else "adv_cap_zero")
                )
                fills.append(self._reject(oid, asset, day, "buy", ref_price, gap_raw, why))
                _record_fill(j, "buy", 0.0, np.nan, vwap_raw[j], "rejected", why.removesuffix("_zero"))
                unfilled_rows.append({"date": day, "asset_id": asset, "side": "buy",
                                      "reason": why.removesuffix("_zero"),
                                      "unfilled_quantity": gap_raw,
                                      "reference_price_raw": vwap_raw[j]})
                continue
            notional = qty_raw * fill_price_raw
            remaining_turnover_notional = max(remaining_turnover_notional - notional, 0.0)
            fc = self.costs.compute(side="buy", filled_quantity=qty_raw,
                                    fill_price=fill_price_raw,
                                    reference_price=float(vwap_raw[j]), fill_date=day)
            qty_adj = qty_raw * ratio[j]
            shares[j] += qty_adj
            cost_basis[j] += notional + fc.explicit_total
            cash -= notional + fc.explicit_total
            cash_tolerance = max(1e-8, equity * 1e-12)
            if cash < -cash_tolerance:
                raise RuntimeError(f"买入后现金为负: {asset} {day.date()} cash={cash}")
            if cash < 0:
                cash = 0.0
            total_cost += fc.total
            explicit_cost += fc.explicit_total
            buy_amount += notional
            buy_reference_amount += qty_raw * float(vwap_raw[j])
            bought_adj[j] += qty_adj
            status = (
                "filled"
                if not (
                    exchange_capped or order_size_capped or capped
                    or cash_capped or turnover_capped
                )
                else "partial"
            )
            fills.append(FillRecord(
                order_id=oid, asset_id=asset, order_date=day, fill_date=day, side="buy",
                fill_price=fill_price_raw, reference_price=float(vwap_raw[j]),
                filled_quantity=qty_raw, filled_amount=notional,
                unfilled_quantity=max(gap_raw - qty_raw, 0.0),
                commission=fc.commission, stamp_duty=fc.stamp_duty,
                transfer_fee=fc.transfer_fee, slippage_cost=fc.slippage_cost,
                impact_cost=fc.impact_cost, status=status,
                reject_reason=(
                    "turnover_cap" if turnover_capped
                    else (
                        "adv_cap" if capped
                        else (
                            "insufficient_cash" if cash_capped
                            else (
                                "order_size_cap" if order_size_capped
                                else ("lot_size_rounding" if exchange_capped else "")
                            )
                        )
                    )
                ),
                adv_participation=float(notional / adv[j]) if adv[j] and adv[j] > 0 else np.nan,
            ))
            _record_fill(
                j, "buy", qty_raw, fill_price_raw, float(vwap_raw[j]), status,
                "turnover_cap" if turnover_capped
                else (
                    "adv_cap" if capped
                    else (
                        "insufficient_cash" if cash_capped
                        else (
                            "order_size_cap" if order_size_capped
                            else ("lot_size_rounding" if exchange_capped else "")
                        )
                    )
                ),
            )
            if status == "partial":
                unfilled_rows.append({
                    "date": day, "asset_id": asset, "side": "buy",
                    "reason": (
                        "turnover_cap" if turnover_capped
                        else (
                            "adv_cap" if capped
                            else (
                                "insufficient_cash" if cash_capped
                                else (
                                    "order_size_cap" if order_size_capped
                                    else "lot_size_rounding"
                                )
                            )
                        )
                    ),
                    "unfilled_quantity": gap_raw - qty_raw,
                    "reference_price_raw": vwap_raw[j],
                })

        # ---- 组装持仓迁移记录 ----
        tol = 1e-9
        active_period_idx = np.flatnonzero((raw_held > tol) | (raw_target_shares > tol))
        recorded_period_idx = np.fromiter(
            sorted(set(pp_order_qty_raw) | set(pp_fill_qty_raw)),
            dtype="int64",
        )
        for j in np.union1d(active_period_idx, recorded_period_idx):
            pre_raw = float(raw_held[j])
            tgt_raw = float(raw_target_shares[j])
            if pre_raw <= tol and tgt_raw <= tol and j not in pp_order_qty_raw:
                continue
            order_raw = pp_order_qty_raw.get(j, 0.0)
            fill_raw = pp_fill_qty_raw.get(j, 0.0)
            if tgt_raw <= tol < pre_raw:
                action = "exit"
            elif tgt_raw > pre_raw + tol:
                action = "buy"
            elif tgt_raw < pre_raw - tol:
                action = "sell"
            else:
                action = "hold"
            status = pp_status.get(j, "no_order")
            reject_reason = pp_reject_reason.get(j, "")
            reason = pp_reason.get(j, "hold")
            fill_price = pp_fill_price.get(j, np.nan)
            ref_price = pp_reference_price.get(j, np.nan)
            if abs(order_raw) > tol:
                fill_ratio = min(max(abs(fill_raw / order_raw), 0.0), 1.0)
            elif abs(fill_raw) > tol:
                fill_ratio = 1.0
            else:
                fill_ratio = 1.0 if action == "hold" else 0.0
            post_raw = pre_raw + fill_raw
            ratio_j = ratio[j] if np.isfinite(ratio[j]) and ratio[j] > 0 else 1.0
            pre_adj = float(shares_start[j])
            post_adj = float(shares[j])
            tgt_adj = tgt_raw * ratio_j
            order_adj = order_raw * ratio_j
            fill_adj = fill_raw * ratio_j
            position_period_rows.append(PositionPeriodRecord(
                signal_date=signal_day, date=day, asset_id=self._assets_array[j],
                action=action,
                pre_quantity_raw=pre_raw, pre_quantity_adjusted=pre_adj,
                target_quantity_raw=tgt_raw, target_quantity_adjusted=tgt_adj,
                order_quantity_raw=order_raw, order_quantity_adjusted=order_adj,
                fill_quantity_raw=fill_raw, fill_quantity_adjusted=fill_adj,
                post_quantity_raw=post_raw, post_quantity_adjusted=post_adj,
                reason=reason, fill_price=fill_price, reference_price=ref_price,
                fill_ratio=fill_ratio, status=status, reject_reason=reject_reason,
            ))

        return {
            "cash": cash, "cost": total_cost, "explicit_cost": explicit_cost,
            "buy_amount": buy_amount, "sell_amount": sell_amount,
            "buy_reference_amount": buy_reference_amount,
            "sell_reference_amount": sell_reference_amount,
            "realized": realized, "order_seq": order_seq,
            "position_period_rows": position_period_rows,
        }

    # ---------- 辅助 ----------

    def _blocked(self, ti, j, side, allow_mask, tradable_price) -> tuple[bool, str]:
        """返回 (是否拦截, 原因)。原因粒度足够定位到具体规则。"""
        if not tradable_price[j]:
            return True, "no_valid_price"
        if self._is_susp[ti, j]:
            return True, "suspended"
        if side == "buy":
            if self._lu_block[ti, j]:
                return True, "limit_up_block"
            if not allow_mask[j]:
                return True, "not_buyable"
        else:
            if self._ld_block[ti, j]:
                return True, "limit_down_block"
            if not allow_mask[j]:
                return True, "not_sellable"
        return False, ""

    @staticmethod
    def _apply_adv(qty_raw, adv, price, max_part, lot, *, minimum: int, step: int):
        """ADV 参与率上限。返回 (可成交股数, 是否被截断)。"""
        if not np.isfinite(adv) or adv <= 0 or not np.isfinite(price) or price <= 0:
            return 0.0, qty_raw > 0
        max_notional = adv * max_part
        max_qty = max_notional / price
        if qty_raw <= max_qty:
            return qty_raw, False
        capped = _round_buy_quantity(max_qty, minimum, step)
        return max(capped, 0.0), True

    @staticmethod
    def _apply_notional_cap(qty_raw, price, remaining, lot, *, minimum: int, step: int):
        """Apply the remaining executed-notional budget for max_turnover."""
        if not np.isfinite(remaining):
            return qty_raw, False
        if remaining <= 0 or not np.isfinite(price) or price <= 0:
            return 0.0, qty_raw > 0
        max_qty = remaining / price
        if qty_raw <= max_qty + 1e-12:
            return qty_raw, False
        capped = _round_buy_quantity(max_qty, minimum, step)
        return max(capped, 0.0), True

    def _max_affordable_buy_quantity(
        self, qty_raw, price, reference_price, day, budget, *, minimum: int, step: int
    ) -> float:
        """Largest exchange-valid quantity whose notional plus explicit fees fits cash."""
        qty = _round_buy_quantity(qty_raw, minimum, step)
        if qty <= 0 or budget <= 0:
            return 0.0

        def affordable(candidate: float) -> bool:
            fees = self.costs.compute(
                side="buy",
                filled_quantity=candidate,
                fill_price=price,
                reference_price=reference_price,
                fill_date=day,
            ).explicit_total
            return candidate * price + fees <= budget + 1e-9

        if affordable(qty):
            return qty
        max_steps = int(np.floor((qty - minimum) / step + 1e-9))
        lo, hi = 0, max_steps
        best = 0.0
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = float(minimum + mid * step)
            if affordable(candidate):
                best = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    @staticmethod
    def _reject(oid, asset, day, side, ref_price, qty, why) -> FillRecord:
        return FillRecord(
            order_id=oid, asset_id=asset, order_date=day, fill_date=day, side=side,
            fill_price=np.nan, reference_price=ref_price, filled_quantity=0.0,
            filled_amount=0.0, unfilled_quantity=qty, commission=0.0, stamp_duty=0.0,
            transfer_fee=0.0, slippage_cost=0.0, impact_cost=0.0,
            status="rejected", reject_reason=why, adv_participation=np.nan,
        )

    def _finalize(
        self, holdings_shares, holdings_cost_basis, holdings_unrealized_pnl,
        holdings_value, ledger_rows, orders, fills, unfilled_rows,
        initial_capital, identity_rows, position_period_rows,
    ) -> ExecutionOutput:
        dates, assets = self.dates, self.assets
        ledger = pd.DataFrame(ledger_rows).set_index("date")
        hv = pd.DataFrame(holdings_value, index=dates, columns=assets)
        net = ledger["net_assets"]
        actual_weights = hv.div(net.where(net > 0), axis=0).fillna(0.0)

        # 账户恒等式校验 (规范 8.3)。gross_pnl 由持仓/成交独立重算, 不是残差回填,
        # 所以 residual 是真的对账误差, 能抓出记账错误。
        identity = pd.DataFrame(identity_rows).set_index("date")
        identity["residual"] = identity["expected_close"] - identity["close_net_assets"]
        identity["residual_bps_of_nav"] = (
            identity["residual"] / identity["close_net_assets"].where(net > 0) * 10_000
        )
        max_residual_bps = float(identity["residual_bps_of_nav"].abs().max())
        if not np.isfinite(max_residual_bps) or max_residual_bps > 1e-6:
            raise ArithmeticError(f"账户恒等式校验失败: max_abs_residual={max_residual_bps} bps")
        min_cash = float(ledger["cash"].min())
        if min_cash < -max(1e-8, float(initial_capital) * 1e-12):
            raise ArithmeticError(f"账户现金为负: min_cash={min_cash}")

        cost_rows = [
            {
                "date": f.fill_date, "asset_id": f.asset_id, "side": f.side,
                "commission": f.commission, "stamp_duty": f.stamp_duty,
                "transfer_fee": f.transfer_fee, "slippage_cost": f.slippage_cost,
                "impact_cost": f.impact_cost,
                "total": f.commission + f.stamp_duty + f.transfer_fee
                         + f.slippage_cost + f.impact_cost,
                "filled_amount": f.filled_amount,
            }
            for f in fills if f.filled_quantity > 0
        ]
        costs_df = (
            pd.DataFrame(cost_rows).groupby("date")[
                ["commission", "stamp_duty", "transfer_fee", "slippage_cost",
                 "impact_cost", "total", "filled_amount"]
            ].sum().reindex(dates).fillna(0.0)
            if cost_rows else
            pd.DataFrame(
                0.0, index=dates,
                columns=["commission", "stamp_duty", "transfer_fee", "slippage_cost",
                         "impact_cost", "total", "filled_amount"],
            )
        )

        unfilled = (
            pd.DataFrame(unfilled_rows) if unfilled_rows else
            pd.DataFrame(columns=[
                "date", "asset_id", "side", "reason", "unfilled_quantity",
                "reference_price_raw", "unfilled_amount",
            ])
        )
        if len(unfilled):
            unfilled["unfilled_amount"] = (
                unfilled["unfilled_quantity"] * unfilled["reference_price_raw"]
            )

        return ExecutionOutput(
            orders=tuple(orders), fills=tuple(fills),
            holdings_shares=pd.DataFrame(holdings_shares, index=dates, columns=assets),
            holdings_cost_basis=pd.DataFrame(
                holdings_cost_basis, index=dates, columns=assets
            ),
            holdings_unrealized_pnl=pd.DataFrame(
                holdings_unrealized_pnl, index=dates, columns=assets
            ),
            holdings_value=hv, actual_weights=actual_weights, cash_ledger=ledger,
            costs=costs_df, unfilled_summary=unfilled,
            accounting_identity=identity,
            position_period_records=tuple(position_period_rows),
        )
