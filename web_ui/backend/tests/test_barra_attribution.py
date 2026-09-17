from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from qbt_web.services.barra_attribution import barra_style_attribution


class BarraAttributionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        self.dates = pd.date_range("2024-01-02", periods=4, freq="B", name="date")
        pd.DataFrame(
            {
                "portfolio_net_return": [0.0, 0.03, 0.01, 0.04],
                "benchmark_return": [0.0, 0.01, 0.01, 0.02],
            },
            index=self.dates,
        ).to_parquet(self.run_dir / "daily_returns.parquet")
        barra_style_attribution.cache_clear()

    def tearDown(self) -> None:
        barra_style_attribution.cache_clear()
        self.temp_dir.cleanup()

    @patch("qbt_web.services.barra_attribution.load_barra_factor_returns")
    @patch("qbt_web.services.barra_attribution.compare_style_run")
    def test_uses_lagged_active_exposure_and_reconciles_daily_returns(
        self, compare_style, load_returns
    ) -> None:
        compare_style.return_value = {
            "timeseries": {
                "dates": [str(value) for value in self.dates],
                "active": {"size": [1.0, 2.0, 3.0, 4.0]},
            }
        }
        load_returns.return_value = (
            pd.DataFrame({"size": [0.01] * 4}, index=self.dates),
            {"data_source": "fixture", "date_min": "2024-01-02", "date_max": "2024-01-05"},
        )

        result = barra_style_attribution(
            self.run_dir,
            "ALL_A_EQ",
            self.root / "warehouse",
            barra_dir=self.root / "barra",
            index_weights_dir=self.root / "weights",
            index_source_dir=self.root / "source",
        )

        series = {item["name"]: item["values"] for item in result["chart"]["series"]}
        self.assertIsNone(series["Barra风格收益贡献"][0])
        self.assertAlmostEqual(series["实际超额收益"][1], 0.02)
        self.assertAlmostEqual(series["Barra风格收益贡献"][1], 0.01)
        self.assertAlmostEqual(series["纯Alpha收益"][1], 0.01)
        self.assertAlmostEqual(series["Barra风格收益贡献"][2], 0.03)
        self.assertLessEqual(result["identity_max_abs_error"], 1e-15)
        self.assertEqual(result["method"]["exposure_lag_days"], 1)


if __name__ == "__main__":
    unittest.main()
