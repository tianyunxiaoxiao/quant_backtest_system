"""Demo-factor definitions and no-lookahead invariants."""

import numpy as np
import pandas as pd
import pytest

from qbt.data.hashing import hash_frame
from qbt.factors.demo import (
    DEMO_FACTOR_SPECS,
    build_all_demo_factors,
    build_bp_1_over_pb,
)
from qbt.factors.values import load_factor_values, load_target_weights


def _sources() -> dict[str, pd.DataFrame]:
    dates = pd.date_range("2020-01-01", periods=320, freq="B")
    assets = ["A", "B", "C"]
    step = np.arange(len(dates), dtype="float64")[:, None]
    close = pd.DataFrame(
        10.0 * np.exp(step * np.array([[0.0002, -0.0001, 0.0003]])),
        index=dates,
        columns=assets,
    )
    return {
        "adj_close": close,
        "float_mktcap": close * pd.Series([1e8, 2e8, 3e8], index=assets),
        "turnover_rate": pd.DataFrame(
            np.tile(0.01 + (step % 17) / 10_000, (1, len(assets))),
            index=dates,
            columns=assets,
        ),
        "pb": pd.DataFrame(
            np.tile([1.0, 2.0, 4.0], (len(dates), 1)), index=dates, columns=assets
        ),
    }


def test_bp_is_inverse_of_positive_finite_pb():
    pb = pd.DataFrame([[1.0, 2.0, 0.0, -1.0, np.inf, np.nan]])
    bp = build_bp_1_over_pb(pb)
    assert bp.iloc[0, 0] == pytest.approx(1.0)
    assert bp.iloc[0, 1] == pytest.approx(0.5)
    assert bp.iloc[0, 2:].isna().all()
    assert DEMO_FACTOR_SPECS["bp_1_over_pb"].direction == 1


def test_imported_factor_hash_is_computed_after_axis_normalization():
    values = pd.DataFrame(
        [[1.0, 2.0]],
        index=pd.DatetimeIndex(["2023-01-03"]),
        columns=["B", "A"],
    )
    factor = load_factor_values(values, factor_id="imported", direction=1)
    assert factor.values.index.name == "date"
    assert factor.values.columns.name == "asset_id"
    assert factor.content_hash == hash_frame(factor.values)


def test_target_weights_preserve_cash_and_reject_invalid_rows():
    dates = pd.DatetimeIndex(["2023-01-03", "2023-01-04"])
    target = load_target_weights(
        pd.DataFrame({"A": [0.6, np.nan], "B": [0.2, 0.0]}, index=dates),
        portfolio_id="portfolio",
    )
    assert target.values.loc[dates[0]].sum() == pytest.approx(0.8)
    assert target.values.loc[dates[1]].sum() == pytest.approx(0.0)
    assert target.metadata["value_type"] == "target_weights"

    with pytest.raises(ValueError, match="超过 1"):
        load_target_weights(
            pd.DataFrame({"A": [0.7], "B": [0.4]}, index=dates[:1]),
            portfolio_id="overflow",
        )
    with pytest.raises(ValueError, match="不能为负"):
        load_target_weights(
            pd.DataFrame({"A": [-0.1]}, index=dates[:1]),
            portfolio_id="negative",
        )


def test_all_demo_factors_are_future_truncation_invariant():
    sources = _sources()
    cutoff = sources["adj_close"].index[279]
    full = build_all_demo_factors(sources)
    truncated_sources = {name: frame.loc[:cutoff] for name, frame in sources.items()}
    truncated = build_all_demo_factors(truncated_sources)

    assert set(full) == set(DEMO_FACTOR_SPECS)
    for factor_id in full:
        pd.testing.assert_frame_equal(
            full[factor_id].values.loc[:cutoff],
            truncated[factor_id].values,
        )
