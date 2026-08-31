"""Backtest runner service."""

from __future__ import annotations

import io
import json
import multiprocessing
import threading
import traceback
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from qbt.factors.values import inspect_factor_values, load_factor_values, load_target_weights
from qbt_web import db
from qbt_web.config import settings
from qbt_web.engine import get_indexes, run_backtest
from qbt_web.services.factor_platform import FactorPlatformClient

_run_slots = threading.BoundedSemaphore(max(1, settings.qbt_max_concurrent_runs))
_process_lock = threading.Lock()
_processes: dict[str, multiprocessing.Process] = {}


def _new_run_id() -> str:
    return f"web_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"


def submit_run(
    payload: dict[str, Any],
    *,
    factor_platform_cookie: str = "",
    owner_user_id: int | None = None,
    owner_username: str | None = None,
) -> dict[str, Any]:
    """Create run record and return its id. The caller must schedule execution."""
    supported_indexes = {item["index_id"] for item in get_indexes()}
    if payload["index_id"] not in supported_indexes:
        raise ValueError(
            f"当前米筐快照仓库不支持指数 {payload['index_id']}; "
            f"可用指数: {sorted(supported_indexes)}"
        )
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
        "min_commission": payload.get("min_commission", 5.0),
        "stamp_duty_rate": payload.get("stamp_duty_rate"),
        "transfer_fee_rate": payload.get("transfer_fee_rate"),
        "fill_price_field": payload["fill_price_field"],
        "lookback": payload.get("lookback"),
        "factor_source": payload.get("factor_source", "demo"),
        "factor_direction": payload.get("factor_direction"),
        "factor_version_id": payload.get("factor_version_id"),
        "portfolio_input_mode": payload.get("portfolio_input_mode", "factor_scores"),
        "business_summary": {
            "selection_fraction": payload["selection_fraction"],
            "weighting_method": payload["weighting_method"],
            "rebalance_frequency": payload["rebalance_frequency"],
            "signal_lag_days": 1,
            "fill_price_field": payload["fill_price_field"],
            "initial_capital": payload["initial_capital"],
            "max_single_weight": payload["max_single_weight"],
            "portfolio_input_mode": payload.get("portfolio_input_mode", "factor_scores"),
        },
    }

    if config["factor_source"] == "platform":
        platform_payload = FactorPlatformClient().fetch_visible_version(
            config["factor_id"],
            str(config.get("factor_version_id") or ""),
            factor_platform_cookie,
        )
        platform_factor = platform_payload.metadata
        raw = pd.read_parquet(io.BytesIO(platform_payload.content))
        platform_value_type = str(platform_factor.get("value_type") or "factor_scores")
        factor = (
            load_target_weights(raw, portfolio_id=config["factor_id"])
            if platform_value_type == "target_weights"
            else load_factor_values(
                raw,
                factor_id=config["factor_id"],
                direction=int(platform_factor.get("direction", 1)),
            )
        )
        stats = inspect_factor_values(factor.values)
        digest = factor.content_hash.removeprefix("sha256:")
        factor_dir = settings.output_root.parent / "factor_values" / config["factor_id"]
        factor_dir.mkdir(parents=True, exist_ok=True)
        final_path = factor_dir / f"{digest}.parquet"
        if not final_path.exists():
            factor.values.to_parquet(final_path)
        version = db.FactorVersionRecord(
            version_id=str(config["factor_version_id"]),
            factor_id=config["factor_id"],
            name=str(platform_factor.get("name") or config["factor_id"]),
            source="factor-platform",
            value_type=platform_value_type,
            direction=int(platform_factor.get("direction", 1)),
            file_path=str(final_path),
            n_dates=stats.n_dates,
            n_assets=stats.n_assets,
            date_start=str(stats.date_start.date()) if stats.date_start is not None else None,
            date_end=str(stats.date_end.date()) if stats.date_end is not None else None,
            coverage_ratio=stats.coverage_ratio,
            content_hash=factor.content_hash,
            created_at=db.utc_now(),
            owner_user_id=owner_user_id,
            owner_username=owner_username,
        )
        db.create_factor_version(version)
        config["factor_upstream_hash"] = platform_factor.get("summary", {}).get(
            "factor_values_hash"
        )

    # 外部因子值回测: 解析导入登记, 把文件路径与方向冻结进 run 配置,
    # 保证 run 记录可复现 (文件后续被删除时 run 会显式失败, 不静默换因子)。
    if config["factor_source"] in {"values", "platform"}:
        version_id = config.get("factor_version_id")
        version = db.get_factor_version(version_id) if version_id else None
        record = db.get_imported_factor(config["factor_id"])
        if version_id and version is None:
            raise ValueError(f"因子版本不存在: {version_id}")
        if version is not None and version.factor_id != config["factor_id"]:
            raise ValueError(f"因子版本与因子ID不匹配: {version_id}")
        source_record = version or record
        if source_record is None:
            raise ValueError(f"导入因子不存在: {config['factor_id']}")
        if owner_user_id is not None and source_record.owner_user_id != owner_user_id:
            raise ValueError(f"导入因子不存在: {config['factor_id']}")
        if not Path(source_record.file_path).is_file():
            raise ValueError(f"导入因子文件缺失: {source_record.file_path}")
        config["factor_version_id"] = getattr(source_record, "version_id", None)
        config["factor_content_hash"] = source_record.content_hash
        config["factor_values_path"] = source_record.file_path
        config["factor_values_name"] = source_record.name
        config["factor_values_source"] = source_record.source
        config["factor_value_type"] = source_record.value_type
        config["portfolio_input_mode"] = (
            "direct_target_weights"
            if source_record.value_type == "target_weights"
            else "factor_scores"
        )
        config["business_summary"]["portfolio_input_mode"] = config["portfolio_input_mode"]
        if config["portfolio_input_mode"] == "direct_target_weights":
            config["business_summary"].update(
                {
                    "selection_fraction": None,
                    "weighting_method": "uploaded_exact_weights",
                    "rebalance_frequency": "target_weight_rows",
                    "max_single_weight": None,
                }
            )
        if config["factor_direction"] is None:
            config["factor_direction"] = source_record.direction

    db.create_run(
        run_id,
        payload["factor_id"],
        payload["index_id"],
        config,
        artifact_dir,
        owner_user_id=owner_user_id,
        owner_username=owner_username,
    )
    return {"run_id": run_id, "status": "pending"}


def _run_worker(run_id: str, params: dict[str, Any], artifact_dir: Path) -> None:
    """Execute one run in an isolated process so it can be cancelled safely."""
    try:
        summary = run_backtest(run_id, params, artifact_dir)
        db.transition_status(run_id, "running", "completed", summary=summary)
    except Exception as exc:
        db.transition_status(
            run_id,
            "running",
            "failed",
            error=f"{exc}\n{traceback.format_exc()}",
        )


def execute_run(run_id: str) -> None:
    """Run qbt in a cancellable child process, serialized to bound resource use."""
    record = db.get_run(run_id)
    if record is None or record.status != "pending":
        return

    artifact_dir = Path(record.artifact_dir)
    config = json.loads(record.config_json or "{}")

    # Convert date strings back to date objects.
    params = dict(config)
    for key in ("start_date", "end_date"):
        if isinstance(params.get(key), str):
            params[key] = date.fromisoformat(params[key])

    with _run_slots:
        process: multiprocessing.Process | None = None
        with _process_lock:
            if not db.transition_status(run_id, "pending", "running"):
                return
            try:
                process = multiprocessing.get_context("spawn").Process(
                    target=_run_worker,
                    args=(run_id, params, artifact_dir),
                    name=f"qbt-{run_id}",
                    daemon=True,
                )
                process.start()
                _processes[run_id] = process
            except Exception as exc:
                db.transition_status(
                    run_id,
                    "running",
                    "failed",
                    error=f"无法启动回测子进程: {exc}",
                )
                return

        process.join()
        with _process_lock:
            _processes.pop(run_id, None)
        record = db.get_run(run_id)
        if record is not None and record.status == "running":
            db.transition_status(
                run_id,
                "running",
                "failed",
                error=f"回测子进程异常退出 (exit_code={process.exitcode})",
            )


def cancel_run(run_id: str) -> str:
    """Cancel a pending run or terminate its owned worker process."""
    with _process_lock:
        record = db.get_run(run_id)
        if record is None:
            raise KeyError(run_id)
        if record.status == "pending":
            if db.transition_status(run_id, "pending", "cancelled"):
                return "cancelled"
            record = db.get_run(run_id)
        if record is not None and record.status == "running":
            process = _processes.get(run_id)
            if process is None:
                raise RuntimeError("运行进程不属于当前服务实例，无法安全取消")
            if not db.transition_status(run_id, "running", "cancelled"):
                return db.get_run(run_id).status
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            return "cancelled"
        return record.status
