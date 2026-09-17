"""Web API model validation tests."""

import pytest
from pydantic import ValidationError

from qbt_web.models import RunConfig


def test_run_config_uses_current_backtest_defaults():
    config = RunConfig(factor_id="test_factor")

    assert config.selection_fraction == 0.10
    assert config.fill_price_field == "adj_open"
    assert config.slippage_bps == 0.0


def test_run_config_accepts_selection_fraction_below_one_percent():
    config = RunConfig(factor_id="test_factor", selection_fraction=0.001)

    assert config.selection_fraction == 0.001


@pytest.mark.parametrize("selection_fraction", [0.0, -0.001])
def test_run_config_rejects_non_positive_selection_fraction(selection_fraction):
    with pytest.raises(ValidationError):
        RunConfig(factor_id="test_factor", selection_fraction=selection_fraction)
