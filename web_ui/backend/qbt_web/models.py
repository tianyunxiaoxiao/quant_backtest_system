"""Pydantic request/response models."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class FactorInfo(BaseModel):
    factor_id: str
    direction: int
    description: str
    warmup_days: int
    inputs: list[str]
    kind: Literal["demo", "values"] = "demo"
    name: str | None = None
    n_dates: int | None = None
    n_assets: int | None = None
    date_start: str | None = None
    date_end: str | None = None
    coverage_ratio: float | None = None
    source: str | None = None


class IndexInfo(BaseModel):
    index_id: str
    name: str


class RunConfig(BaseModel):
    factor_id: str
    index_id: str = "ALL_A_EQ"
    start_date: date = date(2018, 1, 1)
    end_date: date = date(2026, 3, 31)
    rebalance_frequency: Literal["daily", "weekly", "monthly"] = "monthly"
    initial_capital: float = 100_000_000.0
    selection_fraction: float = Field(0.30, ge=0.01, le=1.0)
    weighting_method: Literal["factor_strength", "equal_weight", "index_weight"] = "factor_strength"
    max_single_weight: float = Field(0.05, ge=0.0, le=1.0)
    slippage_bps: float = Field(12.0, ge=0.0)
    commission_rate: float = Field(0.00025, ge=0.0)
    stamp_duty_rate: float | None = Field(None, ge=0.0, le=0.01)
    transfer_fee_rate: float | None = Field(None, ge=0.0, le=0.001)
    fill_price_field: Literal["adj_vwap", "adj_open", "adj_close"] = "adj_vwap"
    lookback: int | None = None
    # 因子来源: demo = 内置公式因子; values = 外部导入的已计算因子值。
    factor_source: Literal["demo", "values"] = "demo"
    # 导入因子值的回测方向 (+1 越大越好 / -1 越小越好), 缺省用导入时声明的方向。
    factor_direction: Literal[1, -1] | None = None


class RunOut(BaseModel):
    id: str
    status: str
    factor_id: str
    index_id: str
    start_date: str | None
    end_date: str | None
    rebalance_frequency: str | None
    initial_capital: float | None
    selection_fraction: float | None
    weighting_method: str | None
    max_single_weight: float | None
    fill_price_field: str | None
    summary: dict[str, Any] | None
    error: str | None
    created_at: str | None
    completed_at: str | None


class RunList(BaseModel):
    runs: list[RunOut]


class RunDetail(RunOut):
    config: dict[str, Any] | None
    artifact_dir: str | None


class ArtifactItem(BaseModel):
    name: str
    path: str
    size: int
    mime_type: str


class ArtifactList(BaseModel):
    artifacts: list[ArtifactItem]


class ChartData(BaseModel):
    chart: str
    data: dict[str, Any]
