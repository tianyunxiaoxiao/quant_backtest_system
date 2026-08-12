"""SQLite persistence for run metadata."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qbt_web.config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    factor_id TEXT NOT NULL,
    index_id TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT,
    rebalance_frequency TEXT,
    initial_capital REAL,
    selection_fraction REAL,
    weighting_method TEXT,
    max_single_weight REAL,
    fill_price_field TEXT,
    config_json TEXT,
    summary_json TEXT,
    error TEXT,
    artifact_dir TEXT,
    created_at TEXT,
    completed_at TEXT
);
"""


@dataclass(frozen=True)
class RunRecord:
    id: str
    status: str
    factor_id: str
    index_id: str
    start_date: str | None
    end_date: str | None
    rebalance_frequency: str | None
    initial_capital: float | None
    selection_fraction: float | None
    weighting_method: str | None
    max_single_weight: float | None
    fill_price_field: str | None
    config_json: str | None
    summary_json: str | None
    error: str | None
    artifact_dir: str | None
    created_at: str | None
    completed_at: str | None


@contextmanager
def _conn():
    conn = sqlite3.connect(str(settings.database_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_run(
    run_id: str,
    factor_id: str,
    index_id: str,
    config: dict[str, Any],
    artifact_dir: Path,
) -> None:
    init_db()
    summary = config.get("business_summary", {})
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO runs (
                id, status, factor_id, index_id, start_date, end_date,
                rebalance_frequency, initial_capital, selection_fraction,
                weighting_method, max_single_weight, fill_price_field,
                config_json, summary_json, error, artifact_dir, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "pending",
                factor_id,
                index_id,
                config.get("start_date"),
                config.get("end_date"),
                summary.get("rebalance_frequency"),
                summary.get("initial_capital"),
                summary.get("selection_fraction"),
                summary.get("weighting_method"),
                summary.get("max_single_weight"),
                summary.get("fill_price_field"),
                json.dumps(config, ensure_ascii=False),
                None,
                None,
                str(artifact_dir),
                _now(),
                None,
            ),
        )
        conn.commit()


def update_status(
    run_id: str,
    status: str,
    *,
    summary: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    fields = ["status = ?"]
    params: list[Any] = [status]
    if summary is not None:
        fields.append("summary_json = ?")
        params.append(json.dumps(summary, ensure_ascii=False))
    if error is not None:
        fields.append("error = ?")
        params.append(error)
    if status in ("completed", "failed"):
        fields.append("completed_at = ?")
        params.append(_now())
    params.append(run_id)
    with _conn() as conn:
        conn.execute(
            f"UPDATE runs SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        conn.commit()


def get_run(run_id: str) -> RunRecord | None:
    init_db()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return None if row is None else RunRecord(**dict(row))


def list_runs(limit: int = 200) -> list[RunRecord]:
    init_db()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [RunRecord(**dict(r)) for r in rows]


def delete_run(run_id: str) -> bool:
    init_db()
    with _conn() as conn:
        cur = conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        conn.commit()
    return cur.rowcount > 0
