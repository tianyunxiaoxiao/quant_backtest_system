"""Imported factor values management endpoints (2026-08-18)."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile

from qbt_web import db, engine
from qbt_web.config import settings
from qbt_web.models import FactorInfo

router = APIRouter(prefix="/api/factor-values")

# 保存目录: <web>/data/factor_values/<factor_id>.parquet
_FACTOR_VALUES_DIR = settings.output_root.parent / "factor_values"

_ID_SANITIZE = re.compile(r"[^0-9A-Za-z_.\-]")


def _sanitize_factor_id(raw: str) -> str:
    cleaned = _ID_SANITIZE.sub("_", raw.strip())
    return cleaned.strip("._") or "imported_factor"


@router.get("", response_model=list[FactorInfo])
async def list_factor_values():
    return [
        FactorInfo(
            factor_id=rec.factor_id,
            direction=rec.direction,
            description=f"外部导入因子值: {rec.name}",
            warmup_days=0,
            inputs=[],
            kind="values",
            name=rec.name,
            n_dates=rec.n_dates,
            n_assets=rec.n_assets,
            date_start=rec.date_start,
            date_end=rec.date_end,
            coverage_ratio=rec.coverage_ratio,
            source=rec.source,
        )
        for rec in db.list_imported_factors()
    ]


@router.post("", response_model=FactorInfo, status_code=201)
async def upload_factor_values(
    file: UploadFile,
    name: str = Form(...),
    direction: int = Form(1),
    source: str = Form(""),
    factor_id: str | None = Form(None),
):
    if direction not in (1, -1):
        raise HTTPException(status_code=400, detail="direction 必须是 +1 或 -1")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".parquet":
        raise HTTPException(status_code=400, detail="只支持 .parquet 因子值文件")

    _FACTOR_VALUES_DIR.mkdir(parents=True, exist_ok=True)
    fid = _sanitize_factor_id(factor_id or Path(file.filename or "imported.parquet").stem)

    # 先写临时文件, 体检通过后再落最终名, 避免半成品被注册。
    tmp_path = _FACTOR_VALUES_DIR / f".upload_{fid}.parquet"
    final_path = _FACTOR_VALUES_DIR / f"{fid}.parquet"
    try:
        tmp_path.write_bytes(await file.read())
        factor = engine.load_factor_values(
            tmp_path, factor_id=fid, direction=direction, description=name
        )
        # 重新导出规范化后的宽表 (排序/类型/Inf→NaN); 体检与哈希基于规范化结果。
        stats = engine.inspect_factor_values(factor.values)
        factor.values.to_parquet(tmp_path)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"因子值校验失败: {exc}") from exc

    tmp_path.replace(final_path)

    rec = db.ImportedFactorRecord(
        factor_id=fid,
        name=name,
        source=source or None,
        direction=direction,
        file_path=str(final_path),
        n_dates=stats.n_dates,
        n_assets=stats.n_assets,
        date_start=str(stats.date_start.date()) if stats.date_start is not None else None,
        date_end=str(stats.date_end.date()) if stats.date_end is not None else None,
        coverage_ratio=stats.coverage_ratio,
        content_hash=factor.content_hash,
        created_at=None,
    )
    db.create_imported_factor(rec)
    return FactorInfo(
        factor_id=fid,
        direction=direction,
        description=f"外部导入因子值: {name}",
        warmup_days=0,
        inputs=[],
        kind="values",
        name=name,
        n_dates=stats.n_dates,
        n_assets=stats.n_assets,
        date_start=rec.date_start,
        date_end=rec.date_end,
        coverage_ratio=stats.coverage_ratio,
        source=rec.source,
    )


@router.delete("/{factor_id}")
async def delete_factor_values(factor_id: str):
    rec = db.get_imported_factor(factor_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="导入因子不存在")
    db.delete_imported_factor(factor_id)
    Path(rec.file_path).unlink(missing_ok=True)
    return {"ok": True}
