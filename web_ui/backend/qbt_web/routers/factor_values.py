"""Imported factor values management endpoints (2026-08-18)."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile

from qbt_web import db, engine
from qbt_web.auth import owns, principal_from_request
from qbt_web.config import settings
from qbt_web.models import FactorInfo

router = APIRouter(prefix="/api/factor-values")

# 保存目录: <web>/data/factor_values/<factor_id>/<content_hash>.parquet
_FACTOR_VALUES_DIR = settings.output_root.parent / "factor_values"

_ID_SANITIZE = re.compile(r"[^0-9A-Za-z_.\-]")


def _sanitize_factor_id(raw: str) -> str:
    cleaned = _ID_SANITIZE.sub("_", raw.strip())
    return cleaned.strip("._") or "imported_factor"


@router.get("", response_model=list[FactorInfo])
async def list_factor_values(request: Request):
    principal = principal_from_request(request)
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
            factor_version_id=(versions[0].version_id if versions else None),
            content_hash=rec.content_hash,
            value_type=rec.value_type,
        )
        for rec in db.list_imported_factors(
            owner_user_id=None if principal.is_admin else principal.user_id
        )
        if (
            versions := db.list_factor_versions(
                rec.factor_id,
                owner_user_id=None if principal.is_admin else principal.user_id,
            )
        )
    ]


@router.post("", response_model=FactorInfo, status_code=201)
async def upload_factor_values(
    request: Request,
    file: UploadFile,
    name: str = Form(...),
    direction: int = Form(1),
    source: str = Form(""),
    factor_id: str | None = Form(None),
    value_type: str = Form("factor_scores"),
):
    principal = principal_from_request(request)
    if not isinstance(value_type, str):
        value_type = "factor_scores"
    if value_type not in {"factor_scores", "target_weights"}:
        raise HTTPException(
            status_code=400, detail="value_type 必须是 factor_scores/target_weights"
        )
    if direction not in (1, -1):
        raise HTTPException(status_code=400, detail="direction 必须是 +1 或 -1")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".parquet":
        raise HTTPException(status_code=400, detail="只支持 .parquet 因子值文件")

    _FACTOR_VALUES_DIR.mkdir(parents=True, exist_ok=True)
    requested_id = _sanitize_factor_id(factor_id or Path(file.filename or "imported.parquet").stem)
    fid = requested_id if principal.user_id == 0 else f"u{principal.user_id}_{requested_id}"
    resolved_direction = 1 if value_type == "target_weights" else direction

    # 先写临时文件, 体检通过后再落最终名, 避免半成品被注册。
    tmp_path = _FACTOR_VALUES_DIR / f".upload_{fid}.parquet"
    try:
        tmp_path.write_bytes(await file.read())
        factor = (
            engine.load_target_weights(tmp_path, portfolio_id=fid, description=name)
            if value_type == "target_weights"
            else engine.load_factor_values(
                tmp_path, factor_id=fid, direction=resolved_direction, description=name
            )
        )
        # 重新导出规范化后的宽表 (排序/类型/Inf→NaN); 体检与哈希基于规范化结果。
        stats = engine.inspect_factor_values(factor.values)
        coverage_ratio = (
            round(float(factor.values.gt(0.0).to_numpy().mean()), 6)
            if value_type == "target_weights"
            else stats.coverage_ratio
        )
        factor.values.to_parquet(tmp_path)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"因子值校验失败: {exc}") from exc

    digest = factor.content_hash.removeprefix("sha256:")
    version_id = f"{fid}@{digest[:16]}"
    final_dir = _FACTOR_VALUES_DIR / fid
    final_dir.mkdir(parents=True, exist_ok=True)
    final_path = final_dir / f"{digest}.parquet"
    if final_path.exists():
        tmp_path.unlink(missing_ok=True)
    else:
        tmp_path.replace(final_path)

    created_at = db.utc_now()
    db.create_factor_version(
        db.FactorVersionRecord(
            version_id=version_id,
            factor_id=fid,
            name=name,
            source=source or None,
            value_type=value_type,
            direction=resolved_direction,
            file_path=str(final_path),
            n_dates=stats.n_dates,
            n_assets=stats.n_assets,
            date_start=str(stats.date_start.date()) if stats.date_start is not None else None,
            date_end=str(stats.date_end.date()) if stats.date_end is not None else None,
            coverage_ratio=coverage_ratio,
            content_hash=factor.content_hash,
            created_at=created_at,
            owner_user_id=principal.user_id,
            owner_username=principal.username,
        )
    )

    rec = db.ImportedFactorRecord(
        factor_id=fid,
        name=name,
        source=source or None,
        value_type=value_type,
        direction=resolved_direction,
        file_path=str(final_path),
        n_dates=stats.n_dates,
        n_assets=stats.n_assets,
        date_start=str(stats.date_start.date()) if stats.date_start is not None else None,
        date_end=str(stats.date_end.date()) if stats.date_end is not None else None,
        coverage_ratio=coverage_ratio,
        content_hash=factor.content_hash,
        created_at=created_at,
        owner_user_id=principal.user_id,
        owner_username=principal.username,
    )
    db.create_imported_factor(rec)
    return FactorInfo(
        factor_id=fid,
        direction=resolved_direction,
        description=f"外部导入因子值: {name}",
        warmup_days=0,
        inputs=[],
        kind="values",
        name=name,
        n_dates=stats.n_dates,
        n_assets=stats.n_assets,
        date_start=rec.date_start,
        date_end=rec.date_end,
        coverage_ratio=coverage_ratio,
        source=rec.source,
        factor_version_id=version_id,
        content_hash=factor.content_hash,
        value_type=value_type,
    )


@router.get("/{factor_id}/versions", response_model=list[FactorInfo])
async def list_factor_versions(factor_id: str, request: Request):
    principal = principal_from_request(request)
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
            factor_version_id=rec.version_id,
            content_hash=rec.content_hash,
            value_type=rec.value_type,
        )
        for rec in db.list_factor_versions(
            factor_id,
            owner_user_id=None if principal.is_admin else principal.user_id,
        )
    ]


@router.delete("/{factor_id}")
async def delete_factor_values(factor_id: str, request: Request):
    rec = db.get_imported_factor(factor_id)
    if rec is None or not owns(principal_from_request(request), rec.owner_user_id):
        raise HTTPException(status_code=404, detail="导入因子不存在")
    db.delete_imported_factor(factor_id)
    Path(rec.file_path).unlink(missing_ok=True)
    return {"ok": True}
