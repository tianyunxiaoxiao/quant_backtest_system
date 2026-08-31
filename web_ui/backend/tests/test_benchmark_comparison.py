from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from qbt_web.services.benchmark_comparison import compare_run, list_benchmarks


class BenchmarkComparisonTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.run_dir = self.root / "run"
        self.benchmark_dir = self.root / "warehouse" / "benchmarks"
        self.run_dir.mkdir()
        self.benchmark_dir.mkdir(parents=True)

        dates = pd.date_range("2024-01-02", periods=8, freq="B")
        portfolio_returns = pd.Series(
            [0.0, 0.02, -0.01, 0.01, 0.005, -0.004, 0.006, 0.003], index=dates
        )
        embedded_benchmark = pd.Series(
            [0.0, 0.01, -0.005, 0.004, 0.002, -0.001, 0.002, 0.001], index=dates
        )
        frame = pd.DataFrame(
            {
                "portfolio_net_return": portfolio_returns,
                "portfolio_gross_return": portfolio_returns + 0.0001,
                "benchmark_return": embedded_benchmark,
                "portfolio_nav": (1.0 + portfolio_returns).cumprod(),
                "benchmark_nav": (1.0 + embedded_benchmark).cumprod(),
                "turnover": 0.05,
                "trade_cost": 10.0,
                "n_holdings": 20,
                "top10_concentration": 0.5,
                "cash_ratio": 0.01,
                "hhi": 0.05,
            }
        )
        frame["excess_return"] = frame["portfolio_net_return"] - frame["benchmark_return"]
        frame["excess_nav"] = frame["portfolio_nav"] / frame["benchmark_nav"]
        frame.to_parquet(self.run_dir / "daily_returns.parquet")

        pd.DataFrame(
            {
                "trade_cost": 10.0,
                "cash_ratio": 0.01,
                "n_holdings": 20,
                "turnover": 0.05,
            },
            index=dates,
        ).to_parquet(self.run_dir / "cash_ledger.parquet")
        pd.DataFrame(0.05, index=dates, columns=[f"asset_{value}" for value in range(20)]).to_parquet(
            self.run_dir / "actual_weights.parquet"
        )
        (self.run_dir / "performance_report.json").write_text(
            json.dumps(
                {
                    "full_sample": {
                        "turnover_annual_oneway": 12.34,
                        "total_cost": 80.0,
                        "avg_holdings": 20.0,
                        "avg_top10_concentration": 0.5,
                        "avg_cash_ratio": 0.01,
                        "hhi": 0.05,
                    }
                }
            ),
            encoding="utf-8",
        )

        quote_dates = pd.date_range("2024-01-01", periods=10, freq="B")
        quotes = pd.DataFrame(
            {
                "date": quote_dates,
                "close": [100.0, 101.0, 100.0, 103.0, 102.0, 104.0, 105.0, 103.0, 106.0, 107.0],
            }
        )
        quotes.to_parquet(self.benchmark_dir / "000300.SH.parquet", index=False)
        manifest = {
            "schema_version": "qbt_benchmark_quotes/v1",
            "benchmarks": [
                {
                    "benchmark_id": "000300.SH",
                    "name": "沪深300",
                    "file": "000300.SH.parquet",
                    "source_uri": "fixture.xlsx",
                    "source_sha256": "sha256:test",
                    "date_min": "2024-01-01",
                    "date_max": "2024-01-12",
                }
            ],
        }
        (self.benchmark_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_lists_embedded_and_external_benchmarks(self) -> None:
        options = list_benchmarks(self.root / "warehouse")
        self.assertEqual([item["benchmark_id"] for item in options], ["ALL_A_EQ", "000300.SH"])

    def test_switch_recalculates_comparison_without_changing_portfolio(self) -> None:
        original = pd.read_parquet(self.run_dir / "daily_returns.parquet")
        embedded = compare_run(self.run_dir, "ALL_A_EQ", self.root / "warehouse")
        external = compare_run(self.run_dir, "000300.SH", self.root / "warehouse")
        after = pd.read_parquet(self.run_dir / "daily_returns.parquet")

        self.assertEqual(embedded["summary"]["total_return"], external["summary"]["total_return"])
        self.assertNotEqual(
            embedded["summary"]["benchmark_total_return"],
            external["summary"]["benchmark_total_return"],
        )
        self.assertNotEqual(embedded["summary"]["beta"], external["summary"]["beta"])
        self.assertEqual(external["nav"]["series"][1]["values"][0], 0.0)
        self.assertNotEqual(
            embedded["charts"]["monthly"]["series"][1]["values"],
            external["charts"]["monthly"]["series"][1]["values"],
        )
        external_monthly = external["charts"]["monthly"]["series"]
        portfolio_monthly = external_monthly[0]["values"][0]
        benchmark_monthly = external_monthly[1]["values"][0]
        expected_excess = (1.0 + portfolio_monthly) / (1.0 + benchmark_monthly) - 1.0
        self.assertAlmostEqual(external_monthly[2]["values"][0], expected_excess)
        self.assertNotEqual(
            embedded["charts"]["drawdown"]["series"][1]["values"],
            external["charts"]["drawdown"]["series"][1]["values"],
        )
        pd.testing.assert_frame_equal(original, after)

    def test_missing_benchmark_trading_date_is_rejected(self) -> None:
        quotes_path = self.benchmark_dir / "000300.SH.parquet"
        quotes = pd.read_parquet(quotes_path)
        quotes = quotes[quotes["date"] != pd.Timestamp("2024-01-08")]
        quotes.to_parquet(quotes_path, index=False)

        with self.assertRaisesRegex(ValueError, "缺少交易日"):
            compare_run(self.run_dir, "000300.SH", self.root / "warehouse")

    def test_legacy_return_artifact_restores_portfolio_metrics(self) -> None:
        path = self.run_dir / "daily_returns.parquet"
        legacy = pd.read_parquet(path).drop(
            columns=[
                "turnover",
                "trade_cost",
                "n_holdings",
                "top10_concentration",
                "cash_ratio",
                "hhi",
            ]
        )
        legacy.to_parquet(path)

        result = compare_run(self.run_dir, "000300.SH", self.root / "warehouse")
        performance = result["performance"]

        self.assertEqual(performance["turnover_annual_oneway"], 12.34)
        self.assertEqual(performance["total_cost"], 80.0)
        self.assertEqual(performance["avg_holdings"], 20.0)
        self.assertEqual(performance["avg_top10_concentration"], 0.5)
        self.assertEqual(performance["avg_cash_ratio"], 0.01)


if __name__ == "__main__":
    unittest.main()
