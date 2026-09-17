"""RQData Barra style exposure loader tests."""

import json

import numpy as np
import pandas as pd

from qbt.data.barra import (
    BARRA_STYLE_MAPPING,
    load_barra_factor_returns,
    load_barra_style_exposures,
)


def test_load_barra_styles_maps_ids_and_never_forward_fills(tmp_path):
    root = tmp_path / "barra"
    partition = root / "exposures" / "year=2024" / "month=01"
    partition.mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "model": "v2",
                "factor_return_first_date": "2024-01-02",
                "factor_return_last_date": "2024-01-04",
                "exposure_factor_columns": list(BARRA_STYLE_MAPPING.values()),
            }
        ),
        encoding="utf-8",
    )
    rows = []
    for date, value in [("2024-01-02", 1.0), ("2024-01-04", 2.0)]:
        row = {"date": pd.Timestamp(date), "order_book_id": "000001.XSHE"}
        row.update({column: value for column in BARRA_STYLE_MAPPING.values()})
        rows.append(row)
    pd.DataFrame(rows).to_parquet(partition / "barra_v2_exposure.parquet", index=False)

    dates = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04"])
    assets = pd.Index(["000001.SZ", "600000.SH"])
    valid = pd.DataFrame(True, index=dates, columns=assets)
    styles, coverage, metadata = load_barra_style_exposures(
        root, dates=dates, assets=assets, valid_mask=valid
    )

    assert set(styles) == set(BARRA_STYLE_MAPPING)
    assert styles["Size"].loc[pd.Timestamp("2024-01-02"), "000001.SZ"] == 1.0
    assert np.isnan(styles["Size"].loc[pd.Timestamp("2024-01-03"), "000001.SZ"])
    assert styles["Value"].loc[pd.Timestamp("2024-01-04"), "000001.SZ"] == 2.0
    assert coverage.loc[coverage["date"] == pd.Timestamp("2024-01-03"), "coverage"].eq(0).all()
    assert metadata["data_source"] == "rqdata_barra_v2"
    assert metadata["date_min"] == "2024-01-02"
    assert metadata["date_max"] == "2024-01-04"


def test_load_barra_factor_returns_maps_styles_and_never_fills_gaps(tmp_path):
    root = tmp_path / "barra"
    returns_dir = root / "factor_returns"
    returns_dir.mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps({"model": "v2"}), encoding="utf-8"
    )
    rows = []
    for date, value in [("2024-01-02", 0.01), ("2024-01-04", 0.02)]:
        row = {"date": pd.Timestamp(date)}
        row.update({column: value for column in BARRA_STYLE_MAPPING.values()})
        rows.append(row)
    pd.DataFrame(rows).to_parquet(
        returns_dir / "barra_v2_factor_returns_2024.parquet", index=False
    )

    dates = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04"])
    returns, metadata = load_barra_factor_returns(root, dates=dates)

    assert list(returns.columns) == [style.lower() for style in BARRA_STYLE_MAPPING]
    assert returns.loc[pd.Timestamp("2024-01-02"), "size"] == 0.01
    assert returns.loc[pd.Timestamp("2024-01-03")].isna().all()
    assert returns.loc[pd.Timestamp("2024-01-04"), "quality"] == 0.02
    assert metadata["date_min"] == "2024-01-02"
    assert metadata["date_max"] == "2024-01-04"
