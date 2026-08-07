"""演示因子库 (导师 A6)。

导师口径: 20 日反转、BP=1/PB, 以及市值、换手、波动敏感性因子。

五个因子均使用当日快照或历史价量数据。BP 的 PB 快照是否完全 PIT 取决于
数据商重述政策, 因此在元数据中明确披露。方向
(direction) 在这里写死在元数据里, 跑完回测不许回头改符号 —— 这是 A6 明确
点出的纪律要求。

统一约定
--------
- 所有因子在 T 日收盘后可得, 只使用 <= T 的信息;
- 回测器再按 signal_lag_days 决定 T+1 下单, 因子层不做任何位移;
- 缺失值保留 NaN, 由 missing_policy="exclude_from_eligible" 在选股层剔除;
- direction=+1 表示因子值越大预期收益越高, -1 表示越小越好。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..contracts.frames import FactorFrame
from ..data.hashing import hash_frame

__all__ = [
    "FactorSpec",
    "DEMO_FACTOR_SPECS",
    "build_reversal_20d",
    "build_bp_1_over_pb",
    "build_size_ln_float_mktcap",
    "build_turnover_21d",
    "build_volatility_252d",
    "build_demo_factor",
    "build_all_demo_factors",
]


@dataclass(frozen=True)
class FactorSpec:
    """演示因子的静态声明。direction 事前写死, 事后不许改。"""

    factor_id: str
    direction: int
    description: str
    warmup_days: int
    inputs: tuple[str, ...]


DEMO_FACTOR_SPECS: dict[str, FactorSpec] = {
    "reversal_20d": FactorSpec(
        factor_id="reversal_20d",
        direction=-1,
        description="过去 20 个交易日复权收益率; 短期反转, 跌得多的后续预期更好, 故 direction=-1",
        warmup_days=21,
        inputs=("adj_close",),
    ),
    "bp_1_over_pb": FactorSpec(
        factor_id="bp_1_over_pb",
        direction=1,
        description="账面市值比 BP=1/PB; 仅正且有限的 PB 有效, BP 越高预期收益越高",
        warmup_days=1,
        inputs=("pb",),
    ),
    "size_ln_float_mktcap": FactorSpec(
        factor_id="size_ln_float_mktcap",
        direction=-1,
        description="ln(流通市值); 小市值溢价, 市值越小预期收益越高, 故 direction=-1",
        warmup_days=1,
        inputs=("float_mktcap",),
    ),
    "turnover_21d": FactorSpec(
        factor_id="turnover_21d",
        direction=-1,
        description="过去 21 个交易日日均换手率; 低换手(低关注度)溢价, 故 direction=-1",
        warmup_days=21,
        inputs=("turnover_rate",),
    ),
    "volatility_252d": FactorSpec(
        factor_id="volatility_252d",
        direction=-1,
        description="过去 252 个交易日日收益标准差; 低波异象, 故 direction=-1",
        warmup_days=252,
        inputs=("adj_close",),
    ),
}


def _min_periods(window: int) -> int:
    """要求窗口至少填到八成, 避免上市初期用 3 个点算出的极端值。"""
    return max(2, int(round(window * 0.8)))


def _mask_to_membership(values: pd.DataFrame, membership: pd.DataFrame | None) -> pd.DataFrame:
    """可选: 把非成分股位置置为 NaN。默认不裁, 交给选股层处理。"""
    if membership is None:
        return values
    aligned = membership.reindex(index=values.index, columns=values.columns).fillna(False)
    return values.where(aligned.astype(bool))


def build_reversal_20d(adj_close: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """过去 window 日复权收益率。T 日值 = close_T / close_{T-window} - 1。"""
    close = adj_close.astype("float64")
    # 只在两端都有价格时给值; pct_change 自带这个语义
    return close.pct_change(periods=window, fill_method=None)


def build_bp_1_over_pb(pb: pd.DataFrame) -> pd.DataFrame:
    """BP = 1/PB。非正、无穷和缺失 PB 均保留为缺失。"""
    import numpy as np

    clean = pb.astype("float64")
    valid = (clean > 0.0) & np.isfinite(clean)
    return (1.0 / clean.where(valid)).astype("float64")


def build_size_ln_float_mktcap(float_mktcap: pd.DataFrame) -> pd.DataFrame:
    """ln(流通市值)。非正值视为脏数据, 置 NaN。"""
    import numpy as np

    mc = float_mktcap.astype("float64")
    return pd.DataFrame(
        np.log(mc.where(mc > 0.0).to_numpy()), index=mc.index, columns=mc.columns
    )


def build_turnover_21d(turnover_rate: pd.DataFrame, window: int = 21) -> pd.DataFrame:
    """过去 window 日平均换手率。"""
    tr = turnover_rate.astype("float64")
    return tr.rolling(window=window, min_periods=_min_periods(window)).mean()


def build_volatility_252d(adj_close: pd.DataFrame, window: int = 252) -> pd.DataFrame:
    """过去 window 日日收益标准差 (未年化, 单调变换不影响排序)。"""
    ret = adj_close.astype("float64").pct_change(fill_method=None)
    return ret.rolling(window=window, min_periods=_min_periods(window)).std(ddof=1)


_BUILDERS = {
    "reversal_20d": lambda src: build_reversal_20d(src["adj_close"]),
    "bp_1_over_pb": lambda src: build_bp_1_over_pb(src["pb"]),
    "size_ln_float_mktcap": lambda src: build_size_ln_float_mktcap(src["float_mktcap"]),
    "turnover_21d": lambda src: build_turnover_21d(src["turnover_rate"]),
    "volatility_252d": lambda src: build_volatility_252d(src["adj_close"]),
}


def build_demo_factor(
    factor_id: str,
    sources: dict[str, pd.DataFrame],
    *,
    membership: pd.DataFrame | None = None,
    data_version: str = "unversioned",
    code_version: str = "unversioned",
) -> FactorFrame:
    """按 factor_id 造一个 FactorFrame, direction 从 spec 取, 不接受调用方覆盖。"""
    if factor_id not in DEMO_FACTOR_SPECS:
        raise KeyError(
            f"未知 factor_id={factor_id}; 已支持 {sorted(DEMO_FACTOR_SPECS)}"
        )
    spec = DEMO_FACTOR_SPECS[factor_id]
    missing = [c for c in spec.inputs if c not in sources]
    if missing:
        raise KeyError(f"{factor_id} 缺少输入字段: {missing}")

    values = _BUILDERS[factor_id](sources)
    values = _mask_to_membership(values, membership)
    values = values.astype("float64").replace([float("inf"), float("-inf")], pd.NA)
    values = values.astype("float64")

    coverage = float(values.notna().to_numpy().mean())
    return FactorFrame(
        values=values,
        factor_id=spec.factor_id,
        direction=spec.direction,
        description=spec.description,
        missing_policy="exclude_from_eligible",
        data_version=data_version,
        content_hash=hash_frame(values),
        code_version=code_version,
        metadata={
            "warmup_days": spec.warmup_days,
            "inputs": list(spec.inputs),
            "coverage_ratio": round(coverage, 6),
            "direction_locked_before_backtest": True,
            "source": "mentor A6 demo factor set",
        },
    )


def build_all_demo_factors(
    sources: dict[str, pd.DataFrame],
    *,
    membership: pd.DataFrame | None = None,
    data_version: str = "unversioned",
    code_version: str = "unversioned",
) -> dict[str, FactorFrame]:
    """一次造齐五个演示因子。"""
    out: dict[str, FactorFrame] = {}
    for fid in DEMO_FACTOR_SPECS:
        out[fid] = build_demo_factor(
            fid,
            sources,
            membership=membership,
            data_version=data_version,
            code_version=code_version,
        )
    return out
