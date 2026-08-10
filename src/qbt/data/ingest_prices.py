"""个股行情 CSV -> 规范化 Parquet 仓库 (规范 17-P0 第 2 步)。

原始数据特征 (来自数据审计, 对应确认清单 D2 / B6 / G2):
- OHLC 与前收盘价是前复权口径; 量、额、股本、市值、均价是未复权原值。
- 前收盘价恒等于前一交易日收盘价, 说明复权序列连续无跳空, 可直接算总收益。
- 文件 GB18030 编码, 中文表头, 行尾多一个空列, 缺失值是字面量 N/A。

本模块重建原始价格与每日复权因子:
    raw_close   = 总市值 / 总股本
    adj_factor  = adj_close / raw_close   (逐段常数, 做阶梯平滑去掉市值四舍五入噪声)
    raw_open    = adj_open / adj_factor
    adj_vwap    = 均价 * adj_factor
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

__all__ = ["IngestConfig", "load_single_stock", "ingest_prices"]

_COLUMN_MAP = {
    "代码": "asset_id",
    "简称": "short_name",
    "日期": "date",
    "前收盘价(元)": "adj_prev_close",
    "开盘价(元)": "adj_open",
    "最高价(元)": "adj_high",
    "最低价(元)": "adj_low",
    "收盘价(元)": "adj_close",
    "成交量(股)": "volume",
    "成交金额(元)": "amount",
    "涨跌幅(%)": "pct_change",
    "均价(元)": "raw_vwap",
    "换手率(%)": "turnover_rate",
    "A股流通市值(元)": "float_mktcap",
    "总市值(元)": "total_mktcap",
    "A股流通股本(股)": "float_shares",
    "总股本(股)": "total_shares",
    "市盈率": "pe",
    "市净率": "pb",
    "市销率": "ps",
    "市现率": "pcf",
}

# float32 最大值被数据商当作缺失哨兵 (审计发现 5 / 确认清单 G1)
_SENTINEL = 3.0e38
_AF_BREAK_THRESHOLD = 5e-4  # 复权因子阶梯识别阈值: 噪声 < 2e-4, 真实除权跳变 > 2e-2


@dataclass(frozen=True)
class IngestConfig:
    source_dir: Path
    output_dir: Path
    start_date: pd.Timestamp = pd.Timestamp("2015-06-01")
    end_date: pd.Timestamp = pd.Timestamp("2026-04-07")  # G2: 统一截断, 丢掉残缺截面
    encoding: str = "gb18030"
    max_workers: int = 8


def _step_smooth_adj_factor(af_raw: pd.Series) -> pd.Series:
    """把带四舍五入噪声的复权因子还原成逐段常数阶梯。"""
    af = af_raw.astype("float64")
    valid = af.notna() & np.isfinite(af) & (af > 0)
    if valid.sum() == 0:
        return pd.Series(1.0, index=af.index)
    v = af.where(valid)
    rel = (v / v.ffill().shift()).abs()
    breaks = (rel - 1.0).abs() > _AF_BREAK_THRESHOLD
    segment = breaks.fillna(True).cumsum()
    smoothed = v.groupby(segment).transform("median")
    return smoothed.ffill().bfill()


def load_single_stock(path: Path, cfg: IngestConfig) -> pd.DataFrame | None:
    """读取单只股票 CSV, 返回规范化长表。"""
    try:
        df = pd.read_csv(
            path, encoding=cfg.encoding, na_values=["N/A", "n/a", "", "--"],
            dtype={"代码": "string", "简称": "string"},
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"读取行情文件失败: {path}: {exc}") from exc
    df = df.rename(columns=_COLUMN_MAP)
    keep = [c for c in _COLUMN_MAP.values() if c in df.columns]
    df = df[keep]
    if "date" not in df.columns or "adj_close" not in df.columns:
        raise ValueError(f"行情文件缺少 date/adj_close 必需列: {path}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["date"].notna()]
    df["asset_id"] = df["asset_id"].astype("string").str.strip()
    asset_id = path.stem.upper()
    df["asset_id"] = df["asset_id"].fillna(asset_id)

    numeric = [c for c in df.columns if c not in ("asset_id", "short_name", "date")]
    for col in numeric:
        s = pd.to_numeric(df[col], errors="coerce")
        df[col] = s.mask(s.abs() >= _SENTINEL)

    df = df.sort_values("date").drop_duplicates(subset="date", keep="last")
    # 上市区间以全历史为准, 截断只影响输出窗口
    listed_first = df["date"].iloc[0]
    listed_last = df["date"].iloc[-1]

    raw_close = df["total_mktcap"] / df["total_shares"].replace(0, np.nan)
    fallback = df["float_mktcap"] / df["float_shares"].replace(0, np.nan)
    raw_close = raw_close.where(raw_close > 0, fallback)
    af = _step_smooth_adj_factor(df["adj_close"] / raw_close)
    af = af.clip(lower=1e-8)
    df["adj_factor"] = af
    df["raw_close"] = df["adj_close"] / af
    df["raw_open"] = df["adj_open"] / af
    if "raw_vwap" in df.columns:
        df["adj_vwap"] = df["raw_vwap"] * af
    else:
        df["raw_vwap"] = df["raw_close"]
        df["adj_vwap"] = df["adj_close"]
    # 均价缺失或无成交时回落到收盘价, 保证成交价字段永不为空
    no_trade = df["volume"].fillna(0.0) <= 0
    df["adj_vwap"] = df["adj_vwap"].where(~no_trade & df["adj_vwap"].notna(), df["adj_close"])
    df["raw_vwap"] = df["raw_vwap"].where(~no_trade & df["raw_vwap"].notna(), df["raw_close"])

    # OHLC 基本约束校验 (审计发现 6): 记录并夹紧, 不静默丢弃
    hi = df[["adj_high", "adj_open", "adj_close", "adj_low"]].max(axis=1)
    lo = df[["adj_low", "adj_open", "adj_close", "adj_high"]].min(axis=1)
    df["ohlc_violation"] = (df["adj_high"] < df["adj_low"]) | (df["adj_high"] < df["adj_open"]) | (
        df["adj_high"] < df["adj_close"]) | (df["adj_low"] > df["adj_open"]) | (
        df["adj_low"] > df["adj_close"])
    df["adj_high"] = hi
    df["adj_low"] = lo

    df["listed_first_date"] = listed_first
    df["listed_last_date"] = listed_last
    df["short_name_latest"] = df["short_name"].iloc[-1] if "short_name" in df.columns else pd.NA

    out = df[(df["date"] >= cfg.start_date) & (df["date"] <= cfg.end_date)].copy()
    if out.empty:
        return None
    out["asset_id"] = asset_id
    float_cols = [
        "adj_open", "adj_high", "adj_low", "adj_close", "adj_prev_close", "adj_vwap",
        "raw_open", "raw_close", "raw_vwap", "adj_factor", "pct_change", "turnover_rate",
        "pe", "pb", "ps", "pcf",
    ]
    for col in float_cols:
        if col in out.columns:
            out[col] = out[col].astype("float32")
    for col in ("volume", "amount", "float_mktcap", "total_mktcap", "float_shares", "total_shares"):
        if col in out.columns:
            out[col] = out[col].astype("float64")
    cols = [
        "asset_id", "date", "adj_open", "adj_high", "adj_low", "adj_close", "adj_prev_close",
        "adj_vwap", "raw_open", "raw_close", "raw_vwap", "adj_factor", "pct_change", "volume",
        "amount", "turnover_rate", "float_mktcap", "total_mktcap", "float_shares", "total_shares",
        "pe", "pb", "ps", "pcf", "ohlc_violation", "listed_first_date", "listed_last_date",
        "short_name_latest",
    ]
    return out[[c for c in cols if c in out.columns]]


def _worker(args: tuple[str, IngestConfig]) -> pd.DataFrame | None:
    path, cfg = args
    return load_single_stock(Path(path), cfg)


def _validate_ingested_data(data: pd.DataFrame) -> None:
    required = {
        "asset_id", "date", "adj_open", "adj_high", "adj_low", "adj_close",
        "adj_vwap", "raw_open", "raw_close", "raw_vwap", "adj_factor",
        "volume", "amount",
    }
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"摄取结果缺少必需列: {missing}")
    if data.empty or data["asset_id"].isna().any() or data["date"].isna().any():
        raise ValueError("摄取结果为空或包含缺失 asset_id/date")
    if data.duplicated(["asset_id", "date"]).any():
        raise ValueError("摄取结果包含重复 asset_id/date")
    if not data["date"].between(data["date"].min(), data["date"].max()).all():
        raise ValueError("摄取结果日期非法")
    factor = data["adj_factor"].astype("float64")
    if ((~np.isfinite(factor)) | (factor <= 0)).any():
        raise ValueError("摄取结果包含非法 adj_factor")
    valid = data["raw_close"].notna() & data["adj_close"].notna()
    if valid.any():
        rebuilt = data.loc[valid, "raw_close"] * factor.loc[valid]
        error = (rebuilt - data.loc[valid, "adj_close"]).abs()
        scale = data.loc[valid, "adj_close"].abs().clip(lower=1.0)
        if (error > scale * 1e-5).any():
            raise ValueError("摄取结果 raw_close * adj_factor 与 adj_close 不一致")


def _recover_interrupted_swap(output_root: Path) -> None:
    """Restore the newest complete backup when a prior directory swap was interrupted."""
    out_dir = output_root / "daily_prices"
    if out_dir.exists():
        return
    backups = sorted(
        output_root.glob(".daily_prices_backup_*"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if backups:
        backups[0].rename(out_dir)


def ingest_prices(cfg: IngestConfig, *, limit: int | None = None, verbose: bool = True) -> dict:
    """批量转换并按年分区写出 Parquet。返回摄取统计。"""
    files = sorted(Path(cfg.source_dir).glob("*.CSV"))
    if limit:
        files = files[:limit]
    output_root = Path(cfg.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    _recover_interrupted_swap(output_root)
    out_dir = output_root / "daily_prices"

    frames: list[pd.DataFrame] = []
    n_ok = n_fail = 0
    with ProcessPoolExecutor(max_workers=cfg.max_workers) as pool:
        for i, res in enumerate(pool.map(_worker, [(str(f), cfg) for f in files], chunksize=32)):
            if res is None or res.empty:
                n_fail += 1
            else:
                frames.append(res)
                n_ok += 1
            if verbose and (i + 1) % 500 == 0:
                print(f"  ingested {i + 1}/{len(files)} files", flush=True)

    if not frames:
        raise RuntimeError("没有任何文件成功摄取")
    data = pd.concat(frames, ignore_index=True)
    data["asset_id"] = data["asset_id"].astype("category")
    data = data.sort_values(["date", "asset_id"], ignore_index=True)
    _validate_ingested_data(data)

    stage_dir = Path(tempfile.mkdtemp(prefix=".daily_prices_stage_", dir=output_root))
    backup_dir = output_root / f".daily_prices_backup_{uuid.uuid4().hex}"
    final_names: list[str] = []
    try:
        expected_rows = 0
        for year, chunk in data.groupby(data["date"].dt.year, sort=True):
            name = f"daily_prices_{year}.parquet"
            path = stage_dir / name
            chunk.to_parquet(path, index=False, compression="snappy")
            reloaded = pd.read_parquet(path)
            _validate_ingested_data(reloaded)
            if len(reloaded) != len(chunk):
                raise ValueError(f"分区写入行数不一致: {name}")
            expected_rows += len(reloaded)
            final_names.append(name)
        if expected_rows != len(data):
            raise ValueError("全部分区写入行数与源数据不一致")

        if out_dir.exists():
            out_dir.rename(backup_dir)
        try:
            stage_dir.rename(out_dir)
        except Exception:
            if backup_dir.exists() and not out_dir.exists():
                backup_dir.rename(out_dir)
            raise
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
    finally:
        if stage_dir.exists():
            shutil.rmtree(stage_dir)

    written = [str(out_dir / name) for name in final_names]

    stats = {
        "files_total": len(files),
        "files_ok": n_ok,
        "files_failed": n_fail,
        "rows": int(len(data)),
        "assets": int(data["asset_id"].nunique()),
        "date_min": str(data["date"].min().date()),
        "date_max": str(data["date"].max().date()),
        "ohlc_violation_rows": int(data["ohlc_violation"].sum()),
        "zero_volume_rows": int((data["volume"].fillna(0) <= 0).sum()),
        "partitions": written,
    }
    if verbose:
        print(stats["files_ok"], "assets ->", stats["rows"], "rows")
    return stats
