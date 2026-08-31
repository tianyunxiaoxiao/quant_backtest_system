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
    owner_user_id INTEGER,
    owner_username TEXT,
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
    started_at TEXT,
    cancelled_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS imported_factors (
    factor_id TEXT PRIMARY KEY,
    owner_user_id INTEGER,
    owner_username TEXT,
    name TEXT NOT NULL,
    source TEXT,
    value_type TEXT NOT NULL DEFAULT 'factor_scores',
    direction INTEGER NOT NULL DEFAULT 1,
    file_path TEXT NOT NULL,
    n_dates INTEGER,
    n_assets INTEGER,
    date_start TEXT,
    date_end TEXT,
    coverage_ratio REAL,
    content_hash TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS factor_versions (
    version_id TEXT PRIMARY KEY,
    factor_id TEXT NOT NULL,
    owner_user_id INTEGER,
    owner_username TEXT,
    name TEXT NOT NULL,
    source TEXT,
    value_type TEXT NOT NULL DEFAULT 'factor_scores',
    direction INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    n_dates INTEGER,
    n_assets INTEGER,
    date_start TEXT,
    date_end TEXT,
    coverage_ratio REAL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(factor_id, content_hash)
);

CREATE INDEX IF NOT EXISTS factor_versions_factor_id
ON factor_versions(factor_id, created_at DESC);
"""


@dataclass(frozen=True)
class RunRecord:
    id: str
    owner_user_id: int | None
    owner_username: str | None
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
    started_at: str | None
    cancelled_at: str | None
    completed_at: str | None


@dataclass(frozen=True)
class ImportedFactorRecord:
    factor_id: str
    name: str
    source: str | None
    direction: int
    file_path: str
    n_dates: int | None
    n_assets: int | None
    date_start: str | None
    date_end: str | None
    coverage_ratio: float | None
    content_hash: str | None
    created_at: str | None
    value_type: str = "factor_scores"
    owner_user_id: int | None = None
    owner_username: str | None = None


@dataclass(frozen=True)
class FactorVersionRecord:
    version_id: str
    factor_id: str
    name: str
    source: str | None
    direction: int
    file_path: str
    n_dates: int | None
    n_assets: int | None
    date_start: str | None
    date_end: str | None
    coverage_ratio: float | None
    content_hash: str
    created_at: str
    value_type: str = "factor_scores"
    owner_user_id: int | None = None
    owner_username: str | None = None


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
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
        for name, definition in (
            ("started_at", "TEXT"),
            ("cancelled_at", "TEXT"),
            ("owner_user_id", "INTEGER"),
            ("owner_username", "TEXT"),
        ):
            if name not in columns:
                conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")
        for table in ("imported_factors", "factor_versions"):
            table_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if "value_type" not in table_columns:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN value_type TEXT NOT NULL "
                    "DEFAULT 'factor_scores'"
                )
            for name, definition in (
                ("owner_user_id", "INTEGER"),
                ("owner_username", "TEXT"),
            ):
                if name not in table_columns:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_now() -> str:
    return _now()


def create_run(
    run_id: str,
    factor_id: str,
    index_id: str,
    config: dict[str, Any],
    artifact_dir: Path,
    *,
    owner_user_id: int | None = None,
    owner_username: str | None = None,
) -> None:
    init_db()
    summary = config.get("business_summary", {})
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO runs (
                id, owner_user_id, owner_username, status, factor_id, index_id, start_date, end_date,
                rebalance_frequency, initial_capital, selection_fraction,
                weighting_method, max_single_weight, fill_price_field,
                config_json, summary_json, error, artifact_dir, created_at,
                started_at, cancelled_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                owner_user_id,
                owner_username,
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
                None,
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
    if status == "running":
        fields.append("started_at = COALESCE(started_at, ?)")
        params.append(_now())
    if status == "cancelled":
        fields.append("cancelled_at = COALESCE(cancelled_at, ?)")
        params.append(_now())
    if status in ("completed", "failed", "cancelled"):
        fields.append("completed_at = ?")
        params.append(_now())
    params.append(run_id)
    with _conn() as conn:
        conn.execute(
            f"UPDATE runs SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        conn.commit()


def transition_status(
    run_id: str,
    expected: str,
    status: str,
    *,
    summary: dict[str, Any] | None = None,
    error: str | None = None,
) -> bool:
    """Atomically move a run between lifecycle states."""
    fields = ["status = ?"]
    params: list[Any] = [status]
    now = _now()
    if summary is not None:
        fields.append("summary_json = ?")
        params.append(json.dumps(summary, ensure_ascii=False))
    if error is not None:
        fields.append("error = ?")
        params.append(error)
    if status == "running":
        fields.append("started_at = COALESCE(started_at, ?)")
        params.append(now)
    if status == "cancelled":
        fields.append("cancelled_at = COALESCE(cancelled_at, ?)")
        params.append(now)
    if status in ("completed", "failed", "cancelled"):
        fields.append("completed_at = ?")
        params.append(now)
    params.extend([run_id, expected])
    with _conn() as conn:
        cursor = conn.execute(
            f"UPDATE runs SET {', '.join(fields)} WHERE id = ? AND status = ?",
            params,
        )
        conn.commit()
    return cursor.rowcount == 1


def get_run(run_id: str) -> RunRecord | None:
    init_db()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return None if row is None else RunRecord(**dict(row))


def list_runs(limit: int = 200, *, owner_user_id: int | None = None) -> list[RunRecord]:
    init_db()
    with _conn() as conn:
        if owner_user_id is None:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs WHERE owner_user_id = ? ORDER BY created_at DESC LIMIT ?",
                (owner_user_id, limit),
            ).fetchall()
    return [RunRecord(**dict(r)) for r in rows]


def fail_interrupted_runs() -> int:
    """Close active records left behind by a previous service instance."""
    now = _now()
    with _conn() as conn:
        cursor = conn.execute(
            """
            UPDATE runs
            SET status = 'failed',
                error = COALESCE(error, '回测服务重启，任务已中断'),
                completed_at = ?
            WHERE status IN ('pending', 'running')
            """,
            (now,),
        )
        conn.commit()
    return cursor.rowcount


def delete_run(run_id: str) -> bool:
    init_db()
    with _conn() as conn:
        cur = conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Imported factor values registry (2026-08-18)
# ---------------------------------------------------------------------------


def create_imported_factor(rec: ImportedFactorRecord) -> None:
    init_db()
    with _conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO imported_factors (
                factor_id, owner_user_id, owner_username, name, source, value_type, direction, file_path,
                n_dates, n_assets, date_start, date_end,
                coverage_ratio, content_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec.factor_id,
                rec.owner_user_id,
                rec.owner_username,
                rec.name,
                rec.source,
                rec.value_type,
                rec.direction,
                rec.file_path,
                rec.n_dates,
                rec.n_assets,
                rec.date_start,
                rec.date_end,
                rec.coverage_ratio,
                rec.content_hash,
                rec.created_at or _now(),
            ),
        )
        conn.commit()


def create_factor_version(rec: FactorVersionRecord) -> None:
    init_db()
    with _conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO factor_versions (
                version_id, factor_id, owner_user_id, owner_username, name, source, value_type, direction, file_path,
                n_dates, n_assets, date_start, date_end, coverage_ratio,
                content_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec.version_id,
                rec.factor_id,
                rec.owner_user_id,
                rec.owner_username,
                rec.name,
                rec.source,
                rec.value_type,
                rec.direction,
                rec.file_path,
                rec.n_dates,
                rec.n_assets,
                rec.date_start,
                rec.date_end,
                rec.coverage_ratio,
                rec.content_hash,
                rec.created_at,
            ),
        )
        conn.commit()


def get_factor_version(version_id: str) -> FactorVersionRecord | None:
    init_db()
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM factor_versions WHERE version_id = ?", (version_id,)
        ).fetchone()
    return None if row is None else FactorVersionRecord(**dict(row))


def list_factor_versions(
    factor_id: str,
    *,
    owner_user_id: int | None = None,
) -> list[FactorVersionRecord]:
    init_db()
    with _conn() as conn:
        if owner_user_id is None:
            rows = conn.execute(
                "SELECT * FROM factor_versions WHERE factor_id = ? ORDER BY created_at DESC",
                (factor_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM factor_versions WHERE factor_id = ? AND owner_user_id = ? "
                "ORDER BY created_at DESC",
                (factor_id, owner_user_id),
            ).fetchall()
    return [FactorVersionRecord(**dict(row)) for row in rows]


def get_imported_factor(factor_id: str) -> ImportedFactorRecord | None:
    init_db()
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM imported_factors WHERE factor_id = ?", (factor_id,)
        ).fetchone()
    return None if row is None else ImportedFactorRecord(**dict(row))


def list_imported_factors(*, owner_user_id: int | None = None) -> list[ImportedFactorRecord]:
    init_db()
    with _conn() as conn:
        if owner_user_id is None:
            rows = conn.execute(
                "SELECT * FROM imported_factors ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM imported_factors WHERE owner_user_id = ? ORDER BY created_at DESC",
                (owner_user_id,),
            ).fetchall()
    return [ImportedFactorRecord(**dict(r)) for r in rows]


def delete_imported_factor(factor_id: str) -> bool:
    init_db()
    with _conn() as conn:
        cur = conn.execute("DELETE FROM imported_factors WHERE factor_id = ?", (factor_id,))
        conn.commit()
    return cur.rowcount > 0
