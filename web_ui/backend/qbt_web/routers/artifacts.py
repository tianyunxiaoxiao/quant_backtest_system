"""Artifact serving and chart-data endpoints."""
from __future__ import annotations

import io
import mimetypes
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

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


# ---------------------------------------------------------------------------
# 历史持仓 (2026-08-18): 最新两期调仓明细 + 全部成交历史下载
# ---------------------------------------------------------------------------

_POSITION_COLUMNS = [
    "fill_date", "asset_id", "side", "filled_quantity", "fill_price",
    "filled_amount", "commission", "stamp_duty", "transfer_fee",
    "explicit_cost", "total_cost", "status",
]


def _load_fills(root: Path) -> pd.DataFrame:
    path = root / "fills.parquet"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fills not found")
    return pd.read_parquet(path)


def _fill_record(row: pd.Series) -> dict[str, Any]:
    return {
        "fill_date": str(row["fill_date"]),
        "asset_id": str(row["asset_id"]),
        "side": str(row["side"]),
        "filled_quantity": float(row["filled_quantity"]),
        "fill_price": float(row["fill_price"]),
        "filled_amount": float(row["filled_amount"]),
        "commission": float(row["commission"]),
        "stamp_duty": float(row["stamp_duty"]),
        "transfer_fee": float(row["transfer_fee"]),
        "explicit_cost": float(row["explicit_cost"]),
        "total_cost": float(row["total_cost"]),
        "status": str(row["status"]),
    }


@router.get("/{run_id}/positions/latest")
async def latest_positions(run_id: str, periods: int = 2):
    """最新 N 期 (默认 2 期) 调仓成交明细, 按期分组返回。"""
    root = _artifact_dir(run_id)
    fills = _load_fills(root)
    executed = fills[fills["filled_quantity"] > 0].copy()
    if executed.empty:
        return {"periods": []}
    periods = max(1, min(int(periods), 24))
    # 唯一成交日按时间倒序取最新 N 期, 期内按标的升序。
    latest_dates = sorted(executed["fill_date"].unique(), reverse=True)[:periods]
    out_periods = []
    for d in latest_dates:
        day = executed[executed["fill_date"] == d].sort_values("asset_id")
        records = [_fill_record(row) for _, row in day.iterrows()]
        n_buy = int((day["side"] == "buy").sum())
        n_sell = int((day["side"] == "sell").sum())
        out_periods.append(
            {
                "date": str(pd.Timestamp(d).date()),
                "n_records": len(records),
                "n_buy": n_buy,
                "n_sell": n_sell,
                "buy_amount": float(day.loc[day["side"] == "buy", "filled_amount"].sum()),
                "sell_amount": float(day.loc[day["side"] == "sell", "filled_amount"].sum()),
                "explicit_cost": float(day["explicit_cost"].sum()),
                "records": records,
            }
        )
    return {"periods": out_periods}


@router.get("/{run_id}/positions/export")
async def export_positions(run_id: str):
    """全部历史成交记录导出为 CSV (utf-8-sig, Excel 可直接打开中文)。"""
    root = _artifact_dir(run_id)
    fills = _load_fills(root)
    columns = [c for c in _POSITION_COLUMNS if c in fills.columns]
    df = fills[columns].sort_values(["fill_date", "asset_id"])
    buf = io.StringIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{run_id}_all_fills.csv"'},
    )
