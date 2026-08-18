"""Run management endpoints."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from qbt_web import db
from qbt_web.config import settings
from qbt_web.models import RunConfig, RunDetail, RunList, RunOut
from qbt_web.services.runner import execute_run, submit_run

router = APIRouter(prefix="/api/runs")


def _record_to_out(record: db.RunRecord, *, include_config: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": record.id,
        "status": record.status,
        "factor_id": record.factor_id,
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
        "completed_at": record.completed_at,
    }
    if include_config:
        out["config"] = json.loads(record.config_json) if record.config_json else None
        out["artifact_dir"] = record.artifact_dir
    return out


@router.post("", response_model=RunDetail, status_code=202)
async def create_run(payload: RunConfig, background_tasks: BackgroundTasks):
    data = payload.model_dump()
    try:
        info = submit_run(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(execute_run, info["run_id"])
    record = db.get_run(info["run_id"])
    if record is None:
        raise HTTPException(status_code=500, detail="Failed to create run record")
    return _record_to_out(record, include_config=True)


@router.get("", response_model=RunList)
async def list_runs(limit: int = 200):
    records = db.list_runs(limit=limit)
    return {"runs": [_record_to_out(r) for r in records]}


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: str):
    record = db.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _record_to_out(record, include_config=True)


@router.get("/{run_id}/progress")
async def run_progress(run_id: str):
    record = db.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run_id, "status": record.status, "error": record.error}


@router.delete("/{run_id}")
async def delete_run(run_id: str):
    record = db.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if record.status in ("running", "pending"):
        raise HTTPException(status_code=400, detail="Cannot delete a running/pending run")
    db.delete_run(run_id)
    if record.artifact_dir:
        import shutil
        shutil.rmtree(Path(record.artifact_dir), ignore_errors=True)
    return {"ok": True}
