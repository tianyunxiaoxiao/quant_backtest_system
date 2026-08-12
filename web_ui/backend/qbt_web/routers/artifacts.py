"""Artifact serving and chart-data endpoints."""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from qbt_web import db
from qbt_web.config import settings
from qbt_web.models import ArtifactList, ChartData
from qbt_web.services import chartdata

router = APIRouter(prefix="/api/runs")


def _artifact_dir(run_id: str) -> Path:
    record = db.get_run(run_id)
    if record is None or record.artifact_dir is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return Path(record.artifact_dir)


@router.get("/{run_id}/artifacts", response_model=ArtifactList)
async def list_artifacts(run_id: str):
    root = _artifact_dir(run_id)
    if not root.exists():
        return {"artifacts": []}
    items: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root)
            mime, _ = mimetypes.guess_type(str(path))
            items.append(
                {
                    "name": str(rel),
                    "path": str(rel),
                    "size": path.stat().st_size,
                    "mime_type": mime or "application/octet-stream",
                }
            )
    return {"artifacts": items}


@router.get("/{run_id}/artifacts/{path:path}")
async def get_artifact(run_id: str, path: str):
    root = _artifact_dir(run_id)
    target = (root / path).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    mime, _ = mimetypes.guess_type(str(target))
    return FileResponse(target, media_type=mime or "application/octet-stream")


@router.get("/{run_id}/chart-data/{chart}", response_model=ChartData)
async def get_chart_data(run_id: str, chart: str):
    root = _artifact_dir(run_id)
    builder = chartdata.CHART_BUILDERS.get(chart)
    if builder is None:
        raise HTTPException(status_code=404, detail="Unknown chart")
    try:
        data = builder(root)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chart data error: {exc}") from exc
    return {"chart": chart, "data": data}


@router.get("/{run_id}/report.md")
async def get_report_markdown(run_id: str):
    root = _artifact_dir(run_id)
    target = root / "backtest_report.md"
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Report not ready")
    return FileResponse(target, media_type="text/markdown")
