"""Backtest runner service."""
from __future__ import annotations

import json
import threading
import traceback
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from qbt_web import db
from qbt_web.config import settings
from qbt_web.engine import run_backtest

_run_lock = threading.Lock()


def _new_run_id() -> str:
    return f"web_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"


def submit_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Create run record and return its id. The caller must schedule execution."""
    run_id = _new_run_id()
    artifact_dir = settings.output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "factor_id": payload["factor_id"],
        "index_id": payload["index_id"],
        "start_date": payload["start_date"].isoformat(),
        "end_date": payload["end_date"].isoformat(),
        "rebalance_frequency": payload["rebalance_frequency"],
        "initial_capital": payload["initial_capital"],
        "selection_fraction": payload["selection_fraction"],
        "weighting_method": payload["weighting_method"],
        "max_single_weight": payload["max_single_weight"],
        "slippage_bps": payload["slippage_bps"],
        "commission_rate": payload["commission_rate"],
        "stamp_duty_rate": payload.get("stamp_duty_rate"),
        "transfer_fee_rate": payload.get("transfer_fee_rate"),
        "fill_price_field": payload["fill_price_field"],
        "lookback": payload.get("lookback"),
        "factor_source": payload.get("factor_source", "demo"),
        "factor_direction": payload.get("factor_direction"),
        "business_summary": {
            "selection_fraction": payload["selection_fraction"],
            "weighting_method": payload["weighting_method"],
            "rebalance_frequency": payload["rebalance_frequency"],
            "signal_lag_days": 1,
            "fill_price_field": payload["fill_price_field"],
            "initial_capital": payload["initial_capital"],
            "max_single_weight": payload["max_single_weight"],
        },
    }

    # 外部因子值回测: 解析导入登记, 把文件路径与方向冻结进 run 配置,
    # 保证 run 记录可复现 (文件后续被删除时 run 会显式失败, 不静默换因子)。
    if config["factor_source"] == "values":
        record = db.get_imported_factor(config["factor_id"])
        if record is None:
            raise ValueError(f"导入因子不存在: {config['factor_id']}")
        if not Path(record.file_path).is_file():
            raise ValueError(f"导入因子文件缺失: {record.file_path}")
        config["factor_values_path"] = record.file_path
        config["factor_values_name"] = record.name
        config["factor_values_source"] = record.source
        if config["factor_direction"] is None:
            config["factor_direction"] = record.direction

    db.create_run(run_id, payload["factor_id"], payload["index_id"], config, artifact_dir)
    return {"run_id": run_id, "status": "pending"}


def execute_run(run_id: str) -> None:
    """Actually run qbt. This function is serialized by a lock to avoid
    matplotlib global-state conflicts.
    """
    record = db.get_run(run_id)
    if record is None:
        return

    artifact_dir = Path(record.artifact_dir)
    config = json.loads(record.config_json or "{}")

    # Convert date strings back to date objects.
    params = dict(config)
    for key in ("start_date", "end_date"):
        if isinstance(params.get(key), str):
            params[key] = date.fromisoformat(params[key])

    db.update_status(run_id, "running")
    try:
        with _run_lock:
            summary = run_backtest(run_id, params, artifact_dir)
        db.update_status(run_id, "completed", summary=summary)
    except Exception as exc:
        db.update_status(run_id, "failed", error=f"{exc}\n{traceback.format_exc()}")
