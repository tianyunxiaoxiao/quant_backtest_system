from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qbt_web import db
from qbt_web.routers.runs import _record_to_out
from qbt_web.services import runner


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False

    def is_alive(self) -> bool:
        return not self.terminated and not self.killed

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def join(self, timeout=None) -> None:
        return None


class RunLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.old_database_path = db.settings.database_path
        db.settings.database_path = self.root / "qbt.db"
        runner._processes.clear()

    def tearDown(self) -> None:
        runner._processes.clear()
        db.settings.database_path = self.old_database_path
        self.temp_dir.cleanup()

    def create_run(
        self,
        run_id: str = "run-1",
        *,
        owner_user_id: int | None = None,
        owner_username: str | None = None,
    ) -> db.RunRecord:
        config = {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "business_summary": {
                "rebalance_frequency": "daily",
                "initial_capital": 1_000_000,
                "selection_fraction": 0.3,
                "weighting_method": "equal_weight",
                "max_single_weight": 0.1,
                "fill_price_field": "adj_vwap",
            },
        }
        db.create_run(
            run_id,
            "alpha",
            "ALL_A_EQ",
            config,
            self.root / run_id,
            owner_user_id=owner_user_id,
            owner_username=owner_username,
        )
        return db.get_run(run_id)

    def test_schema_migrates_existing_runs_table(self) -> None:
        db.settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        with db._conn() as conn:
            conn.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
            conn.commit()

        db.init_db()

        with db._conn() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
        self.assertIn("started_at", columns)
        self.assertIn("cancelled_at", columns)

    def test_pending_run_can_be_cancelled_without_worker(self) -> None:
        self.create_run()

        status = runner.cancel_run("run-1")
        record = db.get_run("run-1")

        self.assertEqual(status, "cancelled")
        self.assertEqual(record.status, "cancelled")
        self.assertIsNone(record.started_at)
        self.assertIsNotNone(record.cancelled_at)
        self.assertEqual(_record_to_out(record)["elapsed_seconds"], 0.0)

    def test_running_cancel_terminates_worker_and_blocks_completion_race(self) -> None:
        self.create_run()
        self.assertTrue(db.transition_status("run-1", "pending", "running"))
        process = FakeProcess()
        runner._processes["run-1"] = process

        status = runner.cancel_run("run-1")

        self.assertEqual(status, "cancelled")
        self.assertTrue(process.terminated)
        self.assertFalse(
            db.transition_status("run-1", "running", "completed", summary={"ok": True})
        )
        record = db.get_run("run-1")
        self.assertEqual(record.status, "cancelled")
        self.assertIsNone(record.summary_json)
        self.assertIsNotNone(record.started_at)
        self.assertIsNotNone(record.completed_at)

    def test_terminal_timing_is_stable(self) -> None:
        self.create_run()
        self.assertTrue(db.transition_status("run-1", "pending", "running"))
        self.assertTrue(db.transition_status("run-1", "running", "completed", summary={"value": 1}))
        first = _record_to_out(db.get_run("run-1"))
        second = _record_to_out(db.get_run("run-1"))

        self.assertGreaterEqual(first["elapsed_seconds"], 0.0)
        self.assertEqual(first["elapsed_seconds"], second["elapsed_seconds"])
        self.assertEqual(json.loads(db.get_run("run-1").summary_json), {"value": 1})

    def test_service_restart_closes_interrupted_runs(self) -> None:
        self.create_run("pending-run")
        self.create_run("running-run")
        self.assertTrue(db.transition_status("running-run", "pending", "running"))

        changed = db.fail_interrupted_runs()

        self.assertEqual(changed, 2)
        for run_id in ("pending-run", "running-run"):
            record = db.get_run(run_id)
            self.assertEqual(record.status, "failed")
            self.assertIn("服务重启", record.error)
            self.assertIsNotNone(record.completed_at)

    def test_run_listing_is_isolated_by_central_user_id(self) -> None:
        self.create_run("alice-run", owner_user_id=7, owner_username="alice")
        self.create_run("bob-run", owner_user_id=8, owner_username="bob")

        self.assertEqual([row.id for row in db.list_runs(owner_user_id=7)], ["alice-run"])
        self.assertEqual([row.id for row in db.list_runs(owner_user_id=8)], ["bob-run"])
        self.assertEqual(
            {row.id for row in db.list_runs()},
            {"alice-run", "bob-run"},
        )


if __name__ == "__main__":
    unittest.main()
