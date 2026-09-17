from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from qbt_web.services.style_comparison import compare_style_run


class StyleComparisonTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.run_dir = self.root / "run"
        self.warehouse_dir = self.root / "warehouse"
        self.weights_dir = self.root / "index_weights"
        self.run_dir.mkdir()
        (self.warehouse_dir / "benchmarks").mkdir(parents=True)
        self.weights_dir.mkdir()

        self.dates = pd.date_range("2024-01-02", periods=3, freq="B", name="date")
        columns = pd.MultiIndex.from_product(
            [["portfolio", "index", "active"], ["size", "value"]],
            names=["exposure_type", "style"],
        )
        stored = pd.DataFrame(index=self.dates, columns=columns, dtype="float64")
        stored[("portfolio", "size")] = [1.5, 1.6, 1.7]
        stored[("portfolio", "value")] = [0.4, 0.5, 0.6]
        stored[("index", "size")] = [0.2, 0.2, 0.2]
        stored[("index", "value")] = [0.1, 0.1, 0.1]
        stored["active"] = stored["portfolio"].to_numpy() - stored["index"].to_numpy()
        stored.to_parquet(self.run_dir / "style_exposures.parquet")

        manifest = {
            "schema_version": "qbt_benchmark_quotes/v1",
            "benchmarks": [
                {
                    "benchmark_id": "000300.SH",
                    "name": "沪深300",
                    "file": "000300.SH.parquet",
                    "source_uri": "fixture",
                }
            ],
        }
        (self.warehouse_dir / "benchmarks" / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        pd.DataFrame(
            {
                "snapshot_date": [pd.Timestamp("2024-01-01")] * 2,
                "asset_id": ["000001.SZ", "000002.SZ"],
                "weight": [0.25, 0.75],
            }
        ).to_parquet(self.weights_dir / "000300.SH_monthly.parquet", index=False)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _compare(self, benchmark_id: str):
        return compare_style_run(
            self.run_dir,
            benchmark_id,
            self.warehouse_dir,
            barra_dir=self.root / "barra",
            index_weights_dir=self.weights_dir,
            index_source_dir=self.root / "index_source",
        )

    def test_embedded_benchmark_preserves_stored_exposures(self) -> None:
        result = self._compare("ALL_A_EQ")
        self.assertEqual(result["timeseries"]["portfolio"]["size"], [1.5, 1.6, 1.7])
        self.assertEqual(result["timeseries"]["index"]["size"], [0.2, 0.2, 0.2])
        self.assertAlmostEqual(result["timeseries"]["active"]["size"][0], 1.3)

    @patch("qbt_web.services.style_comparison.load_barra_style_exposures")
    def test_external_benchmark_changes_only_index_and_active(self, load_barra) -> None:
        size = pd.DataFrame(
            [[1.0, 3.0]] * 3,
            index=self.dates,
            columns=["000001.SZ", "000002.SZ"],
        )
        value = pd.DataFrame(
            [[-1.0, 1.0]] * 3,
            index=self.dates,
            columns=["000001.SZ", "000002.SZ"],
        )
        load_barra.return_value = (
            {"Size": size, "Value": value},
            pd.DataFrame(),
            {"data_source": "rqdata_barra_v2"},
        )

        embedded = self._compare("ALL_A_EQ")
        external = self._compare("000300.SH")

        self.assertEqual(
            embedded["timeseries"]["portfolio"], external["timeseries"]["portfolio"]
        )
        self.assertEqual(external["timeseries"]["index"]["size"], [2.5, 2.5, 2.5])
        self.assertEqual(external["timeseries"]["index"]["value"], [0.5, 0.5, 0.5])
        self.assertAlmostEqual(external["timeseries"]["active"]["size"][0], -1.0)
        self.assertNotEqual(
            embedded["timeseries"]["active"]["size"],
            external["timeseries"]["active"]["size"],
        )
        self.assertEqual(external["benchmark"]["weight_source"], "pit_monthly_index_weights")


if __name__ == "__main__":
    unittest.main()
