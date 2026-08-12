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
    fill_price_field: Literal["adj_vwap", "adj_open", "adj_close"] = "adj_vwap"
    lookback: int | None = None


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
