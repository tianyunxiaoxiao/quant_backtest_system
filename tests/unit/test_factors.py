"""Demo-factor definitions and no-lookahead invariants."""

import numpy as np
import pandas as pd
import pytest

from qbt.factors.demo import (
    DEMO_FACTOR_SPECS,
    build_all_demo_factors,
    build_bp_1_over_pb,
)


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
