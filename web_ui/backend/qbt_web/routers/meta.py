"""Metadata endpoints: factors, indexes, config."""
from __future__ import annotations

from fastapi import APIRouter

from qbt_web import db
from qbt_web.config import settings
from qbt_web.engine import get_demo_factors, get_indexes
from qbt_web.models import FactorInfo, IndexInfo

router = APIRouter(prefix="/api")


@router.get("/factors", response_model=list[FactorInfo])
async def list_factors():
    """内置公式因子 + 外部导入因子值, 统一供新建回测选择。"""
    factors = [FactorInfo(**info) for info in get_demo_factors().values()]
    imported = [
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
    return imported + factors


@router.get("/indexes", response_model=list[IndexInfo])
async def list_indexes():
    return [IndexInfo(**info) for info in get_indexes()]


@router.get("/config")
async def app_config():
    return {
        "app_name": settings.app_name,
        "default_index": "ALL_A_EQ",
        "default_start": "2018-01-01",
        "default_end": "2026-03-31",
        "default_capital": 100_000_000,
    }
