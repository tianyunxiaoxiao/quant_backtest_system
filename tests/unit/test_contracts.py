"""契约层单元测试。"""

import pytest
from datetime import date

from qbt.contracts import (
    ClockConfig,
    ExecutionConfig,
    FactorFrame,
    LongOnlyFactorBacktestConfig,
    LongOnlyFactorBacktestRequest,
    SelectionConfig,
    WeightingConfig,
)


def test_clock_config_forbids_same_day_fill():
    with pytest.raises(ValueError):
        ClockConfig(order_lag_days=0)


def test_selection_fraction_validation():
    with pytest.raises(ValueError):
        SelectionConfig(selection_fraction=1.5)


def test_weighting_method_validation():
    with pytest.raises(ValueError):
        WeightingConfig(method="unknown")


def test_config_syncs_nested_fields():
    cfg = LongOnlyFactorBacktestConfig(selection_fraction=0.2, weighting_method="equal_weight")
    assert cfg.selection.selection_fraction == 0.2
    assert cfg.weighting.method == "equal_weight"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"initial_capital": float("nan")},
        {"initial_capital": float("inf")},
        {"selection_fraction": float("nan")},
    ],
)
def test_config_rejects_non_finite_top_level_values(kwargs):
    with pytest.raises(ValueError):
        LongOnlyFactorBacktestConfig(**kwargs)


def test_default_config_matches_mentor_acceptance_scope():
    cfg = LongOnlyFactorBacktestConfig()
    assert cfg.start_date == date(2018, 1, 1)
    assert cfg.end_date == date(2026, 3, 31)
    assert cfg.oos_start == date(2023, 1, 1)
    assert cfg.rebalance_frequency == "daily"
    assert cfg.execution.fill_price_field == "adj_vwap"


def test_request_requires_index_id():
    import pandas as pd
    values = pd.DataFrame({"A": [1.0, 2.0]}, index=pd.date_range("2020-01-02", periods=2))
    factor = FactorFrame(values=values, factor_id="test")
    with pytest.raises(ValueError):
        LongOnlyFactorBacktestRequest(factor=factor, index_id="")


def test_backtester_does_not_import_reporting():
    """规范硬性要求: 回测器包不得导入绘图库。"""
    import subprocess
    import sys

    code = (
        "import sys; "
        "import qbt.engine; "
        "assert 'matplotlib' not in sys.modules, 'engine imports matplotlib'; "
        "import qbt.engine.backtester as bt; "
        "assert not hasattr(bt, 'matplotlib'); "
        "assert not hasattr(bt, 'plt'); "
        "print('OK')"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={"PYTHONPATH": "src"})
    assert result.returncode == 0, result.stderr
