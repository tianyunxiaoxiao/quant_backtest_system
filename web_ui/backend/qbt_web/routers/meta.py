"""Metadata endpoints: factors, indexes, config."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request

from qbt_web import db
from qbt_web.auth import principal_from_request
from qbt_web.config import settings
from qbt_web.engine import get_demo_factors, get_indexes
from qbt_web.models import FactorInfo, IndexInfo
from qbt_web.services.benchmark_comparison import list_benchmarks
from qbt_web.services.factor_platform import FactorPlatformClient, FactorPlatformError

router = APIRouter(prefix="/api")


@router.get("/factors", response_model=list[FactorInfo])
async def list_factors(request: Request):
    """内置公式因子 + 外部导入因子值, 统一供新建回测选择。"""
    factors = [FactorInfo(**info) for info in get_demo_factors().values()]
    principal = principal_from_request(request)
    owner_filter = None if principal.is_admin else principal.user_id
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
            factor_version_id=(
                versions[0].version_id
                if (
                    versions := db.list_factor_versions(
                        rec.factor_id,
                        owner_user_id=owner_filter,
                    )
                )
                else None
            ),
            content_hash=rec.content_hash,
            value_type=rec.value_type,
        )
        for rec in db.list_imported_factors(owner_user_id=owner_filter)
    ]
    platform = []
    if FactorPlatformClient.configured():
        try:
            rows = await asyncio.to_thread(
                FactorPlatformClient().list_visible,
                request.headers.get("cookie", ""),
            )
            platform = [
                FactorInfo(
                    factor_id=str(row["factor_id"]),
                    direction=int(row.get("direction", 1)),
                    description=f"因子研究平台: {row.get('name') or row['factor_id']}",
                    warmup_days=0,
                    inputs=[],
                    kind="platform",
                    name=str(row.get("name") or row["factor_id"]),
                    date_start=row.get("date_start"),
                    date_end=row.get("date_end"),
                    coverage_ratio=row.get("coverage_latest"),
                    source="factor-platform",
                    factor_version_id=str(
                        row.get("factor_version_id") or row.get("source_run_id") or ""
                    ),
                    content_hash=row.get("factor_values_hash"),
                    value_type=str(row.get("value_type") or "factor_scores"),
                )
                for row in rows
                if row.get("factor_id")
                and (row.get("factor_version_id") or row.get("source_run_id"))
            ]
        except FactorPlatformError:
            platform = []
    return platform + imported + factors


@router.get("/indexes", response_model=list[IndexInfo])
async def list_indexes():
    return [IndexInfo(**info) for info in get_indexes()]


@router.get("/benchmarks")
async def benchmark_options():
    """Report benchmarks are independent from the backtest selection universe."""
    return list_benchmarks(settings.warehouse_dir)


@router.get("/config")
async def app_config():
    manifest_path = settings.warehouse_dir / "rqdata_warehouse_manifest.json"
    default_end = "2026-03-31"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        default_end = str(manifest.get("date_max") or default_end)
    return {
        "app_name": settings.app_name,
        "default_index": "ALL_A_EQ",
        "default_start": "2019-01-01",
        "default_end": default_end,
        "default_capital": 100_000_000,
    }
