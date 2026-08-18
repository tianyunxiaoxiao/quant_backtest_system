"""演示因子库 (导师 A6) 与外部因子值直接回测入口。"""

from qbt.factors.demo import (
    DEMO_FACTOR_SPECS,
    FactorSpec,
    build_all_demo_factors,
    build_bp_1_over_pb,
    build_demo_factor,
    build_reversal_20d,
    build_size_ln_float_mktcap,
    build_turnover_21d,
    build_volatility_252d,
)
from qbt.factors.values import (
    FactorValuesStats,
    inspect_factor_values,
    load_factor_values,
)

__all__ = [
    "DEMO_FACTOR_SPECS",
    "FactorSpec",
    "FactorValuesStats",
    "build_all_demo_factors",
    "build_bp_1_over_pb",
    "build_demo_factor",
    "build_reversal_20d",
    "build_size_ln_float_mktcap",
    "build_turnover_21d",
    "build_volatility_252d",
    "inspect_factor_values",
    "load_factor_values",
]
