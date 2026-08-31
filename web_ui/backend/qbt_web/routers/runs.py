"""Run management endpoints."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from qbt_web import db
from qbt_web.auth import owns, principal_from_request
from qbt_web.models import RunConfig, RunDetail, RunList
from qbt_web.services.runner import cancel_run, execute_run, submit_run

router = APIRouter(prefix="/api/runs")


def _record_to_out(record: db.RunRecord, *, include_config: bool = False) -> dict[str, Any]:
    def parse(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    created = parse(record.created_at)
    started = parse(record.started_at)
    ended = parse(record.completed_at)
    clock_end = ended or datetime.now(timezone.utc)
    elapsed = max(0.0, (clock_end - started).total_seconds()) if started else 0.0
    queue_seconds = max(0.0, (started - created).total_seconds()) if started and created else None
    config = json.loads(record.config_json) if record.config_json else {}
    out: dict[str, Any] = {
        "id": record.id,
        "owner_user_id": record.owner_user_id,
        "owner_username": record.owner_username,
        "status": record.status,
        "factor_id": record.factor_id,
        "factor_name": config.get("factor_values_name") or config.get("factor_name"),
        "index_id": record.index_id,
        "start_date": record.start_date,
        "end_date": record.end_date,
        "rebalance_frequency": record.rebalance_frequency,
        "initial_capital": record.initial_capital,
        "selection_fraction": record.selection_fraction,
        "weighting_method": record.weighting_method,
        "max_single_weight": record.max_single_weight,
        "fill_price_field": record.fill_price_field,
        "summary": json.loads(record.summary_json) if record.summary_json else None,
        "error": record.error,
        "created_at": record.created_at,
        "started_at": record.started_at,
        "cancelled_at": record.cancelled_at,
        "completed_at": record.completed_at,
        "elapsed_seconds": elapsed,
        "queue_seconds": queue_seconds,
    }
    if include_config:
        out["config"] = config or None
        out["artifact_dir"] = record.artifact_dir
    return out


@router.post("", response_model=RunDetail, status_code=202)
async def create_run(payload: RunConfig, background_tasks: BackgroundTasks, request: Request):
    data = payload.model_dump()
    principal = principal_from_request(request)
    try:
        info = submit_run(
            data,
            factor_platform_cookie=request.headers.get("cookie", ""),
            owner_user_id=principal.user_id,
            owner_username=principal.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(execute_run, info["run_id"])
    record = db.get_run(info["run_id"])
    if record is None:
        raise HTTPException(status_code=500, detail="Failed to create run record")
    return _record_to_out(record, include_config=True)


@router.get("", response_model=RunList)
async def list_runs(request: Request, limit: int = 200):
    principal = principal_from_request(request)
    records = db.list_runs(
        limit=limit,
        owner_user_id=None if principal.is_admin else principal.user_id,
    )
    return {"runs": [_record_to_out(r) for r in records]}


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: str, request: Request):
    record = db.get_run(run_id)
    if record is None or not owns(principal_from_request(request), record.owner_user_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return _record_to_out(record, include_config=True)


@router.get("/{run_id}/progress")
async def run_progress(run_id: str, request: Request):
    record = db.get_run(run_id)
    if record is None or not owns(principal_from_request(request), record.owner_user_id):
        raise HTTPException(status_code=404, detail="Run not found")
    detail = _record_to_out(record)
    return {
        "run_id": run_id,
        "status": record.status,
        "error": record.error,
        "started_at": record.started_at,
        "elapsed_seconds": detail["elapsed_seconds"],
        "queue_seconds": detail["queue_seconds"],
    }


@router.post("/{run_id}/cancel")
async def cancel(run_id: str, request: Request):
    existing = db.get_run(run_id)
    if existing is None or not owns(principal_from_request(request), existing.owner_user_id):
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        status = await asyncio.to_thread(cancel_run, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if status not in ("cancelled", "pending", "running"):
        raise HTTPException(status_code=409, detail=f"Run is already {status}")
    record = db.get_run(run_id)
    return _record_to_out(record, include_config=True)


@router.delete("/{run_id}")
async def delete_run(run_id: str, request: Request):
    record = db.get_run(run_id)
    if record is None or not owns(principal_from_request(request), record.owner_user_id):
        raise HTTPException(status_code=404, detail="Run not found")
    if record.status in ("running", "pending"):
        raise HTTPException(status_code=400, detail="Cannot delete a running/pending run")
    db.delete_run(run_id)
    if record.artifact_dir:
        import shutil

        shutil.rmtree(Path(record.artifact_dir), ignore_errors=True)
    return {"ok": True}
