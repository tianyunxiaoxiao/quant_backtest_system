"""User-owned folders for organizing backtest runs."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from qbt_web import db
from qbt_web.auth import principal_from_request
from qbt_web.config import settings
from qbt_web.models import (
    RunGroupCreate,
    RunGroupList,
    RunGroupOut,
    RunGroupStatistics,
    RunGroupUpdate,
)
from qbt_web.services.benchmark_comparison import (
    DEFAULT_REPORT_BENCHMARK_ID,
    compare_run,
)

router = APIRouter(prefix="/api/run-groups")

_STATISTIC_KEYS = (
    "total_return",
    "annual_return",
    "annual_volatility",
    "sharpe",
    "max_drawdown",
    "benchmark_total_return",
    "excess_total_return_geometric",
    "excess_annual_return_geometric",
    "excess_sharpe",
    "excess_max_drawdown",
    "excess_volatility",
    "information_ratio",
    "beta",
)
_PORTFOLIO_KEYS = {
    "total_return",
    "annual_return",
    "annual_volatility",
    "sharpe",
    "max_drawdown",
}


def _clean_name(value: str) -> str:
    name = " ".join(value.split())
    if not name:
        raise HTTPException(status_code=400, detail="分组名称不能为空")
    return name


def _require_editable(group) -> None:
    if group.name == db.DEFAULT_RUN_GROUP_NAME:
        raise HTTPException(status_code=400, detail="默认分组不能重命名或删除")


def _require_admin(request: Request):
    principal = principal_from_request(request)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="只有管理员可以管理全局分组")
    return principal


@router.get("", response_model=RunGroupList)
async def list_groups(request: Request):
    principal_from_request(request)
    return {"groups": db.list_run_groups()}


def _parse_group_ids(value: str | None) -> set[int] | None:
    if value is None or not value.strip():
        return None
    try:
        ids = {int(item) for item in value.split(",") if item.strip()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="分组参数无效") from exc
    if not ids or any(group_id <= 0 for group_id in ids):
        raise HTTPException(status_code=400, detail="分组参数无效")
    return ids


def _statistics_rows(records, benchmark_id: str) -> list[dict]:
    rows = []
    for record in records:
        config = json.loads(record.config_json) if record.config_json else {}
        original = json.loads(record.summary_json) if record.summary_json else {}
        metrics = {key: None for key in _STATISTIC_KEYS}
        for key in _PORTFOLIO_KEYS:
            value = original.get(key)
            metrics[key] = float(value) if value is not None else None
        error = None
        try:
            comparison = compare_run(
                Path(record.artifact_dir or ""),
                benchmark_id,
                settings.warehouse_dir,
            )
            summary = comparison["summary"]
            metrics = {
                key: float(summary[key]) if summary.get(key) is not None else None
                for key in _STATISTIC_KEYS
            }
        except Exception:
            # One damaged legacy artifact must not prevent the rest of the group loading.
            error = "该回测无法按所选基准计算完整统计"
        rows.append(
            {
                "id": record.id,
                "display_name": (
                    record.display_name
                    or config.get("factor_values_name")
                    or config.get("factor_name")
                    or record.factor_id
                ),
                "rebalance_frequency": record.rebalance_frequency,
                "start_date": record.start_date,
                "end_date": record.end_date,
                "metrics": metrics,
                "error": error,
            }
        )
    return rows


@router.get("/statistics", response_model=RunGroupStatistics)
async def group_statistics(
    request: Request,
    benchmark_id: str = DEFAULT_REPORT_BENCHMARK_ID,
    group_ids: str | None = None,
):
    principal = principal_from_request(request)
    selected_group_ids = _parse_group_ids(group_ids)
    if selected_group_ids is not None:
        known_ids = {group.id for group in db.list_run_groups()}
        if not selected_group_ids.issubset(known_ids):
            raise HTTPException(status_code=404, detail="分组不存在")
    records = [
        record
        for record in db.list_runs(
            limit=10_000,
            owner_user_id=None if principal.is_admin else principal.user_id,
        )
        if record.status == "completed"
        and (selected_group_ids is None or record.group_id in selected_group_ids)
    ]
    rows = await asyncio.to_thread(_statistics_rows, records, benchmark_id)
    return {"benchmark_id": benchmark_id, "rows": rows}


@router.post("", response_model=RunGroupOut, status_code=201)
async def create_group(payload: RunGroupCreate, request: Request):
    principal = _require_admin(request)
    try:
        return db.create_run_group(
            _clean_name(payload.name),
            owner_user_id=principal.user_id,
            owner_username=principal.username,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="已存在同名分组") from exc


@router.patch("/{group_id}", response_model=RunGroupOut)
async def update_group(group_id: int, payload: RunGroupUpdate, request: Request):
    _require_admin(request)
    group = db.get_run_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="分组不存在")
    _require_editable(group)
    try:
        db.rename_run_group(group_id, _clean_name(payload.name))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="已存在同名分组") from exc
    return db.get_run_group(group_id)


@router.delete("/{group_id}")
async def delete_group(group_id: int, request: Request):
    _require_admin(request)
    group = db.get_run_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="分组不存在")
    _require_editable(group)
    db.delete_run_group(group_id)
    return {"ok": True}
