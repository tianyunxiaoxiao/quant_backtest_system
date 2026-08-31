from __future__ import annotations

import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from fastapi import UploadFile
from qbt_web import db
from qbt_web.auth import Principal
from qbt_web.routers import factor_values
from qbt_web.routers.runs import _record_to_out
from qbt_web.services import runner
from qbt_web.services.factor_platform import PlatformFactorPayload


def _parquet_upload(values: list[list[float]]) -> UploadFile:
    frame = pd.DataFrame(
        values,
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
        columns=["000001.SZ", "600000.SH"],
    )
    content = io.BytesIO()
    frame.to_parquet(content)
    content.seek(0)
    return UploadFile(file=content, filename="alpha.parquet")


def _request(user_id: int = 0, role: str = "admin"):
    return SimpleNamespace(
        state=SimpleNamespace(principal=Principal(user_id, "tester", role, "test-csrf"))
    )


def _payload(version_id: str) -> dict:
    return {
        "factor_id": "alpha",
        "factor_source": "values",
        "factor_version_id": version_id,
        "factor_direction": None,
        "index_id": "ALL_A_EQ",
        "start_date": pd.Timestamp("2024-01-02").date(),
        "end_date": pd.Timestamp("2024-01-03").date(),
        "rebalance_frequency": "daily",
        "initial_capital": 1_000_000.0,
        "selection_fraction": 0.3,
        "weighting_method": "equal_weight",
        "max_single_weight": 0.1,
        "slippage_bps": 0.0,
        "commission_rate": 0.0,
        "stamp_duty_rate": None,
        "transfer_fee_rate": None,
        "fill_price_field": "adj_vwap",
        "lookback": None,
    }


def _parquet_bytes(values: list[list[float]]) -> bytes:
    upload = _parquet_upload(values)
    return upload.file.read()


class FactorVersionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.old_database_path = db.settings.database_path
        self.old_output_root = runner.settings.output_root
        self.old_factor_dir = factor_values._FACTOR_VALUES_DIR
        db.settings.database_path = self.root / "qbt.db"
        runner.settings.output_root = self.root / "runs"
        factor_values._FACTOR_VALUES_DIR = self.root / "factor_values"

    def tearDown(self) -> None:
        db.settings.database_path = self.old_database_path
        runner.settings.output_root = self.old_output_root
        factor_values._FACTOR_VALUES_DIR = self.old_factor_dir
        self.temp_dir.cleanup()

    def test_upload_keeps_versions_and_run_freezes_selected_version(self) -> None:
        first = asyncio.run(
            factor_values.upload_factor_values(
                _request(),
                _parquet_upload([[1.0, 2.0], [3.0, 4.0]]),
                name="Alpha",
                direction=1,
                source="factor-platform",
                factor_id="alpha",
            )
        )
        second = asyncio.run(
            factor_values.upload_factor_values(
                _request(),
                _parquet_upload([[10.0, 20.0], [30.0, 40.0]]),
                name="Alpha",
                direction=-1,
                source="factor-platform",
                factor_id="alpha",
            )
        )

        self.assertNotEqual(first.factor_version_id, second.factor_version_id)
        versions = db.list_factor_versions("alpha")
        self.assertEqual(len(versions), 2)
        self.assertEqual(len({record.file_path for record in versions}), 2)
        self.assertTrue(all(Path(record.file_path).is_file() for record in versions))

        submitted = runner.submit_run(_payload(first.factor_version_id))
        record = db.get_run(submitted["run_id"])
        config = json.loads(record.config_json)
        first_record = db.get_factor_version(first.factor_version_id)
        self.assertEqual(config["factor_version_id"], first.factor_version_id)
        self.assertEqual(config["factor_content_hash"], first.content_hash)
        self.assertEqual(config["factor_values_path"], first_record.file_path)
        self.assertEqual(config["factor_direction"], 1)
        self.assertEqual(config["min_commission"], 5.0)
        self.assertEqual(_record_to_out(record)["factor_name"], "Alpha")

    def test_platform_factor_is_fetched_and_frozen_before_queueing(self) -> None:
        version_id = "factor-run-20240801"
        content = _parquet_bytes([[1.0, 2.0], [3.0, 4.0]])

        class FakePlatformClient:
            def fetch_visible_version(self, factor_id, requested_version, cookie):
                self_outer.assertEqual(
                    (factor_id, requested_version, cookie),
                    ("alpha", version_id, "qpf_session=test-session"),
                )
                return PlatformFactorPayload(
                    metadata={
                        "factor_id": "alpha",
                        "name": "Research Alpha",
                        "direction": -1,
                        "source_run_id": version_id,
                        "summary": {"factor_version_id": version_id},
                    },
                    content=content,
                )

        self_outer = self
        payload = _payload(version_id)
        payload["factor_source"] = "platform"
        with patch.object(runner, "FactorPlatformClient", FakePlatformClient):
            submitted = runner.submit_run(
                payload,
                factor_platform_cookie="qpf_session=test-session",
            )

        record = db.get_run(submitted["run_id"])
        config = json.loads(record.config_json)
        frozen = db.get_factor_version(version_id)
        self.assertIsNotNone(frozen)
        self.assertEqual(config["factor_source"], "platform")
        self.assertEqual(config["factor_version_id"], version_id)
        self.assertEqual(config["factor_direction"], -1)
        self.assertEqual(_record_to_out(record)["factor_name"], "Research Alpha")
        self.assertEqual(config["factor_values_path"], frozen.file_path)
        self.assertTrue(Path(frozen.file_path).is_file())

    def test_target_weight_upload_freezes_direct_mode(self) -> None:
        created = asyncio.run(
            factor_values.upload_factor_values(
                _request(),
                _parquet_upload([[0.6, 0.2], [0.0, 0.0]]),
                name="Optimized Portfolio",
                direction=-1,
                source="optimizer",
                factor_id="optimized_portfolio",
                value_type="target_weights",
            )
        )
        self.assertEqual(created.value_type, "target_weights")
        self.assertEqual(created.direction, 1)
        version = db.get_factor_version(created.factor_version_id)
        self.assertEqual(version.value_type, "target_weights")

        payload = _payload(created.factor_version_id)
        payload["factor_id"] = "optimized_portfolio"
        submitted = runner.submit_run(payload)
        config = json.loads(db.get_run(submitted["run_id"]).config_json)
        self.assertEqual(config["portfolio_input_mode"], "direct_target_weights")
        self.assertEqual(config["factor_value_type"], "target_weights")
        self.assertEqual(config["business_summary"]["rebalance_frequency"], "target_weight_rows")
        self.assertIsNone(config["business_summary"]["selection_fraction"])


if __name__ == "__main__":
    unittest.main()
