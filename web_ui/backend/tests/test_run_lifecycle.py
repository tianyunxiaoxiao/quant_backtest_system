from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

from qbt_web import db
from qbt_web.auth import Principal
from qbt_web.models import RunNameUpdate
from qbt_web.routers import run_groups, runs
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
        self.assertIn("group_id", columns)
        self.assertIn("display_name", columns)

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

    def test_run_output_records_submitter(self) -> None:
        record = self.create_run(
            "alice-run", owner_user_id=7, owner_username="alice"
        )

        output = _record_to_out(record)

        self.assertEqual(output["owner_user_id"], 7)
        self.assertEqual(output["owner_username"], "alice")

    def test_run_display_name_is_persisted_and_returned(self) -> None:
        self.create_run("named-run", owner_user_id=7, owner_username="alice")

        self.assertTrue(db.rename_run("named-run", "中证1000 UMR 日频"))
        record = db.get_run("named-run")
        output = _record_to_out(record)

        self.assertEqual(record.display_name, "中证1000 UMR 日频")
        self.assertEqual(output["display_name"], "中证1000 UMR 日频")
        self.assertFalse(db.rename_run("missing-run", "不存在"))

    def test_only_owner_or_admin_can_rename_run(self) -> None:
        self.create_run("alice-run", owner_user_id=7, owner_username="alice")
        alice_request = SimpleNamespace(
            state=SimpleNamespace(principal=Principal(7, "alice", "researcher", "csrf"))
        )
        bob_request = SimpleNamespace(
            state=SimpleNamespace(principal=Principal(8, "bob", "researcher", "csrf"))
        )

        updated = asyncio.run(
            runs.update_run_name(
                "alice-run", RunNameUpdate(display_name="  UMR   日频  "), alice_request
            )
        )
        self.assertEqual(updated["display_name"], "UMR 日频")
        with self.assertRaises(HTTPException) as denied:
            asyncio.run(
                runs.update_run_name(
                    "alice-run", RunNameUpdate(display_name="越权修改"), bob_request
                )
            )
        self.assertEqual(denied.exception.status_code, 404)

    def test_run_groups_are_global_and_persist_assignment(self) -> None:
        self.create_run("alice-run", owner_user_id=7, owner_username="alice")
        alpha = db.create_run_group(
            "Alpha 研究", owner_user_id=7, owner_username="alice"
        )
        db.create_run_group("组合优化", owner_user_id=8, owner_username="bob")

        self.assertEqual(
            [group.name for group in db.list_run_groups(owner_user_id=7)],
            ["Alpha 研究", "混沌", "组合优化"],
        )
        self.assertTrue(db.assign_run_group("alice-run", alpha.id))
        self.assertEqual(db.get_run("alice-run").group_id, alpha.id)

        self.assertTrue(db.rename_run_group(alpha.id, "Alpha 精选"))
        self.assertEqual(db.get_run_group(alpha.id).name, "Alpha 精选")

        self.assertTrue(db.delete_run_group(alpha.id))
        reassigned = db.get_run("alice-run")
        self.assertEqual(db.get_run_group(reassigned.group_id).name, "混沌")

    def test_group_name_is_globally_unique(self) -> None:
        db.create_run_group("研究", owner_user_id=7, owner_username="alice")

        with self.assertRaises(sqlite3.IntegrityError):
            db.create_run_group("研究", owner_user_id=8, owner_username="bob")

    def test_users_share_the_same_default_group(self) -> None:
        alice = self.create_run(
            "alice-run", owner_user_id=7, owner_username="alice"
        )
        bob = self.create_run("bob-run", owner_user_id=8, owner_username="bob")

        self.assertEqual(alice.group_id, bob.group_id)
        self.assertEqual(db.get_run_group(alice.group_id).name, "混沌")

    def test_global_group_migration_merges_legacy_duplicates(self) -> None:
        db.settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        with db._conn() as conn:
            conn.executescript(db.SCHEMA)
            conn.execute("ALTER TABLE runs ADD COLUMN group_id INTEGER")
            now = db.utc_now()
            first = conn.execute(
                """
                INSERT INTO run_groups (owner_user_id, owner_username, name, created_at, updated_at)
                VALUES (7, 'alice', '研究', ?, ?)
                """,
                (now, now),
            ).lastrowid
            second = conn.execute(
                """
                INSERT INTO run_groups (owner_user_id, owner_username, name, created_at, updated_at)
                VALUES (8, 'bob', '研究', ?, ?)
                """,
                (now, now),
            ).lastrowid
            conn.execute(
                "INSERT INTO runs (id, status, factor_id, index_id, owner_user_id, group_id) "
                "VALUES ('alice-run', 'completed', 'f', 'ALL_A_EQ', 7, ?)",
                (first,),
            )
            conn.execute(
                "INSERT INTO runs (id, status, factor_id, index_id, owner_user_id, group_id) "
                "VALUES ('bob-run', 'completed', 'f', 'ALL_A_EQ', 8, ?)",
                (second,),
            )
            conn.execute(
                "INSERT INTO app_metadata (key, value) VALUES (?, ?)",
                (db._DEFAULT_GROUP_MIGRATION_KEY, now),
            )
            conn.commit()

        db.init_db()

        research_groups = [g for g in db.list_run_groups() if g.name == "研究"]
        self.assertEqual(len(research_groups), 1)
        self.assertEqual(db.get_run("alice-run").group_id, research_groups[0].id)
        self.assertEqual(db.get_run("bob-run").group_id, research_groups[0].id)

    def test_default_group_cannot_be_renamed_or_deleted(self) -> None:
        record = self.create_run(
            "alice-run", owner_user_id=7, owner_username="alice"
        )

        self.assertFalse(db.rename_run_group(record.group_id, "其他"))
        self.assertFalse(db.delete_run_group(record.group_id))
        self.assertEqual(db.get_run_group(record.group_id).name, "混沌")

    def test_null_assignment_returns_run_to_default_group(self) -> None:
        self.create_run("alice-run", owner_user_id=7, owner_username="alice")
        research = db.create_run_group(
            "研究", owner_user_id=7, owner_username="alice"
        )
        self.assertTrue(db.assign_run_group("alice-run", research.id))

        self.assertTrue(db.assign_run_group("alice-run", None))

        record = db.get_run("alice-run")
        self.assertEqual(db.get_run_group(record.group_id).name, "混沌")

    def test_new_run_is_assigned_to_default_chaos_group(self) -> None:
        record = self.create_run(
            "alice-run", owner_user_id=7, owner_username="alice"
        )

        group = db.get_run_group(record.group_id)

        self.assertIsNotNone(group)
        self.assertEqual(group.name, "混沌")
        self.assertEqual(group.owner_user_id, 0)

    def test_default_group_migration_moves_existing_runs_only_once(self) -> None:
        self.create_run("alice-run", owner_user_id=7, owner_username="alice")
        research = db.create_run_group(
            "研究", owner_user_id=7, owner_username="alice"
        )
        self.assertTrue(db.assign_run_group("alice-run", research.id))
        with db._conn() as conn:
            conn.execute(
                "DELETE FROM app_metadata WHERE key = ?",
                (db._DEFAULT_GROUP_MIGRATION_KEY,),
            )
            conn.commit()

        db.init_db()

        migrated = db.get_run("alice-run")
        self.assertEqual(db.get_run_group(migrated.group_id).name, "混沌")

        self.assertTrue(db.assign_run_group("alice-run", research.id))
        db.init_db()
        self.assertEqual(db.get_run("alice-run").group_id, research.id)

    def test_only_admin_can_manage_global_groups(self) -> None:
        researcher_request = SimpleNamespace(
            state=SimpleNamespace(
                principal=Principal(7, "alice", "researcher", "csrf")
            )
        )
        admin_request = SimpleNamespace(
            state=SimpleNamespace(
                principal=Principal(1, "admin", "admin", "csrf")
            )
        )

        with self.assertRaises(HTTPException) as denied:
            run_groups._require_admin(researcher_request)
        self.assertEqual(denied.exception.status_code, 403)
        self.assertTrue(run_groups._require_admin(admin_request).is_admin)


if __name__ == "__main__":
    unittest.main()
