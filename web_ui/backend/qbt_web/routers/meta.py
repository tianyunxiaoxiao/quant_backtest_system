"""Metadata endpoints: factors, indexes, config."""
from __future__ import annotations

from fastapi import APIRouter

from qbt_web.config import settings
from qbt_web.engine import get_demo_factors, get_indexes
from qbt_web.models import FactorInfo, IndexInfo

router = APIRouter(prefix="/api")


@router.get("/factors", response_model=list[FactorInfo])
async def list_factors():
    return [FactorInfo(**info) for info in get_demo_factors().values()]


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
