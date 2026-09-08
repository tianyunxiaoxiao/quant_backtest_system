from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from scripts.update_rqdata_5min import BAR_HHMM, DATA_DTYPE, INDEX_DTYPE, update_five_minute_dataset


class FakeRQData:
    def get_price(self, ids, **kwargs):
        stamps = pd.DatetimeIndex(
            [pd.Timestamp(2026, 9, 2, value // 100, value % 100) for value in BAR_HHMM]
        )
        index = pd.MultiIndex.from_product([[ids[0]], stamps], names=["order_book_id", "datetime"])
        return pd.DataFrame(
            {
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 100.0,
                "total_turnover": 1000.0,
                "num_trades": 2.0,
            },
            index=index,
        )


def _seed(root: Path) -> Path:
    equities = root / "equities"
    equities.mkdir(parents=True)
    path = equities / "000001.XSHE.h5"
    data = np.zeros(48, dtype=DATA_DTYPE)
    data["datetime"] = 20260901150000
    index = np.array([(20260901, 0)], dtype=INDEX_DTYPE)
    with h5py.File(path, "w") as handle:
        handle.create_dataset("data", data=data, maxshape=(None,), chunks=True)
        handle.create_dataset("index", data=index, maxshape=(None,), chunks=True)
    (root / "manifest.csv").write_text("old")
    (root / "metadata.json").write_text(
        json.dumps({"end_date": "2026-09-01", "stored_price_basis": "raw_unadjusted"})
    )
    return path


def test_update_minbars_breaks_hardlink_before_appending(tmp_path: Path) -> None:
    current = tmp_path / "current"
    original = _seed(current)
    candidate = tmp_path / "candidate"
    os.mkdir(candidate)
    os.mkdir(candidate / "equities")
    os.link(original, candidate / "equities" / original.name)
    (candidate / "metadata.json").write_bytes((current / "metadata.json").read_bytes())
    (candidate / "manifest.csv").write_bytes((current / "manifest.csv").read_bytes())
    panel = tmp_path / "panel.json"
    panel.write_text(json.dumps({"tickers": ["000001.SZ"]}))

    result = update_five_minute_dataset(
        candidate, panel, end_date=date(2026, 9, 2), client=FakeRQData(), batch_size=10
    )

    with h5py.File(original, "r") as handle:
        assert len(handle["index"]) == 1
    with h5py.File(candidate / "equities" / original.name, "r") as handle:
        assert len(handle["index"]) == 2
        assert int(handle["index"][-1]["date"]) == 20260902
        assert int(handle["data"][-1]["datetime"]) == 20260902150000
    assert result["date_max"] == "2026-09-02"
    assert original.stat().st_ino != (candidate / "equities" / original.name).stat().st_ino
